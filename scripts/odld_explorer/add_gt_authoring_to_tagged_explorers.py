#!/usr/bin/env python3
"""Duplicate current tagged ODLD explorers with synchronized frame GT authoring."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from add_gt_comparison_to_tagged_explorers import inject_authoring
from generate_odld_dataset_explorers_w_scenario_tag import (
    INDEX_ROW_KEYS,
    index_html as odld_index_html,
    row_from_explorer,
    row_has_valid_manifest_metadata,
)
from ms_odd_tagging.common.config import (
    DATA_GT,
    FRAME_INPUTS_REVISED,
    ODLD_GT_AUTHORING_EXPLORERS,
    ODLD_SCENARIO_EXPLORERS,
)
from ms_odd_tagging.gt_comparison.authoring import build_review_payload


DEFAULT_SOURCE_DIR = ODLD_SCENARIO_EXPLORERS
DEFAULT_OUTPUT_DIR = ODLD_GT_AUTHORING_EXPLORERS


def recording_from_source(path: Path) -> str:
    for suffix in (
        "_animated_odld_explorer_w_gt_authoring.html",
        "_following_lane_explorer.html",
        "_animated_odld_explorer.html",
    ):
        if path.name.endswith(suffix):
            return path.name.removesuffix(suffix)
    raise ValueError(f"Unexpected tagged explorer name: {path.name}")


def source_manifest_rows(source_dir: Path) -> dict[str, dict]:
    manifest_path = source_dir / "manifest.json"
    if not manifest_path.is_file():
        return {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    rows = {}
    for row in manifest.get("recordings", []):
        if not row_has_valid_manifest_metadata(row):
            continue
        source_file = source_dir / row["file"]
        if source_file.is_file():
            rows[row["recording"]] = row
    return rows


def index_row_for_authoring(
    source: Path,
    output_name: str,
    source_rows: dict[str, dict],
) -> dict:
    recording = recording_from_source(source)
    source_row = source_rows.get(recording)
    if source_row is None:
        source_row = row_from_explorer(source)
    row = {key: source_row[key] for key in INDEX_ROW_KEYS}
    row["file"] = output_name
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--frame-input-root",
        type=Path,
        default=FRAME_INPUTS_REVISED,
    )
    parser.add_argument("--gt-dir", type=Path, default=DATA_GT)
    parser.add_argument(
        "--regenerate-existing",
        action="store_true",
        help="Replace an existing GT-authoring duplicate.",
    )
    parser.add_argument("recordings", nargs="*")
    args = parser.parse_args()

    requested = set(args.recordings)
    all_source_paths = sorted(args.source_dir.glob("*_following_lane_explorer.html"))
    if not all_source_paths:
        all_source_paths = sorted(
            args.source_dir.glob("*_animated_odld_explorer.html")
        )
    source_paths = all_source_paths
    if requested:
        source_paths = [
            path
            for path in all_source_paths
            if recording_from_source(path) in requested
        ]
    if not source_paths:
        parser.error(f"no tagged explorers found under {args.source_dir}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    source_rows = source_manifest_rows(args.source_dir)
    records_by_recording = {}
    for source in source_paths:
        recording = recording_from_source(source)
        gt_path = args.gt_dir / f"{recording}_frame_gt.json"
        payload = build_review_payload(
            args.frame_input_root,
            recording,
            gt_path if gt_path.is_file() else None,
        )
        output_name = f"{recording}_animated_odld_explorer_w_gt_authoring.html"
        output = args.output_dir / output_name
        if output.is_file() and not args.regenerate_existing:
            print(f"Skipped existing {output}")
        else:
            output.write_text(
                inject_authoring(
                    source.read_text(encoding="utf-8"),
                    recording,
                    payload,
                    args.source_dir,
                ),
                encoding="utf-8",
            )
            print(f"Wrote {output}")
        row = index_row_for_authoring(source, output_name, source_rows)
        row["reviewFrames"] = len(payload["review_frames"])
        records_by_recording[recording] = row

    for source in all_source_paths:
        recording = recording_from_source(source)
        if recording in records_by_recording:
            continue
        output_name = f"{recording}_animated_odld_explorer_w_gt_authoring.html"
        if not (args.output_dir / output_name).is_file():
            continue
        row = index_row_for_authoring(source, output_name, source_rows)
        gt_path = args.gt_dir / f"{recording}_frame_gt.json"
        payload = build_review_payload(
            args.frame_input_root,
            recording,
            gt_path if gt_path.is_file() else None,
        )
        row["reviewFrames"] = len(payload["review_frames"])
        records_by_recording[recording] = row

    for output in sorted(
        args.output_dir.glob("*_animated_odld_explorer_w_gt_authoring.html")
    ):
        recording = recording_from_source(output)
        if recording in records_by_recording:
            continue
        row = row_from_explorer(output)
        gt_path = args.gt_dir / f"{recording}_frame_gt.json"
        payload = build_review_payload(
            args.frame_input_root,
            recording,
            gt_path if gt_path.is_file() else None,
        )
        row["reviewFrames"] = len(payload["review_frames"])
        records_by_recording[recording] = row

    records = [
        records_by_recording[recording]
        for recording in sorted(records_by_recording)
    ]

    index = args.output_dir / "index.html"
    index.write_text(odld_index_html(records), encoding="utf-8")
    manifest = {
        "schema_version": "tagged-scenario-gt-authoring-explorers-v1",
        "source_dir": str(args.source_dir),
        "frame_input_root": str(args.frame_input_root),
        "gt_dir": str(args.gt_dir),
        "recordings": [
            {key: row[key] for key in INDEX_ROW_KEYS} | {"reviewFrames": row["reviewFrames"]}
            for row in records
        ],
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
