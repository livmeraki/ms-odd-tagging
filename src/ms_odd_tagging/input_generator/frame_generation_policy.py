"""Compatibility alias; implementation moved to :mod:`ms_odd_tagging.frame_inputs.frame_generation_policy`."""

import sys

from ms_odd_tagging.frame_inputs import frame_generation_policy as _implementation

sys.modules[__name__] = _implementation
