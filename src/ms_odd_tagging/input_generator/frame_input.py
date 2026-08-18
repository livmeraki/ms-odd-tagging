"""Compatibility alias; implementation moved to :mod:`ms_odd_tagging.frame_inputs.standard`."""

import sys

from ms_odd_tagging.frame_inputs import standard as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
else:
    sys.modules[__name__] = _implementation
