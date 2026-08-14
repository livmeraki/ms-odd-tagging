"""Public dispatcher for per-frame model-input generation.

``standard`` preserves the existing model-facing BEV. ``explorer_aligned``
preserves the centered/debug-oriented revised BEV. Both styles share the stable
renderer API in :mod:`ms_odd_tagging.input_generator.bev_renderer`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from ms_odd_tagging.common.config import CANONICAL, FRAME_INPUTS, FRAME_INPUTS_REVISED

from . import frame_input, frame_input_revised
from .bev_renderer import SUPPORTED_BEV_STYLES, normalize_bev_style


STANDARD_DEFAULT_SIZE = (1000, 900)
EXPLORER_ALIGNED_DEFAULT_SIZE = (900, 1200)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate timestamp-sampled per-frame JSON and BEV inputs."
    )
    parser.add_argument("--bev-style", default="standard")
    parser.add_argument("--input-dir", type=Path, default=CANONICAL)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--recording", action="append")
    parser.add_argument("--frame-limit", type=int)
    sampling = parser.add_mutually_exclusive_group()
    sampling.add_argument("--frames-per-second", type=float, default=1.0)
    sampling.add_argument("--all-frames", action="store_true")
    parser.add_argument("--max-objects", type=int, default=80)
    # Leave size unresolved until the BEV style is normalized so each style can
    # keep an appropriate default aspect ratio. Explicit user values still win.
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--left-m", type=float, default=45.0)
    parser.add_argument("--right-m", type=float, default=45.0)
    parser.add_argument("--back-m", type=float, default=25.0)
    parser.add_argument("--forward-m", type=float, default=95.0)
    parser.add_argument("--ld-line-patterns", default="solid,dashed")
    parser.add_argument("--ld-roadmark-classes", default="crosswalk,stopline")
    parser.add_argument("--ld-boundary-attributes", default="drivable,non_drivable")
    parser.add_argument("--profile-generation", action="store_true")
    args = parser.parse_args(argv)
    try:
        args.bev_style = normalize_bev_style(args.bev_style)
    except ValueError as exc:
        parser.error(str(exc))

    default_width, default_height = (
        EXPLORER_ALIGNED_DEFAULT_SIZE
        if args.bev_style == "explorer_aligned"
        else STANDARD_DEFAULT_SIZE
    )
    if args.width is None:
        args.width = default_width
    if args.height is None:
        args.height = default_height
    return args


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
    output_dir = args.output_dir
    if output_dir is None:
        output_dir = (
            FRAME_INPUTS_REVISED
            if args.bev_style == "explorer_aligned"
            else FRAME_INPUTS
        )

    forwarded = [
        "--input-dir", str(args.input_dir),
        "--output-dir", str(output_dir),
        "--max-objects", str(args.max_objects),
        "--width", str(args.width),
        "--height", str(args.height),
        "--left-m", str(args.left_m),
        "--right-m", str(args.right_m),
        "--back-m", str(args.back_m),
        "--forward-m", str(args.forward_m),
    ]
    for recording in args.recording or []:
        forwarded.extend(["--recording", recording])
    if args.frame_limit is not None:
        forwarded.extend(["--frame-limit", str(args.frame_limit)])
    if args.all_frames:
        forwarded.append("--all-frames")
    else:
        forwarded.extend(["--frames-per-second", str(args.frames_per_second)])
    if args.profile_generation:
        forwarded.append("--profile-generation")

    if args.bev_style == "standard":
        forwarded.extend([
            "--ld-line-patterns", args.ld_line_patterns,
            "--ld-roadmark-classes", args.ld_roadmark_classes,
            "--ld-boundary-attributes", args.ld_boundary_attributes,
        ])
        return _forward_main(frame_input.main, forwarded)
    return _forward_main(frame_input_revised.main, forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
