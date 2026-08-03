#!/usr/bin/env python3
"""Run the isolated BEV lane-detection POC from a source checkout."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from ms_odd_tagging.bev_lane_poc.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

