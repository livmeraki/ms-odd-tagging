"""Final role pass using piece-local track geometry.

The existing integrated detector still owns reconstruction, inferred affiliation,
connectors, and topology-supported stitching. This wrapper only replaces the
last static lane-order/role pass so static inferred pieces can be recognized as
local ego/left/right geometry.
"""
from __future__ import annotations

from typing import Any

from .detector_static_order_integrated import (
    _recompute_frames,
    run_lane_debug_v2 as run_integrated,
)
from .static_lane_order_piece_local import (
    build_constructed_lane_network,
    build_static_lane_order,
)


def run_lane_debug_v2(recording: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = dict(config or {})
    result = run_integrated(recording, cfg)
    tracks = result.get("continuous_lane_tracks", [])
    settings = {**(result.get("debug_config") or {}), **cfg}
    lane_order = build_static_lane_order(
        tracks,
        sample_spacing_m=float(settings.get("lane_order_sample_spacing_m", 2.0)),
        maximum_heading_difference_deg=float(settings.get("lane_order_maximum_heading_difference_deg", 20.0)),
        minimum_lateral_m=float(settings.get("lane_order_minimum_lateral_m", 1.5)),
        maximum_lateral_m=float(settings.get("lane_order_maximum_lateral_m", 8.0)),
        maximum_longitudinal_m=float(settings.get("lane_order_maximum_longitudinal_m", 8.0)),
    )
    result["static_lane_order_topology"] = lane_order
    result["constructed_lane_network"] = build_constructed_lane_network(tracks, lane_order)
    _recompute_frames(recording, result, tracks, lane_order, settings)
    result["final_lane_role_policy"] = {
        "method": "static_cross_section_piece_local_lane_order",
        "candidate_projection": "nearest_valid_track_piece_centerline",
        "static_inferred_corridor_participates": True,
    }
    result["schema_version"] = "lane-debug-v2-piece-local-final-role-v1"
    return result
