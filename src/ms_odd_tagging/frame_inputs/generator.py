#!/usr/bin/env python3
"""Current frame-input generator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import _generator as _impl
from ._generator import *  # noqa: F401,F403
from .bev_renderer import render_frame_bev


def render_bev_png(
    recording: dict[str, Any],
    frame: dict[str, Any],
    output_path: Path,
    extent: tuple[float, float, float, float],
    size: tuple[int, int],
    *,
    lane_context: dict[str, Any] | None = None,
    proximity_radius_m: float = 30.0,
    crossing_arc: tuple[float, float, float] | None = None,
    debug_context: dict[str, Any] | None = None,
) -> None:
    render_frame_bev(
        style="explorer_aligned",
        recording=recording,
        frame=frame,
        output_path=output_path,
        extent=extent,
        size=size,
        lane_context=lane_context,
        proximity_radius_m=proximity_radius_m,
        crossing_arc=crossing_arc,
        debug_context=debug_context,
    )


def _sync_impl() -> None:
    _impl.load_config = globals()["load_config"]
    _impl.detect_recording_events = globals()["detect_recording_events"]
    _impl.render_revised_bev_png = globals()["render_bev_png"]


def build_recording(*args: Any, **kwargs: Any):
    _sync_impl()
    return _impl.build_recording(*args, **kwargs)


def main() -> int:
    _sync_impl()
    return _impl.main()


if __name__ == "__main__":
    raise SystemExit(main())
