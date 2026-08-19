"""Canonical OD+LD recording construction.

This is the public package boundary. Compatibility implementations still live
under :mod:`ms_odd_tagging.input_generator` while migration is completed.
"""

from __future__ import annotations

from typing import Any

__all__ = ["main", "parse_args"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from . import builder

        return getattr(builder, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
