#!/usr/bin/env python3
"""Duplicate current tagged ODLD explorers with synchronized frame GT authoring."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from urllib.parse import quote

from add_gt_comparison_to_tagged_explorers import inject_authoring
from ms_odd_tagging.common.config import (
    DATA_GT,
    FRAME_INPUTS_REVISED,
    OUTPUT_ROOT,
)
from ms_odd_tagging.gt_comparison.authoring import build_review_payload


DEFAULT_SOURCE_DIR = (
    OUTPUT_ROOT
    / "scenarios"
    / "following_lane_phase2_all_tags"
    / "04_visualization"
)
DEFAULT_OUTPUT_DIR = OUTPUT_ROOT / "07_odld_scenario_explorers_gt_authoring_all_tags"


def recording_from_source(path: Path) -> str:
    for suffix in (
        "_following_lane_explorer.html",
        "_animated_odld_explorer.html",
    ):
        if path.name.endswith(suffix):
            return path.name.removesuffix(suffix)
    raise ValueError(f"Unexpected tagged explorer name: {path.name}")


def index_html(records: list[dict]) -> str:
    links = "\n".join(
        f'<li><a href="{quote(row["file"])}">{html.escape(row["recording"])}</a>'
        f'<span>{row["review_frames"]} existing GT review frames</span></li>'
        for row in records
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tagged scenario GT authoring explorers</title>
<style>body{{font:15px system-ui,sans-serif;max-width:1000px;margin:auto;padding:24px;background:#f8fafc;color:#172033}}
h1{{font-size:23px}}p{{color:#64748b}}ul{{list-style:none;padding:0}}li{{display:flex;justify-content:space-between;gap:20px;padding:13px 4px;border-bottom:1px solid #d8deea}}
a{{font-weight:650;color:#2458c6}}span{{color:#657087}}</style></head>
<body><h1>Tagged scenario GT authoring explorers</h1>
<p>Open a recording, move to an exact frame, then review existing GT or add that frame to GT.</p>
<ul>{links}</ul></body></html>"""


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
    source_paths = sorted(args.source_dir.glob("*_following_lane_explorer.html"))
    if not source_paths:
        source_paths = sorted(
            args.source_dir.glob("*_animated_odld_explorer.html")
        )
    if requested:
        source_paths = [
            path
            for path in source_paths
            if recording_from_source(path) in requested
        ]
    if not source_paths:
        parser.error(f"no tagged explorers found under {args.source_dir}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    records = []
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
        records.append(
            {
                "recording": recording,
                "file": output_name,
                "review_frames": len(payload["review_frames"]),
            }
        )

    index = args.output_dir / "index.html"
    index.write_text(index_html(records), encoding="utf-8")
    manifest = {
        "schema_version": "tagged-scenario-gt-authoring-explorers-v1",
        "source_dir": str(args.source_dir),
        "frame_input_root": str(args.frame_input_root),
        "gt_dir": str(args.gt_dir),
        "recordings": records,
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
