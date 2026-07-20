#!/usr/bin/env python3
"""Repository entry point for the ordered input-generation pipeline."""

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
SRC_ROOT = REPO_ROOT / "src"
if SRC_ROOT.is_dir():
    sys.path.insert(0, str(SRC_ROOT))

from ms_odd_tagging.pipeline import main


if __name__ == "__main__":
    raise SystemExit(main())
