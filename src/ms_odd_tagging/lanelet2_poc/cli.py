"""Run the optional Lanelet2 LCS ego/adjacent-lane proof of concept."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ms_odd_tagging.common.config import CANONICAL

from .config import load_config
from .lanelet_backend import available
from .runner import jsonl_logger, run_recording
from .visualization import render_html


def _frame_indices(values: list[str]) -> set[int] | None:
    if not values:
        return None
    output: set[int] = set()
    for value in values:
        if ":" in value:
            start, stop = value.split(":", 1)
            output.update(range(int(start), int(stop)))
        else:
            output.add(int(value))
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recordings", nargs="*", help="Recording IDs; omit for all canonical ODLD inputs")
    parser.add_argument(
        "--enable-lanelet2-poc",
        action="store_true",
        help="Required feature flag. Without it the command performs no work.",
    )
    parser.add_argument(
        "--allow-geometric-only",
        action="store_true",
        help="Run diagnostic pairing/matching when Lanelet2 bindings are unavailable.",
    )
    parser.add_argument("--canonical-dir", type=Path, default=CANONICAL)
    parser.add_argument("--output-root", type=Path, default=Path("outputs/lanelet2_poc"))
    parser.add_argument("--config", type=Path, default=Path("configs/lanelet2_poc.json"))
    parser.add_argument(
        "--frame",
        action="append",
        default=[],
        metavar="INDEX_OR_START:STOP",
        help="Limit frames; repeatable. Example: --frame 10 or --frame 10:20.",
    )
    parser.add_argument("--visualize", action="store_true")
    args = parser.parse_args(argv)
    if not args.enable_lanelet2_poc:
        print("Lanelet2 POC disabled; pass --enable-lanelet2-poc to run it.")
        return 0
    config = load_config(
        args.config if args.config.is_file() else None,
        {
            "feature_enabled": True,
            "require_lanelet2": not args.allow_geometric_only,
        },
    )
    if config["require_lanelet2"] and not available():
        parser.error(
            "Lanelet2 Python bindings are not installed. See docs/lanelet2_poc.md "
            "or pass --allow-geometric-only for non-routing diagnostics."
        )
    if args.recordings:
        inputs = [
            args.canonical_dir / f"{recording}_canonical_odld_frames.json"
            for recording in args.recordings
        ]
    else:
        inputs = sorted(args.canonical_dir.glob("*_canonical_odld_frames.json"))
    if not inputs:
        parser.error(f"no canonical ODLD recordings found in {args.canonical_dir}")
    selected = _frame_indices(args.frame)
    for source_path in inputs:
        if not source_path.is_file():
            parser.error(f"missing canonical recording: {source_path}")
        recording = json.loads(source_path.read_text(encoding="utf-8"))
        recording_id = str(recording.get("recording_id") or source_path.stem)
        log_path = args.output_root / "logs" / f"{recording_id}.jsonl"
        if log_path.exists():
            log_path.unlink()
        result = run_recording(
            recording, config, frame_indices=selected, log=jsonl_logger(log_path)
        )
        output = args.output_root / "results" / f"{recording_id}_lanelet2_poc.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
        print(f"Wrote {output}")
        print(f"Wrote {log_path}")
        if args.visualize:
            html = args.output_root / "visualization" / f"{recording_id}_lanelet2_poc.html"
            render_html(result, html)
            print(f"Wrote {html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
