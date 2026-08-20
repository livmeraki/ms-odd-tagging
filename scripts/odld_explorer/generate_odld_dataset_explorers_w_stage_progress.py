#!/usr/bin/env python3
"""Generate OD+LD explorers with progress reported only for completed work.

This is a thin runner around generate_odld_dataset_explorers_w_scenario_tag.py.
It keeps the same explorer output, but exposes the expensive per-recording
pipeline as 17 concrete stages so long runs do not look frozen.

Tag sourcing is identical to the full scenario-tag generator: compatible
current-config recording events may be reused, otherwise events are regenerated
from canonical data. Legacy overlapping five-second candidate windows are never
used as visualization tags.
"""

from __future__ import annotations

import argparse
import gc
import json
import time
from pathlib import Path

import generate_odld_dataset_explorers_w_scenario_tag as gen


STAGE_NAMES = (
    "load canonical OD+LD JSON",
    "run LD topology classifier",
    "merge topology into canonical frames",
    "load raw OD + trajectory explorer data",
    "build LD visualization payload",
    "build road-feature relations",
    "build object relations",
    "build object path-crossing relations",
    "build traffic-light context",
    "load VLM traffic-light episodes",
    "run following-lane detector",
    "load or regenerate current rule-based scenario events",
    "merge following-lane events into tags",
    "generate debug payloads",
    "serialize explorer HTML",
    "inject lane-tracker visualization",
    "update index + manifest",
)


