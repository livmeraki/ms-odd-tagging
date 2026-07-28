#!/usr/bin/env python3
"""Validate one-JSON/one-BEV-per-frame model input folders."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


EXPECTED_SCHEMA = "odld-dynamic-frame-model-input-v1"
REQUIRED_KEYS = {
    "schema_version",
    "recording_id",
    "frame_id",
    "source_canonical_file",
    "frame_index",
    "time_since_start_s",
    "taxonomy",
    "bev",
    "ego",
    "scenario_signals",
    "object_counts",
    "objects",
    "interaction_candidates",
    "ld",
    "data_quality",
    "data_notes",
}


def find_frame_files(root: Path, recording: str | None = None) -> list[Path]:
    search_root = root / recording if recording else root
    if not search_root.exists():
        raise FileNotFoundError(f"Frame-input path does not exist: {search_root}")
    files = sorted(search_root.rglob("frame.json"))
    if not files:
        raise FileNotFoundError(f"No frame.json files found under {search_root}")
    return files


def validate_frame_file(path: Path) -> list[str]:
    errors: list[str] = []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return [f"{path}: frame.json must contain an object"]
    missing = REQUIRED_KEYS - set(payload)
    if missing:
        errors.append(f"{path}: missing top-level keys {sorted(missing)}")
    if payload.get("schema_version") != EXPECTED_SCHEMA:
        errors.append(f"{path}: schema_version must be {EXPECTED_SCHEMA!r}")
    frame_index = payload.get("frame_index")
    if not isinstance(frame_index, int):
        errors.append(f"{path}: frame_index must be an int")
    frame_id = payload.get("frame_id")
    if not isinstance(frame_id, str) or not frame_id.endswith(f"frame-{frame_index:06d}"):
        errors.append(f"{path}: frame_id must identify frame_index")
    source = payload.get("source_canonical_file")
    if not isinstance(source, str) or "\\" in source:
        errors.append(f"{path}: source_canonical_file must be a portable path")
    bev = payload.get("bev")
    if not isinstance(bev, dict):
        errors.append(f"{path}: bev must be an object")
    else:
        if bev.get("frame_index") != frame_index:
            errors.append(f"{path}: bev.frame_index must equal frame_index")
        if bev.get("format") != "png":
            errors.append(f"{path}: bev.format must be 'png'")
        image_path = path.parent / str(bev.get("path", ""))
        if not image_path.is_file():
            errors.append(f"{path}: BEV image missing: {image_path}")
    if not isinstance(payload.get("ego"), dict):
        errors.append(f"{path}: ego must be an object")
    if not isinstance(payload.get("objects"), list):
        errors.append(f"{path}: objects must be a list")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate per-frame JSON model inputs and same-frame BEV PNGs."
    )
    parser.add_argument("--frame-input-dir", type=Path, required=True)
    parser.add_argument("recording", nargs="?")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        files = find_frame_files(args.frame_input_dir, args.recording)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    errors: list[str] = []
    for path in files:
        try:
            errors.extend(validate_frame_file(path))
        except Exception as exc:
            errors.append(f"{path}: failed to parse/validate: {exc}")
    if errors:
        print(f"Validation failed: {len(errors)} issue(s)")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Validation passed: {len(files)} per-frame model input file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
