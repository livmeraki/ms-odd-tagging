"""Public entrypoint for canonical OD+LD+trajectory recording generation.

The supported canonical path always combines OD annotations, recording-level LD
map geometry, and ego trajectory into one canonical representation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from ms_odd_tagging.common.config import CANONICAL, DATA_RAW

from . import odld as canonical_odld


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build canonical OD+LD+trajectory recordings."
    )
    parser.add_argument("--source-root", type=Path, default=DATA_RAW)
    parser.add_argument("--output-root", type=Path, default=CANONICAL)
    parser.add_argument("--ld-radius-m", type=float, default=100.0)
    parser.add_argument("--include-clipped-ld-geometry", action="store_true")
    parser.add_argument("recordings", nargs="*")
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
        "--source-root",
        str(args.source_root),
        "--output-root",
        str(args.output_root),
        "--ld-radius-m",
        str(args.ld_radius_m),
    ]
    if args.include_clipped_ld_geometry:
        forwarded.append("--include-clipped-ld-geometry")
    forwarded.extend(args.recordings)
    return _forward_main(canonical_odld.main, forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
