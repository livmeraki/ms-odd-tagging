#!/usr/bin/env python
"""Render side attempt-1-style BEVs for saved Qwen VLM candidate bundles."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ms_odd_tagging.qwen_vlm_poc.attempt1_style_bev import render_candidate_bevs_attempt1_style
from ms_odd_tagging.qwen_vlm_poc.config import load_config
from ms_odd_tagging.qwen_vlm_poc.evidence import load_candidate_bundle, serialize_candidate_bundle
from ms_odd_tagging.qwen_vlm_poc.loader import canonical_path, load_recording


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render experimental attempt-1-style BEVs without changing the main VLM POC renderer."
    )
    parser.add_argument("--candidate-bundle", action="append", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument(
        "--write-updated-bundles",
        action="store_true",
        help="Write candidate bundle copies whose bev_paths point at the side-rendered images.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(
        args.config,
        overrides={
            "input_dir": args.input_dir,
            "output_root": args.output_root,
        },
    )
    args.output_root.mkdir(parents=True, exist_ok=True)
    written = []
    for bundle_path in args.candidate_bundle:
        candidate = load_candidate_bundle(bundle_path)
        recording = load_recording(canonical_path(config.input_dir, candidate.recording_id))
        rendered = render_candidate_bevs_attempt1_style(recording, candidate, args.output_root, config)
        if args.write_updated_bundles:
            out_path = (
                args.output_root
                / "candidates_attempt1_style"
                / rendered.scenario
                / rendered.recording_id
                / f"{rendered.candidate_id}.json"
            )
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                json.dumps(serialize_candidate_bundle(rendered), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            written.append(str(out_path))
        else:
            written.extend(rendered.bev_paths)
    print(json.dumps({"written": written}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
