"""Canonical OD+LD recording construction.

This is the public package boundary. Compatibility implementations still live
under :mod:`ms_odd_tagging.input_generator` while migration is completed.
"""

from .builder import main, parse_args

__all__ = ["main", "parse_args"]
