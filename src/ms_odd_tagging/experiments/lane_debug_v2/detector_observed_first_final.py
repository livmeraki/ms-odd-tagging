"""Final lane-debug wrapper with observed-first physical-track construction."""
from __future__ import annotations

from typing import Any

from . import detector_static_order as static_order_module
from .continuous_tracks_observed_first import build_continuous_tracks as build_observed_first_tracks
from .detector_static_order_integrated_piece_local import run_lane_debug_v2 as run_piece_local_final


def run_lane_debug_v2(recording: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the existing final pipeline with corrected upstream track construction."""
    previous_builder = static_order_module.build_continuous_tracks
    static_order_module.build_continuous_tracks = build_observed_first_tracks
    try:
        result = run_piece_local_final(recording, config)
    finally:
        static_order_module.build_continuous_tracks = previous_builder

    result["observed_first_track_construction_policy"] = {
        "enabled": True,
        "method": "observed_exact_touch_before_curvature_inference",
        "observed_touch_center_gap_max_m": 0.25,
        "observed_touch_boundary_gap_max_m": 0.25,
        "observed_touch_heading_difference_max_deg": 8.0,
        "observed_touch_local_width_difference_max_m": 0.5,
        "observed_touch_priority_over_inferred_gap": True,
        "reject_inferred_gap_occupied_by_observed_fragment": True,
        "fork_policy": "require_unambiguous_boundary_continuity",
    }
    result["schema_version"] = "lane-debug-v2-observed-first-track-construction-v1"
    return result
