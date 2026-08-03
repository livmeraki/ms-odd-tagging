#!/usr/bin/env python3
"""Repository wrapper for the LD topology detector."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ms_odd_tagging.ld_topology.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
