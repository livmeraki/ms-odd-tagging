"""Compatibility alias; implementation moved to :mod:`ms_odd_tagging.frame_inputs.revised_bev`."""

import sys

from ms_odd_tagging.frame_inputs import revised_bev as _implementation

sys.modules[__name__] = _implementation
