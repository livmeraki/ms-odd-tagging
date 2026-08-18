"""Compatibility alias; implementation moved to :mod:`ms_odd_tagging.frame_inputs.bev_renderer`."""

import sys

from ms_odd_tagging.frame_inputs import bev_renderer as _implementation

sys.modules[__name__] = _implementation
