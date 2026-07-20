#!/usr/bin/env python3
"""Validate refined model-input JSON folders produced from motional windows."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


EXPECTED_SCHEMA = "od-motional-model-input-v2"
REQUIRED_REFINED_KEYS = {
    "schema_version",
    "recording_id",
    "source_window_id",
    "source_window_file",
    "time_window",
    "bev_keyframes",
    "taxonomy",
    "ego_summary",
    "ego_series_sampled",
    "per_frame_counts",
    "relevant_objects",
    "data_quality",
    "data_notes",
}
REQUIRED_COUNT_KEYS = {
    "frame_index",
    "dynamic_object_count",
    "static_visible_object_count",
    "total_object_count",
    "classes_dynamic",
    "classes_static",
    "classes_total",
    "lead_object_id",
    "nearby_pedestrian_count_30m",
    "nearby_motorcycle_count_30m",
}


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def find_refined_files(model_input_dir: Path, recording_id: str | None) -> list[Path]:
    search_root = model_input_dir / recording_id if recording_id else model_input_dir
    if not search_root.exists():
        raise FileNotFoundError(f"Model input path does not exist: {search_root}")
    files = sorted(search_root.rglob("refined.json"))
    if not files:
        raise FileNotFoundError(f"No refined.json files found under {search_root}")
    return files


def fail(errors: list[str], path: Path, message: str) -> None:
    errors.append(f"{path}: {message}")


def validate_keyframes(path: Path, refined: dict, errors: list[str]) -> None:
    keyframes = refined.get("bev_keyframes")
    if not isinstance(keyframes, dict):
        fail(errors, path, "bev_keyframes must be an object")
        return
    for label in ("start", "middle", "end"):
        info = keyframes.get(label)
        if not isinstance(info, dict):
            fail(errors, path, f"bev_keyframes.{label} is missing or invalid")
            continue
        image_path = path.parent / str(info.get("path", ""))
        if info.get("format") != "png":
            fail(errors, path, f"bev_keyframes.{label}.format must be png")
        if not isinstance(info.get("frame_index"), int):
            fail(errors, path, f"bev_keyframes.{label}.frame_index must be an int")
        if not image_path.exists():
            fail(errors, path, f"BEV image missing: {image_path}")


def validate_per_frame_counts(path: Path, refined: dict, errors: list[str]) -> None:
    counts = refined.get("per_frame_counts")
    if not isinstance(counts, list) or not counts:
        fail(errors, path, "per_frame_counts must be a non-empty list")
        return
    for index, row in enumerate(counts):
        if not isinstance(row, dict):
            fail(errors, path, f"per_frame_counts[{index}] must be an object")
            continue
        missing = REQUIRED_COUNT_KEYS - set(row)
        if missing:
            fail(errors, path, f"per_frame_counts[{index}] missing {sorted(missing)}")
        dynamic_count = row.get("dynamic_object_count")
        static_count = row.get("static_visible_object_count")
        total_count = row.get("total_object_count")
        if all(isinstance(value, int) for value in (dynamic_count, static_count, total_count)):
            if dynamic_count + static_count != total_count:
                fail(
                    errors,
                    path,
                    f"per_frame_counts[{index}] dynamic + static != total",
                )
        for key in ("nearby_pedestrian_count_30m", "nearby_motorcycle_count_30m"):
            value = row.get(key)
            if value is not None and not isinstance(value, int):
                fail(errors, path, f"per_frame_counts[{index}].{key} must be int or null")


def validate_against_window_file(
    refined_files: list[Path],
    motional_window_file: Path | None,
    errors: list[str],
) -> None:
    if motional_window_file is None:
        return
    if not motional_window_file.exists():
        errors.append(f"{motional_window_file}: motional window file does not exist")
        return
    source = load_json(motional_window_file)
    windows = {window["window_id"]: window for window in source.get("windows", [])}
    for path in refined_files:
        refined = load_json(path)
        window_id = refined.get("source_window_id")
        source_file = refined.get("source_window_file")
        if window_id not in windows:
            fail(errors, path, f"source_window_id not found in motional window file: {window_id}")
            continue
        window = windows[window_id]
        time_window = refined.get("time_window", {})
        for key in ("start_frame", "end_frame"):
            if time_window.get(key) != window.get(key):
                fail(errors, path, f"time_window.{key} does not match source window")
        if source_file and "\\" in source_file:
            fail(errors, path, "source_window_file contains platform-specific backslashes")


def validate_refined_file(path: Path) -> list[str]:
    errors: list[str] = []
    refined = load_json(path)
    if not isinstance(refined, dict):
        return [f"{path}: refined.json must contain a JSON object"]
    missing = REQUIRED_REFINED_KEYS - set(refined)
    if missing:
        fail(errors, path, f"missing top-level keys {sorted(missing)}")
    if refined.get("schema_version") != EXPECTED_SCHEMA:
        fail(errors, path, f"schema_version must be {EXPECTED_SCHEMA!r}")
    if not isinstance(refined.get("source_window_file"), str):
        fail(errors, path, "source_window_file must be a string")
    elif "\\" in refined["source_window_file"]:
        fail(errors, path, "source_window_file must use POSIX-style separators")
    validate_keyframes(path, refined, errors)
    validate_per_frame_counts(path, refined, errors)
    data_quality = refined.get("data_quality")
    if not isinstance(data_quality, dict):
        fail(errors, path, "data_quality must be an object")
    else:
        for key in (
            "missing_object_frames",
            "frames_with_static_snapshot_spike",
            "nearby_count_source_available",
            "warnings",
        ):
            if key not in data_quality:
                fail(errors, path, f"data_quality.{key} is missing")
    return errors


def validate_refined(
    path: Path,
    motional_by_window: dict[str, dict] | None = None,
) -> list[str]:
    errors = validate_refined_file(path)
    if motional_by_window is None:
        return errors

    refined = load_json(path)
    window_id = refined.get("source_window_id")
    if window_id not in motional_by_window:
        fail(errors, path, f"source_window_id not found in motional windows: {window_id}")
        return errors

    window = motional_by_window[window_id]
    time_window = refined.get("time_window", {})
    for key in ("start_frame", "end_frame"):
        if time_window.get(key) != window.get(key):
            fail(errors, path, f"time_window.{key} does not match source window")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate refined.json model inputs and BEV keyframe files."
    )
    parser.add_argument("--model-input-dir", type=Path, required=True)
    parser.add_argument(
        "recording",
        nargs="?",
        help="Optional recording id subfolder to validate.",
    )
    parser.add_argument(
        "--motional-window-file",
        type=Path,
        default=None,
        help="Optional source motional-window JSON for cross-checking window ids/frames.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        refined_files = find_refined_files(args.model_input_dir, args.recording)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    errors: list[str] = []
    for path in refined_files:
        try:
            errors.extend(validate_refined_file(path))
        except Exception as exc:
            errors.append(f"{path}: failed to parse/validate: {exc}")
    validate_against_window_file(refined_files, args.motional_window_file, errors)

    if errors:
        print(f"Validation failed: {len(errors)} issue(s)")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"Validation passed: {len(refined_files)} refined model input file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
