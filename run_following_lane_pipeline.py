#!/usr/bin/env python3
"""Run the isolated frame-level following-lane workflow."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from ms_odd_tagging.scenarios.following_lane.pipeline import main

if __name__ == "__main__":
    raise SystemExit(main())
