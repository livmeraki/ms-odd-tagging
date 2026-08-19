#!/usr/bin/env python3
"""Run the 2026-07-28 following-lane implementation with standalone visualization.

This comparison runner deliberately avoids injecting the legacy lane-tracker UI
into a newer ODLD explorer HTML, because those HTML marker contracts are not
compatible. It reuses the historical detector/pipeline code on this branch and
writes its own standalone following-lane debugger instead.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ms_odd_tagging.scenarios.following_lane.pipeline import run_one


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recordings", nargs="+", help="Recording IDs to run")
    parser.add_argument("--canonical-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/following_lane.json"),
    )
    args = parser.parse_args()

    config = (
        json.loads(args.config.read_text(encoding="utf-8"))
        if args.config.is_file()
        else {}
    )

    for recording in args.recordings:
        canonical_path = args.canonical_dir / f"{recording}_canonical_odld_frames.json"
        if not canonical_path.is_file():
            parser.error(f"missing canonical recording: {canonical_path}")
        for output in run_one(
            canonical_path,
            args.output_root,
            config,
            "visualization",
            None,
        ):
            print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
