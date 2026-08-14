#!/usr/bin/env python3
"""Canonical per-frame input entrypoint.

This module preserves the existing public API while routing standard BEV rendering
through :mod:`bev_renderer`. The previous implementation is retained privately
for rollback during the cleanup branch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import _frame_input_standard_impl as _impl
from ._frame_input_standard_impl import *  # noqa: F401,F403
from .bev_renderer import render_frame_bev


def render_bev_model_png(
    recording: dict[str, Any],
    frame_context: dict[str, Any],
    frame_idx: int,
    label: str,
    output_path: Path,
    extent: tuple[float, float, float, float],
    size: tuple[int, int],
    ld_filters: dict[str, set[str]] | None = None,
) -> None:
    """Compatibility adapter for the old standard-renderer call signature."""
    frames = {
        int(frame["frame_index"]): frame for frame in frame_context.get("frames", [])
    }
    frame = frames[int(frame_idx)]
    render_frame_bev(
        style="standard",
        recording=recording,
        frame=frame,
        output_path=output_path,
        extent=extent,
        size=size,
        ld_filters=ld_filters,
    )


def _sync_impl() -> None:
    """Propagate public monkeypatch points and the canonical renderer adapter."""
    _impl.load_config = globals()["load_config"]
    _impl.detect_recording_events = globals()["detect_recording_events"]
    _impl.render_bev_model_png = globals()["render_bev_model_png"]


def build_recording(*args: Any, **kwargs: Any):
    _sync_impl()
    return _impl.build_recording(*args, **kwargs)


def main() -> int:
    _sync_impl()
    return _impl.main()


if __name__ == "__main__":
    raise SystemExit(main())
