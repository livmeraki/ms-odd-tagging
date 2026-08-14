"""Public dispatcher for canonical recording generation.

The OD-only canonicalizer remains the shared base implementation. The OD+LD
canonicalizer extends the same OD/trajectory semantics with a recording-level LD
feature store and per-frame spatial references. This module provides one public
entrypoint without forcing those implementations into one large file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from ms_odd_tagging.common.config import CANONICAL, DATA_RAW

from . import canonical, canonical_odld

CANONICAL_MODES = ("od", "odld")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build canonical OD/trajectory or OD+LD/trajectory recordings."
    )
    parser.add_argument("--mode", choices=CANONICAL_MODES, default="odld")
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
    ]
    if args.mode == "odld":
        forwarded.extend(["--ld-radius-m", str(args.ld_radius_m)])
        if args.include_clipped_ld_geometry:
            forwarded.append("--include-clipped-ld-geometry")
        forwarded.extend(args.recordings)
        return _forward_main(canonical_odld.main, forwarded)

    # Preserve the OD-only module's historical default recording when none is
    # supplied explicitly.
    forwarded.extend(args.recordings or canonical.DEFAULT_RECORDINGS)
    return _forward_main(canonical.main, forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
