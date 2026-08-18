"""Compatibility alias; implementation moved to :mod:`ms_odd_tagging.frame_inputs._standard_impl`."""

import sys

from ms_odd_tagging.frame_inputs import _standard_impl as _implementation

sys.modules[__name__] = _implementation
