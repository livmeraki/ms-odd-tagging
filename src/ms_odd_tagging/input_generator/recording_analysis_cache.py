"""Compatibility alias; implementation moved to :mod:`ms_odd_tagging.frame_inputs.recording_analysis_cache`."""

import sys

from ms_odd_tagging.frame_inputs import recording_analysis_cache as _implementation

sys.modules[__name__] = _implementation
