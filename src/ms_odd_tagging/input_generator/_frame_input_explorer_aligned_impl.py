#!/usr/bin/env python3
"""Generate canonical explorer-aligned per-frame inputs."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

from ms_odd_tagging.common.atomic_io import atomic_write_text, staged_directory
from ms_odd_tagging.tagger.rule_based.registry import (
    detect_recording_events,
    load_config,
)
from ms_odd_tagging.common.config import CANONICAL, FRAME_INPUTS_REVISED
from ms_odd_tagging.common.progress import ProgressReporter
from ms_odd_tagging.input_generator.generation_profile import (
    GenerationProfiler,
    finalize_profile,
)
from ms_odd_tagging.input_generator.frame_tags import (
    export_frame_tag_files,
    scenario_key_set,
)
from ms_odd_tagging.input_generator.recording_analysis_cache import (
    get_recording_analysis,
)

from .frame_input import (
    DEFAULT_FRAMES_PER_SECOND,
    build_direct_derivation_context,
    build_frame_json,
    canonical_recording_id,
    following_lane_intervals_to_events,
    sample_frames_by_rate,
    select_canonical_files,
)
from .model_input import ensure_dir, safe_name
from .revised_bev import centered_extent, render_revised_bev_png


DEFAULT_INPUT_DIR = CANONICAL
DEFAULT_OUTPUT_DIR = FRAME_INPUTS_REVISED


def build_recording(
    canonical_path: Path,
    output_dir: Path,
    *,
    extent: tuple[float, float, float, float],
    size: tuple[int, int],
    max_objects: int,
    frames_per_second: float | None = DEFAULT_FRAMES_PER_SECOND,
    frame_limit: int | None = None,
    profiler: GenerationProfiler | None = None,
    refresh_analysis: bool = False,
) -> tuple[dict, int]:
    recording = json.loads(canonical_path.read_text(encoding="utf-8"))
    recording_id = recording["recording_id"]
    if profiler is not None:
        profiler.start_recording(recording_id, [canonical_path])
    selected_frames = sample_frames_by_rate(recording.get("frames", []), frames_per_second)
    if frame_limit is not None:
        selected_frames = selected_frames[:frame_limit]

    recording_dir = output_dir / safe_name(recording_id)
    ensure_dir(recording_dir)
    config = load_config()
    from ms_odd_tagging.scenarios.following_lane.detector import run_following_lane

    events, quality, lane_result, analysis_cache_hit = get_recording_analysis(
        canonical_path=canonical_path,
        recording=recording,
        recording_dir=recording_dir,
        config=config,
        detect_recording_events=detect_recording_events,
        run_following_lane=run_following_lane,
        refresh=refresh_analysis,
    )
    print(
        f"Recording analysis {recording_id}: "
        f"{'cache hit' if analysis_cache_hit else 'computed and cached'}",
        flush=True,
    )
    lane_frames = {
        item["frame_index"]: item for item in lane_result.get("frames", [])
    }
    events = [*events, *following_lane_intervals_to_events(lane_result)]
    events.sort(
        key=lambda event: (
            event.start_timestamp_s,
            event.scenario,
            event.end_timestamp_s,
        )
    )
    rule_path = recording_dir / "recording_rule_events.json"
    atomic_write_text(
        rule_path,
        json.dumps(
            {
                "schema_version": "rule-based-scenario-events-v1",
                "recording_id": recording_id,
                "interval_boundary_convention": "inclusive_samples",
                "rule_based_events": [event.to_dict() for event in events],
                "data_quality": quality,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    frame_tags_dir = recording_dir / "recording_frame_tags_1fps"
    frame_tags_manifest = export_frame_tag_files(
        recording_id=recording_id,
        frames=recording.get("frames", []),
        events=events,
        output_dir=frame_tags_dir,
        scenarios=scenario_key_set(
            events=events,
            configured_scenarios=config["enabled_scenarios"],
        ),
        rule_config_version=config.get("config_version"),
        source_event_json=rule_path.name,
    )
    if profiler is not None:
        profiler.add_output_files(
            [rule_path, frame_tags_dir / "manifest.json"]
            + [frame_tags_dir / row["path"] for row in frame_tags_manifest["frames"]]
        )

    rows = []
    progress = ProgressReporter(
        f"frame-input {recording_id}", len(selected_frames), "frame"
    )
    progress.start()
    for frame in selected_frames:
        sample_start = profiler.sample_start() if profiler is not None else 0.0
        index = frame["frame_index"]
        final_frame_dir = recording_dir / f"frame_{index:06d}"
        lane_frame = lane_frames.get(index)
        derivation_context = build_direct_derivation_context(
            index,
            events,
            set(config["enabled_scenarios"]),
            lane_frame,
        )
        crossing_config = config["object_path_crossing_interactions"]

        with staged_directory(final_frame_dir) as frame_dir:
            bev_path = frame_dir / "bev.png"
            render_revised_bev_png(
                recording,
                frame,
                bev_path,
                extent,
                size,
                lane_context=lane_frame,
                proximity_radius_m=float(
                    config["object_relations"]["generic_proximity_radius_m"]
                ),
                crossing_arc=(
                    float(crossing_config["arc_inner_radius_m"]),
                    float(crossing_config["arc_outer_radius_m"]),
                    float(crossing_config["arc_half_angle_deg"]),
                ),
                debug_context=derivation_context,
            )
            payload = build_frame_json(
                recording,
                frame,
                canonical_path,
                bev_path.name,
                max_objects=max_objects,
            )
            centered_left, centered_right, centered_back, centered_forward = centered_extent(extent)
            payload["bev"].update(
                {
                    "renderer": "explorer-aligned-revised-v1",
                    "orientation": "ego-heading-up",
                    "ego_position": "center",
                    "annotations": [
                        "footprint_proximity_boundary",
                        "phase3c_forward_arc",
                        "active_rule_object_highlight",
                    ],
                    "footprint_proximity_radius_m": float(
                        config["object_relations"]["generic_proximity_radius_m"]
                    ),
                    "extent_m": {
                        "left": centered_left,
                        "right": centered_right,
                        "behind": centered_back,
                        "ahead": centered_forward,
                    },
                    "configured_extent_m": {
                        "left": extent[0],
                        "right": extent[1],
                        "behind": extent[2],
                        "ahead": extent[3],
                    },
                }
            )
            frame_path = frame_dir / "frame.json"
            frame_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            gt_reference_path = frame_dir / "gt_reference.json"
            gt_reference_path.write_text(
                json.dumps(derivation_context, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        final_bev_path = final_frame_dir / "bev.png"
        final_frame_path = final_frame_dir / "frame.json"
        final_gt_reference_path = final_frame_dir / "gt_reference.json"
        if profiler is not None:
            profiler.record_sample(
                index,
                sample_start,
                [final_bev_path, final_frame_path, final_gt_reference_path],
            )
        rows.append(
            {
                "recording_id": recording_id,
                "frame_id": payload["frame_id"],
                "frame_index": index,
                "time_since_start_s": payload["time_since_start_s"],
                "frame_json": str(final_frame_path),
                "bev": str(final_bev_path),
                "relative_bev": final_bev_path.relative_to(output_dir).as_posix(),
            }
        )
        progress.advance(f"frame {index}")

    if profiler is not None:
        profiler.finish_recording()

    return {
        "recording_id": recording_id,
        "canonical_frame_count": len(recording.get("frames", [])),
        "generated_frame_count": len(rows),
        "frames_per_second": frames_per_second,
        "analysis_cache_hit": analysis_cache_hit,
        "recording_frame_tags": str(frame_tags_dir),
        "frames": rows,
    }, len(rows)


def write_review_html(output_dir: Path, rows: list[dict]) -> Path:
    cards = []
    for row in rows:
        cards.append(
            '<article class="frame-card">'
            f'<img src="{html.escape(row["relative_bev"])}" alt="BEV for {html.escape(row["frame_id"])}">'
            f'<div><b>{html.escape(row["recording_id"])}</b><br>'
            f'frame {row["frame_index"]} · {row["time_since_start_s"]:.3f}s</div>'
            "</article>"
        )
    path = output_dir / "bev_review.html"
    atomic_write_text(
        path,
        """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Per-frame BEV review</title><style>
