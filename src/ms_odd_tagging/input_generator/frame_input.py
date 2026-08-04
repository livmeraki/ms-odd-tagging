#!/usr/bin/env python3
"""Generate timestamp-sampled, single-frame model inputs and BEV images."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from ms_odd_tagging.tagger.rule_based.registry import (
    detect_recording_events,
    load_config,
)
from ms_odd_tagging.tagger.rule_based.scenario_event import ScenarioEvent
from ms_odd_tagging.common.config import CANONICAL, FRAME_INPUTS
from ms_odd_tagging.common.progress import ProgressReporter
from ms_odd_tagging.input_generator.generation_profile import (
    GenerationProfiler,
    finalize_profile,
)

from .model_input import (
    DEFAULT_LD_LINE_PATTERNS,
    DEFAULT_LD_ROADMARK_CLASSES,
    count_objects_by_type,
    ensure_dir,
    parse_csv_set,
    portable_path,
    r4,
    render_bev_model_png,
    safe_name,
)


DEFAULT_INPUT_DIR = CANONICAL
DEFAULT_OUTPUT_DIR = FRAME_INPUTS
SCHEMA_VERSION = "odld-dynamic-frame-model-input-v1"
BEV_SCHEMA_VERSION = "odld-per-frame-bev-v1"
DEFAULT_FRAMES_PER_SECOND = 1.0
LONG_VEHICLE_CLASSES = {"truck", "truck_head", "bus", "trailer"}


def following_lane_intervals_to_events(lane_result: dict[str, Any]) -> list[ScenarioEvent]:
    """Serialize following-lane frame states as normal recording-level events."""
    events: list[ScenarioEvent] = []
    for interval in lane_result.get("intervals", []):
        scenario = interval.get("scenario")
        if scenario not in {
            "following_lane_with_lead",
            "following_lane_without_lead",
        }:
            continue
        start_frame = interval.get("start_frame_index")
        end_frame = interval.get("end_frame_index")
        start_time = interval.get("start_time_since_start_s")
        end_time = interval.get("end_time_since_start_s")
        if not all(
            isinstance(value, (int, float))
            for value in (start_frame, end_frame, start_time, end_time)
        ):
            continue
        duration_s = max(0.0, float(end_time) - float(start_time))
        events.append(
            ScenarioEvent(
                scenario=str(scenario),
                start_frame=int(start_frame),
                end_frame=int(end_frame),
                start_timestamp_s=float(start_time),
                end_timestamp_s=float(end_time),
                duration_s=round(duration_s, 6),
                detector_version="following-lane-frame-tags-v1",
                evidence={
                    "source_detector": "following_lane",
                    "frame_count": interval.get("frame_count"),
                    "boundary_convention": interval.get("boundary_convention"),
                    "start_timestamp_unix_s": interval.get("start_timestamp_unix_s"),
                    "end_timestamp_unix_s": interval.get("end_timestamp_unix_s"),
                },
            )
        )
    return events


def build_direct_derivation_context(
    frame_index: int,
    events: list[Any],
    enabled_scenarios: set[str],
    lane_frame: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build auditable frame labels from recording rules and the lane tracker."""
    active_events = []
    labels: dict[str, bool | None] = {
        scenario: False for scenario in enabled_scenarios
    }
    for event in events:
        item = event.to_dict() if hasattr(event, "to_dict") else event
        if item["start_frame"] <= frame_index <= item["end_frame"]:
            active_events.append(item)
            labels[item["scenario"]] = True

    if lane_frame:
        state = lane_frame.get("state")
        if state in {
            "following_lane_with_lead",
            "following_lane_without_lead",
        }:
            labels["following_lane_with_lead"] = (
                state == "following_lane_with_lead"
            )
            labels["following_lane_without_lead"] = (
                state == "following_lane_without_lead"
            )
            lead = lane_frame.get("lead")
            lead_class = str((lead or {}).get("class") or "").lower()
            labels["behind_bike"] = bool(lead and lead_class == "bicycle")
            labels["behind_motorcycle"] = bool(
                lead and lead_class == "motorcycle"
            )
            labels["behind_long_vehicle"] = bool(
                lead and lead_class in LONG_VEHICLE_CLASSES
            )
        elif state == "not_applicable":
            for scenario in (
                "following_lane_with_lead",
                "following_lane_without_lead",
                "behind_bike",
                "behind_motorcycle",
                "behind_long_vehicle",
            ):
                labels[scenario] = False
        else:
            for scenario in (
                "following_lane_with_lead",
                "following_lane_without_lead",
                "behind_bike",
                "behind_motorcycle",
                "behind_long_vehicle",
            ):
                labels[scenario] = None

    return {
        "directly_derived_labels": labels,
        "rule_based_reference": {
            "active_labels": sorted(
                label for label, value in labels.items() if value is True
            ),
            "active_events": active_events,
            "lane_tracker": lane_frame,
        },
    }


