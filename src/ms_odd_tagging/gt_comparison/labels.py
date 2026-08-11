#!/usr/bin/env python3
"""Build human-editable GT labels from active frame or legacy window inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ms_odd_tagging.common.config import DATA_GT


SCENARIO_GROUPS = [
    {
        "id": "phase1_motion",
        "label": "Phase 1 · Ego motion",
        "implemented": True,
        "scenarios": [
            "stationary",
            "low_magnitude_speed",
            "medium_magnitude_speed",
            "high_magnitude_speed",
            "high_lateral_acceleration",
            "high_magnitude_jerk",
            "starting_left_turn",
            "starting_right_turn",
            "starting_low_speed_turn",
            "starting_high_speed_turn",
        ],
    },
    {
        "id": "lane_relations",
        "label": "Lane following and Phase 2 lane change",
        "implemented": True,
        "scenarios": [
            "following_lane_with_lead",
            "following_lane_without_lead",
            "changing_lane",
            "changing_lane_to_left",
            "changing_lane_to_right",
        ],
    },
    {
        "id": "phase2b_crosswalk",
        "label": "Phase 2B · Crosswalk and stopline",
        "implemented": True,
        "scenarios": [
            "traversing_crosswalk",
            "on_stopline_crosswalk",
            "stationary_at_crosswalk",
            "stopping_at_crosswalk",
            "accelerating_at_crosswalk",
        ],
    },
    {
        "id": "phase3a_near_objects",
        "label": "Phase 3A · Nearby objects",
        "implemented": True,
        "scenarios": [
            "near_high_speed_vehicle",
            "near_long_vehicle",
            "near_multiple_bikes",
            "near_multiple_motorcycle",
            "near_multiple_pedestrians",
            "near_multiple_vehicles",
        ],
    },
    {
        "id": "phase3b_pedestrian_crosswalk",
        "label": "Phase 3B · Pedestrian and crosswalk",
        "implemented": True,
        "scenarios": [
            "near_pedestrian_on_crosswalk",
            "near_pedestrian_on_crosswalk_with_ego",
        ],
    },
    {
        "id": "phase3c_path_crossing",
        "label": "Phase 3C · Crossing the ego path",
        "implemented": True,
        "scenarios": [
            "crossed_by_bike",
            "crossed_by_motorcycle",
            "crossed_by_vehicle",
        ],
    },
    {
        "id": "phase4_traffic_interactions",
        "label": "Phase 4 · Traffic interactions",
        "implemented": True,
        "scenarios": [
            "following_lane_with_slow_lead",
            "changing_lane_with_lead",
            "changing_lane_with_trail",
            "stopping_with_lead",
            "stopping_without_lead",
            "stationary_in_traffic",
            "behind_bike",
            "behind_long_vehicle",
            "behind_pedestrian_on_driveable",
            "waiting_for_pedestrian_to_cross",
            "near_barrier_on_driveable",
        ],
    },
    {
        "id": "vlm_intersection_and_traffic_light",
        "label": "VLM-assisted intersection and traffic light",
        "implemented": False,
        "support": "qwen_vlm_poc",
        "scenarios": [
            "starting_straight_traffic_light_intersection_traversal",
            "starting_u_turn",
            "on_intersection",
            "on_traffic_light_intersection",
            "on_stopline_traffic_light",
            "accelerating_at_traffic_light",
            "traversing_traffic_light_intersection",
            "accelerating_at_traffic_light_with_lead",
            "accelerating_at_traffic_light_without_lead",
            "stationary_at_traffic_light_with_lead",
            "stationary_at_traffic_light_without_lead",
            "stopping_at_traffic_light_with_lead",
            "stopping_at_traffic_light_without_lead",
        ],
    },
    {
        "id": "manual_only_taxonomy",
        "label": "Manual-only taxonomy",
        "implemented": False,
        "support": "manual",
        "scenarios": [
            "traversing_intersection",
            "on_carpark",
            "behind_motorcycle",
        ],
    },
]
TAXONOMY = [
    scenario
    for group in SCENARIO_GROUPS
    for scenario in group["scenarios"]
]
IMPLEMENTED_SCENARIOS = [
    scenario
    for group in SCENARIO_GROUPS
    if group["implemented"]
    for scenario in group["scenarios"]
]
VLM_ASSISTED_SCENARIOS = [
    scenario
    for group in SCENARIO_GROUPS
    if group.get("support") == "qwen_vlm_poc"
    for scenario in group["scenarios"]
]
MINIMUM_REVIEW_FRAME_INDEX = 5
SPEED_LABELS = [
    "stationary",
    "high_magnitude_speed",
    "low_magnitude_speed",
    "medium_magnitude_speed",
]


def find_frame_files(model_input_root: Path, recording: str) -> list[Path]:
    """Return sampled per-frame model inputs in real frame order."""
    recording_root = model_input_root / recording
    if not recording_root.exists():
        raise FileNotFoundError(f"Recording frame-input folder not found: {recording_root}")
    files = sorted(recording_root.rglob("frame.json"))
    if not files:
        raise FileNotFoundError(f"No frame.json files found under {recording_root}")
    return files


def speed_band_from_frame(speed_mps: float | int | None) -> str | None:
    """Classify one valid frame speed using the dynamic tagging thresholds."""
    if not isinstance(speed_mps, (int, float)) or isinstance(speed_mps, bool):
        return None
    speed = float(speed_mps)
    if speed < 0 or speed != speed or speed in (float("inf"), float("-inf")):
        return None
    if speed >= 15.0:
        return "high_magnitude_speed"
    if speed >= 5.0:
        return "medium_magnitude_speed"
    if speed >= 0.5:
        return "low_magnitude_speed"
    return "stationary"


def existing_frames(path: Path | None) -> dict[str, dict]:
    if path is None or not path.exists():
        return {}
    payload = load_json(path)
    frames = payload.get("frames") if isinstance(payload, dict) else None
    if isinstance(frames, dict):
        return {str(key): value for key, value in frames.items() if isinstance(value, dict)}
    if isinstance(frames, list):
        return {
            str(item["frame_id"]): item
            for item in frames
            if isinstance(item, dict) and item.get("frame_id") is not None
        }
    return {}


def labels_with_frame_speed(
    existing_labels: dict | None,
    speed_mps: float | int | None,
    derived_labels: dict | None = None,
) -> dict[str, bool | None]:
    labels = {
        label: existing_labels.get(label) if isinstance(existing_labels, dict) else None
        for label in TAXONOMY
    }
    speed_band = speed_band_from_frame(speed_mps)
    for label in SPEED_LABELS:
        labels[label] = None if speed_band is None else label == speed_band
    if isinstance(derived_labels, dict):
        for label in TAXONOMY:
            value = derived_labels.get(label)
            if isinstance(value, bool):
                labels[label] = value
    return labels


def build_frame_gt_payload(
    model_input_root: Path,
    recording: str,
    existing_gt_path: Path | None = None,
) -> dict:
    """Build comparison-ready GT rows for sampled independent frames."""
    prior_frames = existing_frames(existing_gt_path)
    frames = {}
    directly_derived_fields = set(SPEED_LABELS)
    for frame_path in find_frame_files(model_input_root, recording):
        frame = load_json(frame_path)
        frame_id = str(frame.get("frame_id") or frame_path.parent.name)
        prior = prior_frames.get(frame_id, {})
        ego = frame.get("ego") if isinstance(frame.get("ego"), dict) else {}
        speed = ego.get("speed_mps")
        reference_path = frame_path.with_name("gt_reference.json")
        reference = load_json(reference_path) if reference_path.is_file() else {}
        derived = reference.get("directly_derived_labels", {})
        if not isinstance(derived, dict):
            derived = {}
        directly_derived_fields.update(
            label
            for label, value in derived.items()
            if label in TAXONOMY and isinstance(value, bool)
        )
        frames[frame_id] = {
            "frame_id": frame_id,
            "frame_index": frame.get("frame_index"),
            "timestamp_unix_s": frame.get("timestamp_unix_s"),
            "time_since_start_s": frame.get("time_since_start_s"),
            "reference": {
                "speed_mps": speed,
                "speed_formula_label": speed_band_from_frame(speed),
            },
            "labels": labels_with_frame_speed(prior.get("labels"), speed, derived),
            "confidence": prior.get("confidence"),
            "needs_review": prior.get("needs_review", True),
            "notes": prior.get("notes", ""),
            "reviewer": prior.get("reviewer", ""),
            "reviewed_at": prior.get("reviewed_at", ""),
            "excluded_from_evaluation": (
                isinstance(frame.get("frame_index"), int)
                and frame["frame_index"] < MINIMUM_REVIEW_FRAME_INDEX
            ),
        }
    return {
        "schema_version": "scenario-frame-gt-labels-v1",
        "recording_id": recording,
        "notes": [
            "Human-reviewed labels for independent sampled frames.",
            "Speed labels are filled from the current frame speed only.",
            "Dynamic scenario intervals are not converted into review windows.",
        ],
        "label_fields": TAXONOMY,
        "minimum_scored_frame_index": MINIMUM_REVIEW_FRAME_INDEX,
        "formula_filled_label_fields": [
            label for label in TAXONOMY if label in directly_derived_fields
        ],
        "frames": frames,
    }


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def find_refined_files(model_input_root: Path, recording: str) -> list[Path]:
    recording_root = model_input_root / recording
    if not recording_root.exists():
        raise FileNotFoundError(f"Recording model-input folder not found: {recording_root}")
    files = sorted(recording_root.rglob("refined.json"))
    if not files:
        raise FileNotFoundError(f"No refined.json files found under {recording_root}")
    return files


def speed_band_from_median(median_speed_mps: float | int | None) -> str | None:
    if not isinstance(median_speed_mps, (int, float)):
        return None
    if median_speed_mps >= 15.0:
        return "high_magnitude_speed"
    if median_speed_mps >= 5.0:
        return "medium_magnitude_speed"
    if median_speed_mps >= 0.5:
        return "low_magnitude_speed"
    return None


def existing_windows(path: Path | None) -> dict[str, dict]:
    if path is None or not path.exists():
        return {}
    payload = load_json(path)
    windows = payload.get("windows") if isinstance(payload, dict) else None
    if isinstance(windows, dict):
        return {str(key): value for key, value in windows.items() if isinstance(value, dict)}
    if isinstance(windows, list):
        result = {}
        for item in windows:
            if isinstance(item, dict) and item.get("window_id") is not None:
                result[str(item["window_id"])] = item
        return result
    return {}


def labels_with_formula_speed(
    existing_labels: dict | None,
    median_speed_mps: float | int | None,
) -> dict[str, bool | None]:
    labels = {
        label: existing_labels.get(label) if isinstance(existing_labels, dict) else None
        for label in TAXONOMY
    }
    speed_band = speed_band_from_median(median_speed_mps)
    for label in SPEED_LABELS:
        labels[label] = label == speed_band
    return labels


def build_gt_payload(
    model_input_root: Path,
    recording: str,
    existing_gt_path: Path | None = None,
) -> dict:
    prior_windows = existing_windows(existing_gt_path)
    windows = {}
    for refined_path in find_refined_files(model_input_root, recording):
        refined = load_json(refined_path)
        window_id = refined.get("source_window_id") or refined_path.parent.name
        time_window = refined.get("time_window") if isinstance(refined.get("time_window"), dict) else {}
        ego_summary = refined.get("ego_summary") if isinstance(refined.get("ego_summary"), dict) else {}
        median_speed = ego_summary.get("median_speed_mps")
        prior = prior_windows.get(window_id, {})
        labels = labels_with_formula_speed(prior.get("labels"), median_speed)
        windows[window_id] = {
            "window_id": window_id,
            "start_frame": time_window.get("start_frame"),
            "end_frame": time_window.get("end_frame"),
            "start_time_s": time_window.get("start_time_s"),
            "end_time_s": time_window.get("end_time_s"),
            "reference": {
                "median_speed_mps": median_speed,
                "speed_formula_label": speed_band_from_median(median_speed),
            },
            "labels": labels,
            "confidence": prior.get("confidence"),
            "needs_review": prior.get("needs_review", True),
            "notes": prior.get("notes", ""),
            "reviewer": prior.get("reviewer", ""),
            "reviewed_at": prior.get("reviewed_at", ""),
        }
    return {
        "schema_version": "scenario-gt-labels-v1",
        "recording_id": recording,
        "notes": [
            "Human-editable GT labels for optional comparison during local vLLM runs.",
            "Use true or false for completed GT values; leave unknown labels as null.",
            "Speed-band labels are formula-filled from ego_summary.median_speed_mps using low: 0.5 <= speed < 5, medium: 5 <= speed < 15, high: speed >= 15.",
            "Rerunning this generator preserves non-speed manual labels and refreshes speed-band labels from the formula.",
        ],
        "label_fields": TAXONOMY,
        "formula_filled_label_fields": SPEED_LABELS,
        "windows": windows,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a human-editable GT labels JSON from refined model inputs."
    )
    parser.add_argument("--recording", required=True)
    parser.add_argument("--model-input-root", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output GT JSON path. Defaults to MS_ODD_DATA_ROOT/02_gt/<recording>_gt.json.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output or DATA_GT / f"{args.recording}_gt.json"
    payload = build_gt_payload(args.model_input_root, args.recording, output)
    write_json(output, payload)
    print(f"Wrote {output}")
    print(f"Windows: {len(payload['windows'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
