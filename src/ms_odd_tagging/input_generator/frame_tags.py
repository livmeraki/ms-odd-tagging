"""Compatibility alias; implementation moved to :mod:`ms_odd_tagging.frame_inputs.frame_tags`."""

import sys

from ms_odd_tagging.frame_inputs import frame_tags as _implementation

sys.modules[__name__] = _implementation