def canonical_recording_id(path: Path) -> str:
    for suffix in ("_canonical_odld_frames.json", "_canonical_frames.json"):
        if path.name.endswith(suffix):
            return path.name[: -len(suffix)]
    return path.stem


def select_canonical_files(input_dir: Path) -> list[Path]:
    selected: dict[str, Path] = {}
    for path in sorted(input_dir.glob("*_canonical*_frames.json")):
        recording_id = canonical_recording_id(path)
        current = selected.get(recording_id)
        if current is None or path.name.endswith("_canonical_odld_frames.json"):
            selected[recording_id] = path
    return [selected[key] for key in sorted(selected)]


def frame_id(recording_id: str, frame_index: int) -> str:
    return f"{recording_id}:frame-{frame_index:06d}"


def finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def sample_frames_by_rate(
    frames: list[dict[str, Any]], frames_per_second: float | None
) -> list[dict[str, Any]]:
    """Select frames on a timestamp grid; ``None`` preserves every frame."""
    if frames_per_second is None:
        return list(frames)
    if not finite_number(frames_per_second) or frames_per_second <= 0:
        raise ValueError("frames_per_second must be a positive finite number")
    if not frames:
        return []

    period_s = 1.0 / float(frames_per_second)
    selected: list[dict[str, Any]] = []
    next_sample_time: float | None = None
    for frame in frames:
        timestamp = frame.get("time_since_start_s")
        if not finite_number(timestamp):
            continue
        timestamp = float(timestamp)
        if next_sample_time is None:
            selected.append(frame)
            next_sample_time = timestamp + period_s
            continue
        if timestamp + 1e-9 < next_sample_time:
            continue
        selected.append(frame)
        while next_sample_time <= timestamp + 1e-9:
            next_sample_time += period_s
    return selected


def compact_objects(frame: dict[str, Any], max_objects: int) -> list[dict[str, Any]]:
    def distance_key(obj: dict[str, Any]) -> float:
        distance = obj.get("position_ego_m", {}).get("distance")
        return float(distance) if finite_number(distance) else float("inf")

    objects = sorted(
        frame.get("objects", []),
        key=lambda obj: (
            distance_key(obj),
            str(obj.get("object_id", "")),
        ),
    )[:max_objects]
    keep = (
        "object_id",
        "class",
        "subclass",
        "annotation_type",
        "geometry_source",
        "position_lcs_m",
        "position_ego_m",
        "dimensions_m",
        "heading_relative_rad",
        "velocity_lcs_mps",
        "relative_velocity_ego_mps",
    )
    return [r4({key: obj.get(key) for key in keep}) for obj in objects]