class StageProgress:
    def __init__(self, recording: str) -> None:
        self.recording = recording
        self.completed = 0
        self.total = len(STAGE_NAMES)
        self._stage_started_at = time.perf_counter()

    def complete(self, detail: str | None = None) -> None:
        elapsed = time.perf_counter() - self._stage_started_at
        self.completed += 1
        name = STAGE_NAMES[self.completed - 1]
        suffix = f" | {detail}" if detail else ""
        print(
            f"[odld-stage:{self.recording}] "
            f"{self.completed}/{self.total} ({self.completed / self.total * 100:5.1f}%) "
            f"complete: {name} [{gen.format_elapsed(elapsed)}]{suffix}",
            flush=True,
        )
        self._stage_started_at = time.perf_counter()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=gen.DEFAULT_SOURCE_ROOT)
    parser.add_argument("--canonical-dir", type=Path, default=gen.DEFAULT_CANONICAL_DIR)
    parser.add_argument("--window-dir", type=Path, default=gen.DEFAULT_WINDOW_DIR)
    parser.add_argument("--output-dir", type=Path, default=gen.DEFAULT_OUTPUT_DIR)
    parser.add_argument("--index-path", type=Path, default=gen.DEFAULT_INDEX_PATH)
    parser.add_argument(
        "--index-from-existing",
        action="store_true",
        help="Rebuild the index/manifest from already generated explorer HTML.",
    )
    parser.add_argument(
        "--regenerate-existing",
        action="store_true",
        help="Regenerate explorer HTML even when the output file already exists.",
    )
    parser.add_argument("recordings", nargs="*")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.index_from_existing:
        rows = sorted(
            gen.existing_rows_by_recording(args.output_dir).values(),
            key=lambda row: row["recording"],
        )
        gen.write_index_and_manifest(args.index_path, args.output_dir, rows)
        return

    canonical_paths = gen.select_canonical_paths(args.canonical_dir, args.recordings)
    rows_by_recording = gen.read_manifest_rows(args.output_dir)
    total_started_at = time.perf_counter()
    completed_recordings = 0

    for canonical_path in canonical_paths:
        recording_started_at = time.perf_counter()
        recording = gen.recording_from_canonical_path(canonical_path)
        output_name = gen.explorer_output_name(recording)
        output_path = args.output_dir / output_name

        if output_path.is_file() and not args.regenerate_existing:
            completed_recordings += 1
            print(
                f"[odld-explorers] {completed_recordings}/{len(canonical_paths)} recordings "
                f"- {recording}: skipped existing explorer",
                flush=True,
            )
            continue

        progress = StageProgress(recording)

        with canonical_path.open(encoding="utf-8") as handle:
            canonical = json.load(handle)
        recording = canonical["recording_id"]
        progress.recording = recording
        progress.complete()

        ld_topology_result = gen.build_ld_topology_result(canonical)
        progress.complete()

        canonical = gen.canonical_with_ld_topology(canonical, ld_topology_result)
        progress.complete()

        scene_dir = args.source_root / recording
        data = gen.build_base_data(scene_dir)
        progress.complete()

        data["ld"] = gen.build_ld_payload(canonical)
        data["ldTopology"] = gen.build_ld_topology_payload(ld_topology_result)
        progress.complete(
            f"{data['ld']['summary']['laneLines']} lane lines, "
            f"{data['ld']['summary']['roadBoundaries']} boundaries"
        )

        data["roadFeatureRelations"] = gen.build_road_feature_payload(canonical)
        progress.complete()

        data["objectRelations"] = gen.build_object_relation_payload(canonical)
        progress.complete()

        data["pathCrossingRelations"] = gen.build_object_path_crossing_payload(canonical)
        progress.complete()

        data["trafficLightContext"] = gen.build_traffic_light_context_payload(canonical)
        progress.complete()

        data["vlmTrafficLightEpisodes"] = gen.build_vlm_traffic_light_episode_payload(recording)
        progress.complete()

        following_lane_result = gen.run_following_lane(canonical)
        progress.complete(
            f"{len(following_lane_result.get('intervals', []))} following-lane intervals"
        )

        data["tags"] = gen.build_tag_payload(recording, args.window_dir, canonical)
        progress.complete(
            f"{len(data['tags'].get('events', []))} current rule/event intervals"
        )

        data["tags"] = gen.add_following_lane_tags(data["tags"], following_lane_result)
        progress.complete(
            f"{len(data['tags']['scenarios'])} scenarios / {len(data['tags']['events'])} intervals"
        )

        debug_counts = gen.write_debug_payloads(scene_dir, canonical, args.output_dir)
        progress.complete(f"{debug_counts['od']} OD + {debug_counts['ld']} LD debug records")

        temp_path = output_path.with_name(f".{output_path.name}.tmp")
        plotly_script_src = gen.ensure_local_plotly_asset(output_path.parent)
        page = (
            gen.scene_html(data, plotly_script_src=plotly_script_src)
            if plotly_script_src
            else gen.scene_html(data)
        )
        temp_path.write_text(page, encoding="utf-8")
        progress.complete(f"{temp_path.stat().st_size / (1024 * 1024):.1f} MiB temporary HTML")

        gen.inject_lane_tracker(temp_path, following_lane_result)
        temp_path.replace(output_path)
        progress.complete()

        rows_by_recording[recording] = gen.row_from_generated_data(
            recording, output_name, data
        )
        current_rows = sorted(
            rows_by_recording.values(), key=lambda row: row["recording"]
        )
        gen.write_index_and_manifest(args.index_path, args.output_dir, current_rows)
        progress.complete()

        completed_recordings += 1
        elapsed = gen.format_elapsed(time.perf_counter() - recording_started_at)
        print(
            f"[odld-explorers] {completed_recordings}/{len(canonical_paths)} recordings "
            f"- {recording}: generated in {elapsed}",
            flush=True,
        )

        del canonical, data
        gc.collect()

    # Reconcile any explorers already present but not represented in the current
    # manifest, then leave one final authoritative index/manifest.
    rows = gen.rebuild_rows_from_outputs(args.output_dir, rows_by_recording)
    gen.write_index_and_manifest(args.index_path, args.output_dir, rows)
    print(
        f"Finished {len(canonical_paths)} recording(s) in "
        f"{gen.format_elapsed(time.perf_counter() - total_started_at)}",
        flush=True,
    )


if __name__ == "__main__":
    main()
