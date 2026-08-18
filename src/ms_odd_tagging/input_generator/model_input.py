"""Compatibility alias; implementation moved to :mod:`ms_odd_tagging.frame_inputs.model_input`."""

import sys

from ms_odd_tagging.frame_inputs import model_input as _implementation

sys.modules[__name__] = _implementation