def build_frame_json(
    recording: dict[str, Any],
    frame: dict[str, Any],
    source_path: Path,
    bev_filename: str,
    *,
    max_objects: int,
) -> dict[str, Any]:
    frame_index = frame["frame_index"]
    objects = frame.get("objects", [])
    counts = count_objects_by_type(objects)
    speed = frame.get("ego", {}).get("speed_mps")
    return {
        "schema_version": SCHEMA_VERSION,
        "recording_id": recording["recording_id"],
        "frame_id": frame_id(recording["recording_id"], frame_index),
        "source_canonical_file": portable_path(source_path),
        "frame_index": frame_index,
        "timestamp_unix_s": frame.get("timestamp_unix_s"),
        "time_since_start_s": r4(frame["time_since_start_s"]),
        "taxonomy": recording.get("scenario_taxonomy"),
        "bev": {
            "schema_version": BEV_SCHEMA_VERSION,
            "frame_index": frame_index,
            "path": bev_filename,
            "format": "png",
            "audience": "model",
        },
        "ego": r4(frame.get("ego", {})),
        "scenario_signals": r4(frame.get("scenario_signals", {})),
        "object_counts": {
            **counts,
            "nearby_pedestrian_count_30m": frame.get("scenario_signals", {})
            .get("nearby_30m_counts", {})
            .get("pedestrian"),
            "nearby_motorcycle_count_30m": frame.get("scenario_signals", {})
            .get("nearby_30m_counts", {})
            .get("motorcycle"),
        },
        "objects": compact_objects(frame, max_objects),
        "interaction_candidates": r4(frame.get("interaction_candidates", [])),
        "ld": r4(frame.get("ld", {})),
        "data_quality": {
            "speed_valid": finite_number(speed) and speed >= 0,
            "object_state_count": len(objects),
            "objects_truncated": len(objects) > max_objects,
            "ld_available": frame.get("ld", {}).get("available") is True,
        },
        "data_notes": [
            "This record represents exactly one canonical frame.",
            "The BEV is ego-centric at this same frame; no temporal keyframe sampling is used.",
            "Scenario labels are intentionally excluded from model input to prevent leakage.",
        ],
    }


