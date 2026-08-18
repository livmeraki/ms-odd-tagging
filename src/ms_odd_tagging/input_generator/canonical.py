"""Compatibility alias for :mod:`ms_odd_tagging.canonical.core`."""

from __future__ import annotations

import sys

from ms_odd_tagging.canonical import core as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
else:
    sys.modules[__name__] = _implementation
