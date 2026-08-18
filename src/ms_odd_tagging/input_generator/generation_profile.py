"""Compatibility alias; implementation moved to :mod:`ms_odd_tagging.frame_inputs.generation_profile`."""

import sys

from ms_odd_tagging.frame_inputs import generation_profile as _implementation

sys.modules[__name__] = _implementation
