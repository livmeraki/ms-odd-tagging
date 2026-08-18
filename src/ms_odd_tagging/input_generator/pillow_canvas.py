"""Compatibility alias; implementation moved to :mod:`ms_odd_tagging.frame_inputs.pillow_canvas`."""

import sys

from ms_odd_tagging.frame_inputs import pillow_canvas as _implementation

sys.modules[__name__] = _implementation
