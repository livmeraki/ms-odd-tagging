"""Overlay lane-change PoC results onto current simplified predictions.

Only frames positively tagged as lane changes by the PoC are changed. All
other prediction fields and all non-lane-change maneuver predictions remain
exactly as they are in the current prediction documents.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _frames_by_index(document: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for frame in document.get("frames") or []:
        if isinstance(frame, dict) and isinstance(frame.get("frame_index"), int):
            result[frame["frame_index"]] = frame
    return result


def _maneuver(frame: dict[str, Any]) -> dict[str, Any]:
    tags = frame.get("simplified_tags")
    if not isinstance(tags, dict):
        return {}
    maneuver = tags.get("ego_maneuver")
    return maneuver if isinstance(maneuver, dict) else {}


def merge_recording(
    current: dict[str, Any], poc: dict[str, Any]
) -> tuple[dict[str, Any], int]:
    if current.get("recording_id") != poc.get("recording_id"):
        raise ValueError("Current and PoC recording IDs do not match")

    merged = copy.deepcopy(current)
    poc_frames = _frames_by_index(poc)
    overlaid = 0
    for frame_index, frame in _frames_by_index(merged).items():
        poc_maneuver = _maneuver(poc_frames.get(frame_index, {}))
        if poc_maneuver.get("type") != "lane_change":
            continue
        tags = frame.setdefault("simplified_tags", {})
        tags["ego_maneuver"] = {
            "type": "lane_change",
            "direction": poc_maneuver.get("direction"),
        }
        source = tags.setdefault("source_scenarios", [])
        if isinstance(source, list):
            for label in (
                "changing_lane",
                f"changing_lane_to_{poc_maneuver.get('direction')}",
            ):
                if label not in source and not label.endswith("_None"):
                    source.append(label)
        overlaid += 1

    merged["lane_change_poc_overlay"] = {
        "source": "phase2-crossing-first-poc-v2",
        "policy": "overlay_positive_lane_change_maneuvers_only",
        "overlaid_frames": overlaid,
        "non_lane_fields_preserved": True,
    }
    return merged, overlaid


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current-root", type=Path, required=True)
    parser.add_argument("--poc-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    recordings = poc_recordings = frames = 0
    for current_path in sorted(args.current_root.glob("*_simplified_prediction.json")):
        poc_path = args.poc_root / current_path.name
        if poc_path.is_file():
            merged, count = merge_recording(_load(current_path), _load(poc_path))
            poc_recordings += 1
        else:
            merged, count = copy.deepcopy(_load(current_path)), 0
            merged["lane_change_poc_overlay"] = {
                "source": "phase2-crossing-first-poc-v2",
                "policy": "no_matching_poc_prediction_current_prediction_preserved",
                "overlaid_frames": 0,
                "non_lane_fields_preserved": True,
            }
        (args.output_root / current_path.name).write_text(
            json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        recordings += 1
        frames += count
    print(f"Merged recordings: {recordings}")
    print(f"Recordings with matching PoC predictions: {poc_recordings}")
    print(f"Lane-change-positive frames overlaid: {frames}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
