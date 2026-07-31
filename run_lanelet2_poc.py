#!/usr/bin/env python3
"""Run the isolated Lanelet2 LCS POC from a source checkout."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from ms_odd_tagging.lanelet2_poc.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
