#!/usr/bin/env python3
"""Build a human-editable GT label file from refined model inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


TAXONOMY = [
    "stationary",
    "high_magnitude_speed",
    "low_magnitude_speed",
    "medium_magnitude_speed",
    "following_lane_with_lead",
    "following_lane_without_lead",
    "starting_left_turn",
    "starting_right_turn",
    "stopping_with_lead",
    "stopping_without_lead",
    "near_multiple_pedestrians",
    "near_multiple_motorcycle",
]
SPEED_LABELS = [
    "high_magnitude_speed",
    "low_magnitude_speed",
    "medium_magnitude_speed",
]


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
        help="Output GT JSON path. Defaults to gt_labels/<recording>_gt.json.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output or Path("gt_labels") / f"{args.recording}_gt.json"
    payload = build_gt_payload(args.model_input_root, args.recording, output)
    write_json(output, payload)
    print(f"Wrote {output}")
    print(f"Windows: {len(payload['windows'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
