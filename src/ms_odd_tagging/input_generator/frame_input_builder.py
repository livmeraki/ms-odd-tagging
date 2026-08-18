"""Compatibility alias; implementation moved to :mod:`ms_odd_tagging.frame_inputs.builder`."""

import sys

from ms_odd_tagging.frame_inputs import builder as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
else:
    sys.modules[__name__] = _implementation
