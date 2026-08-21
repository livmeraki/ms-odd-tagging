"""Public entrypoint for per-frame JSON and BEV generation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from ms_odd_tagging.common.config import CANONICAL, FRAME_INPUTS

from . import generator as frame_generator


DEFAULT_SIZE = (900, 1200)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate per-frame JSON and BEV inputs."
    )
    parser.add_argument("--input-dir", type=Path, default=CANONICAL)
    parser.add_argument("--output-dir", type=Path, default=FRAME_INPUTS)
    parser.add_argument("--recording", action="append")
    parser.add_argument("--frame-limit", type=int)
    sampling = parser.add_mutually_exclusive_group()
    sampling.add_argument("--frames-per-second", type=float, default=1.0)
    sampling.add_argument("--all-frames", action="store_true")
    parser.add_argument("--max-objects", type=int, default=80)
    parser.add_argument("--width", type=int, default=DEFAULT_SIZE[0])
    parser.add_argument("--height", type=int, default=DEFAULT_SIZE[1])
    parser.add_argument("--left-m", type=float, default=45.0)
    parser.add_argument("--right-m", type=float, default=45.0)
    parser.add_argument("--back-m", type=float, default=25.0)
    parser.add_argument("--forward-m", type=float, default=95.0)
    parser.add_argument(
        "--existing-output",
        choices=("ask", "resume", "regenerate", "cancel"),
        default="ask",
        help=(
            "Existing-output policy. Default ask prompts when outputs exist; "
            "use resume/regenerate/cancel explicitly for batch runs."
        ),
    )
    parser.add_argument(
        "--refresh-analysis",
        action="store_true",
        help="Recompute recording-wide rule/lane analysis instead of using its cache.",
    )
    parser.add_argument("--profile-generation", action="store_true")
    return parser.parse_args(argv)


def _forward_main(module_main, argv: list[str]) -> int:
    previous = sys.argv
    try:
        sys.argv = [previous[0], *argv]
        result = module_main()
    finally:
        sys.argv = previous
    return 0 if result is None else int(result)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    forwarded = [
        "--input-dir", str(args.input_dir),
        "--output-dir", str(args.output_dir),
        "--max-objects", str(args.max_objects),
        "--width", str(args.width),
        "--height", str(args.height),
        "--left-m", str(args.left_m),
        "--right-m", str(args.right_m),
        "--back-m", str(args.back_m),
        "--forward-m", str(args.forward_m),
        "--existing-output", args.existing_output,
    ]
    for recording in args.recording or []:
        forwarded.extend(["--recording", recording])
    if args.frame_limit is not None:
        forwarded.extend(["--frame-limit", str(args.frame_limit)])
    if args.all_frames:
        forwarded.append("--all-frames")
    else:
        forwarded.extend(["--frames-per-second", str(args.frames_per_second)])
    if args.refresh_analysis:
        forwarded.append("--refresh-analysis")
    if args.profile_generation:
        forwarded.append("--profile-generation")
    return _forward_main(frame_generator.main, forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
