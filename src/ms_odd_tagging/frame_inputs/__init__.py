"""Per-frame model-input and BEV generation public boundary."""

from __future__ import annotations

from typing import Any

__all__ = ["main", "parse_args"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from . import builder

        return getattr(builder, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