body{font-family:Arial,sans-serif;margin:24px;background:#f8fafc;color:#0f172a}
h1{font-size:22px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:18px}
.frame-card{background:white;border:1px solid #cbd5e1;border-radius:8px;overflow:hidden}
.frame-card img{display:block;width:100%;height:auto}.frame-card div{padding:10px 12px;line-height:1.45}
</style></head><body><h1>Ego-heading-up BEVs</h1><main class="grid">
"""
        + "\n".join(cards)
        + "\n</main></body></html>\n",
    )
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate explorer-aligned per-frame inputs.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--recording", action="append")
    parser.add_argument("--frame-limit", type=int)
    sampling = parser.add_mutually_exclusive_group()
    sampling.add_argument("--frames-per-second", type=float, default=DEFAULT_FRAMES_PER_SECOND)
    sampling.add_argument("--all-frames", action="store_true")
    parser.add_argument("--max-objects", type=int, default=80)
    # The centered default extent is 90 m wide by 120 m long (3:4).
    parser.add_argument("--width", type=int, default=900)
    parser.add_argument("--height", type=int, default=1200)
    parser.add_argument("--left-m", type=float, default=45.0)
    parser.add_argument("--right-m", type=float, default=45.0)
    parser.add_argument("--back-m", type=float, default=25.0)
    parser.add_argument("--forward-m", type=float, default=95.0)
    parser.add_argument(
        "--refresh-analysis",
        action="store_true",
        help="Ignore cached recording-wide rule/lane analysis and recompute it.",
    )
    parser.add_argument(
        "--profile-generation",
        action="store_true",
        help="Write optional time and storage profiling artifacts under output_dir/profiling.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_dir(args.output_dir)
    requested = set(args.recording or [])
    files = [
        path for path in select_canonical_files(args.input_dir)
        if not requested or canonical_recording_id(path) in requested
    ]
    manifest = {
        "schema_version": "odld-per-frame-input-manifest-v1",
        "renderer": "explorer-aligned-revised-v1",
        "orientation": "ego-heading-up",
        "frames_per_second": None if args.all_frames else args.frames_per_second,
        "recordings": [],
    }
    review_rows = []
    profiler = GenerationProfiler(args.output_dir) if args.profile_generation else None
    recording_progress = ProgressReporter(
        "frame-input recordings", len(files), "recording"
    )
    recording_progress.start()
    for path in files:
        summary, _ = build_recording(
            path,
            args.output_dir,
            extent=(args.left_m, args.right_m, args.back_m, args.forward_m),
            size=(args.width, args.height),
            max_objects=args.max_objects,
            frames_per_second=None if args.all_frames else args.frames_per_second,
            frame_limit=args.frame_limit,
            profiler=profiler,
            refresh_analysis=args.refresh_analysis,
        )
        manifest["recordings"].append(summary)
        review_rows.extend(summary["frames"])
        recording_progress.advance(
            f"{summary['recording_id']}: {summary['generated_frame_count']} frames"
        )
    atomic_write_text(
        args.output_dir / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2),
    )
    review_path = write_review_html(args.output_dir, review_rows)
    print(f"Generated {len(review_rows)} BEV(s).")
    print(f"Review: {review_path}")
    finalize_profile(profiler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
