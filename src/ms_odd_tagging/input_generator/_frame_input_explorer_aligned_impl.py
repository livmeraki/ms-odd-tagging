"""Compatibility alias; implementation moved to :mod:`ms_odd_tagging.frame_inputs._explorer_aligned_impl`."""

import sys

from ms_odd_tagging.frame_inputs import _explorer_aligned_impl as _implementation

sys.modules[__name__] = _implementation