def build_recording(
    canonical_path: Path,
    output_dir: Path,
    *,
    extent: tuple[float, float, float, float],
    size: tuple[int, int],
    ld_filters: dict[str, set[str]],
    max_objects: int,
    frames_per_second: float | None = DEFAULT_FRAMES_PER_SECOND,
    frame_limit: int | None = None,
    profiler: GenerationProfiler | None = None,
) -> tuple[dict[str, Any], int]:
    recording = json.loads(canonical_path.read_text(encoding="utf-8"))
    recording["_source_file"] = str(canonical_path)
    recording_id = recording["recording_id"]
    if profiler is not None:
        profiler.start_recording(recording_id, [canonical_path])
    frames = sample_frames_by_rate(recording.get("frames", []), frames_per_second)
    if frame_limit is not None:
        frames = frames[:frame_limit]

    recording_dir = output_dir / safe_name(recording_id)
    ensure_dir(recording_dir)
    config = load_config()
    events, quality = detect_recording_events(recording, config)
    from ms_odd_tagging.scenarios.following_lane.detector import run_following_lane

    lane_result = run_following_lane(recording)
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
    rule_path.write_text(
        json.dumps(
            {
                "schema_version": "rule-based-scenario-events-v1",
                "recording_id": recording_id,
                "rule_config_version": config["config_version"],
                "interval_boundary_convention": "inclusive_samples",
                "rule_based_events": [event.to_dict() for event in events],
                "data_quality": quality,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if profiler is not None:
        profiler.add_output_files([rule_path])

    rows = []
    progress = ProgressReporter(f"frame-input {recording_id}", len(frames), "frame")
    progress.start()
    for frame in frames:
        sample_start = profiler.sample_start() if profiler is not None else 0.0
        index = frame["frame_index"]
        directory = recording_dir / f"frame_{index:06d}"
        ensure_dir(directory)
        bev_path = directory / "bev.png"
        # The renderer only consumes ``frames``; this adapter deliberately has
        # no temporal-window identity or neighboring samples.
        frame_context = {"frames": [frame]}
        render_bev_model_png(
            recording,
            frame_context,
            index,
            "current",
            bev_path,
            extent,
            size,
            ld_filters=ld_filters,
        )
        frame_path = directory / "frame.json"
        derivation_context = build_direct_derivation_context(
            index,
            events,
            set(config["enabled_scenarios"]),
            lane_frames.get(index),
        )
        payload = build_frame_json(
            recording,
            frame,
            canonical_path,
            bev_path.name,
            max_objects=max_objects,
        )
        frame_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        gt_reference_path = directory / "gt_reference.json"
        gt_reference_path.write_text(
            json.dumps(derivation_context, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if profiler is not None:
            profiler.record_sample(
                index, sample_start, [bev_path, frame_path, gt_reference_path]
            )
        rows.append(
            {
                "frame_id": payload["frame_id"],
                "frame_index": index,
                "time_since_start_s": payload["time_since_start_s"],
                "directory": str(directory),
                "frame_json": str(frame_path),
                "bev": str(bev_path),
            }
        )
        progress.advance(f"frame {index}")

    if profiler is not None:
        profiler.finish_recording()

    return {
        "recording_id": recording_id,
        "source_canonical_file": str(canonical_path),
        "canonical_frame_count": len(recording.get("frames", [])),
        "generated_frame_count": len(rows),
        "frames_per_second": frames_per_second,
        "recording_rule_events": str(rule_path),
        "frames": rows,
    }, len(rows)


def write_readme(output_dir: Path) -> None:
    (output_dir / "README.md").write_text(
        """# Per-frame model inputs

Generated directly from canonical recordings. Every selected frame produces
one `frame_XXXXXX/frame.json` and one same-frame `bev.png`. There are no
overlapping windows and no start/middle/end keyframes. Recording-level
deterministic events are stored once in `recording_rule_events.json`.

BEV generation is timestamp-sampled at 1 frame per second by default. Use
`--frames-per-second` to change the rate or `--all-frames` to disable sampling.
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate timestamp-sampled single-frame JSON inputs and BEV PNGs."
    )
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--recording", action="append")
    parser.add_argument("--frame-limit", type=int, default=None)
    sampling = parser.add_mutually_exclusive_group()
    sampling.add_argument(
        "--frames-per-second",
        type=float,
        default=DEFAULT_FRAMES_PER_SECOND,
        help="Timestamp-based BEV sampling rate (default: 1.0).",
    )
    sampling.add_argument(
        "--all-frames",
        action="store_true",
        help="Generate model input and BEV artifacts for every canonical frame.",
    )
    parser.add_argument("--max-objects", type=int, default=80)
    parser.add_argument("--width", type=int, default=1000)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--left-m", type=float, default=45.0)
    parser.add_argument("--right-m", type=float, default=45.0)
    parser.add_argument("--back-m", type=float, default=25.0)
    parser.add_argument("--forward-m", type=float, default=95.0)
    parser.add_argument("--ld-line-patterns", default="solid,dashed")
    parser.add_argument("--ld-roadmark-classes", default="crosswalk,stopline")
    parser.add_argument("--ld-boundary-attributes", default="")
    parser.add_argument(
        "--profile-generation",
        action="store_true",
        help="Write optional time and storage profiling artifacts under output_dir/profiling.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_dir(args.output_dir)
    write_readme(args.output_dir)
    requested = set(args.recording or [])
    files = [
        path
        for path in select_canonical_files(args.input_dir)
        if not requested or canonical_recording_id(path) in requested
    ]
    ld_filters = {
        "line_patterns": parse_csv_set(args.ld_line_patterns)
        or set(DEFAULT_LD_LINE_PATTERNS),
        "roadmark_classes": parse_csv_set(args.ld_roadmark_classes)
        or set(DEFAULT_LD_ROADMARK_CLASSES),
        "boundary_attributes": parse_csv_set(args.ld_boundary_attributes),
    }
    manifest = {
        "schema_version": "odld-per-frame-input-manifest-v1",
        "input_dir": str(args.input_dir),
        "output_dir": str(args.output_dir),
        "generation_mode": "one_bev_per_selected_canonical_frame",
        "frames_per_second": None if args.all_frames else args.frames_per_second,
        "recordings": [],
    }
    converted = []
    profiler = GenerationProfiler(args.output_dir) if args.profile_generation else None
    recording_progress = ProgressReporter("frame-input recordings", len(files), "recording")
    recording_progress.start()
    for path in files:
        summary, count = build_recording(
            path,
            args.output_dir,
            extent=(args.left_m, args.right_m, args.back_m, args.forward_m),
            size=(args.width, args.height),
            ld_filters=ld_filters,
            max_objects=args.max_objects,
            frames_per_second=None if args.all_frames else args.frames_per_second,
            frame_limit=args.frame_limit,
            profiler=profiler,
        )
        manifest["recordings"].append(summary)
        converted.append((summary["recording_id"], count))
        recording_progress.advance(f"{summary['recording_id']}: {count} frames")
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Converted {len(converted)} recording(s), {sum(n for _, n in converted)} frame(s).")
    print(f"Wrote {manifest_path}")
    for recording_id, count in converted:
        print(f"- {recording_id}: {count} frames / {count} BEVs")
    finalize_profile(profiler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
