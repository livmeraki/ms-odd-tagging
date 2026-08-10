"""Second-pass integration for lane-debug-v2.

Runs the existing static-order detector, then:
1. merges fragmented lanes supported by consecutive static-neighbor topology;
2. builds recording-level static inferred lanes from overlapping ego-corridor boxes;
3. connects observed tracks before/after a supported inferred lane;
4. fills any remaining endpoint gaps with curvature-aware connector polygons;
5. recomputes ego/left/right roles against the final static network.
"""
from __future__ import annotations

from typing import Any

from .detector import _lane_output, _nearest_member
from .detector_static_order import run_lane_debug_v2 as run_static_order
from .neighbor_continuity_stitch import stitch_topology_supported_neighbors
from .static_inferred_connectors import fill_static_inferred_endpoint_gaps
from .static_inferred_lane import build_static_inferred_lanes, integrate_static_inferred_lanes
from .static_lane_order import build_constructed_lane_network, build_static_lane_order, classify_lane_roles
from .strict_track_assignment import assign_point_to_track_strict


def _track_alias_map(tracks: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for track in tracks:
        final_id = str(track.get("track_id"))
        out[final_id] = final_id
        for old in track.get("merged_from_track_ids") or []:
            out[str(old)] = final_id
    return out


def _recompute_frames(
    recording: dict[str, Any], result: dict[str, Any], tracks: list[dict[str, Any]],
    lane_order: dict[str, Any], config: dict[str, Any]
) -> None:
    lane_geometry = result.get("lane_geometry", [])
    lane_by_id = {str(l.get("lane_id")): l for l in lane_geometry}
    track_by_id = {str(t.get("track_id")): t for t in tracks}
    member_to_track = {
        str(lane_id): str(track.get("track_id"))
        for track in tracks for lane_id in track.get("member_lane_ids", [])
    }
    source_by_frame = {f.get("frame_index"): f for f in recording.get("frames", [])}
    previous_track_id = None
    max_heading = float(config.get("continuous_track_maximum_heading_difference_deg", 60.0))
    outside_tol = float(config.get("continuous_track_outside_tolerance_m", 1.0))

    for frame in result.get("frames", []):
        src = source_by_frame.get(frame.get("frame_index"), {})
        ego = src.get("ego") or {}
        p = ego.get("position_lcs_m") or []
        heading = ego.get("heading_lcs_rad")
        if len(p) < 2 or heading is None:
            continue
        point = (float(p[0]), float(p[1]))
        assignment = assign_point_to_track_strict(
            point, float(heading), tracks,
            previous_track_id=previous_track_id,
            maximum_heading_difference_deg=max_heading,
            outside_tolerance_m=outside_tol,
        )
        frame["continuous_ego_track"] = assignment
        track_id = str(assignment.get("track_id")) if assignment.get("track_id") else None
        if track_id:
            previous_track_id = track_id
            track = track_by_id.get(track_id)
            physical = assignment.get("matched_lane_id") or _nearest_member(track, point, lane_by_id)
            matched_kind = assignment.get("matched_piece_kind")
            frame["ego_lane"] = {
                "lane_id": physical,
                "logical_lane_id": track_id,
                "continuous_track_id": track_id,
                "continuous_track_member_lane_ids": assignment.get("member_lane_ids", []),
                "method": assignment.get("method"),
                "confidence": assignment.get("confidence"),
                "inside_polygon": assignment.get("inside_polygon"),
                "polygon_distance_m": assignment.get("polygon_distance_m"),
                "source": "final_integrated_static_lane_network",
                "track_source": None if not track else track.get("source"),
                "matched_piece_kind": matched_kind,
                "inferred": matched_kind in {
                    "ego_supported_inferred_route",
                    "static_inferred_corridor",
                    "static_inferred_connector",
                },
            }
            roles = classify_lane_roles(point, track_id, tracks, lane_order)
            frame["lane_roles"] = roles
            frame["left_lane"] = _lane_output(roles.get("left") or {}, point, track_by_id, lane_by_id)
            frame["right_lane"] = _lane_output(roles.get("right") or {}, point, track_by_id, lane_by_id)

        for obj in frame.get("objects", []):
            lane_id = obj.get("lane_id")
            if lane_id is not None and str(lane_id) in member_to_track:
                obj["logical_lane_id"] = member_to_track[str(lane_id)]
                obj["continuous_track_id"] = member_to_track[str(lane_id)]

    result["continuous_track_member_map"] = member_to_track


def run_lane_debug_v2(recording: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = dict(config or {})
    result = run_static_order(recording, cfg)
    tracks = result.get("continuous_lane_tracks", [])
    provisional_order = result.get("static_lane_order_topology", {})

    topology_tracks, topology_debug = stitch_topology_supported_neighbors(
        tracks,
        provisional_order,
        maximum_gap_m=float(cfg.get("topology_supported_stitch_maximum_gap_m", 15.0)),
        maximum_reference_station_gap_m=float(cfg.get("topology_supported_stitch_maximum_reference_station_gap_m", 16.0)),
    )

    alias = _track_alias_map(topology_tracks)
    static_inferred_lanes = build_static_inferred_lanes(result.get("inferred_ego_routes", []))
    integrated_tracks, static_inferred_debug = integrate_static_inferred_lanes(
        topology_tracks,
        static_inferred_lanes,
        alias,
        maximum_endpoint_distance_m=float(cfg.get("static_inferred_lane_maximum_endpoint_distance_m", 20.0)),
        maximum_heading_difference_deg=float(cfg.get("static_inferred_lane_maximum_heading_difference_deg", 40.0)),
    )
    final_tracks, connector_debug = fill_static_inferred_endpoint_gaps(
        integrated_tracks,
        maximum_gap_m=float(cfg.get("static_inferred_connector_maximum_gap_m", 20.0)),
    )

    lane_order = build_static_lane_order(
        final_tracks,
        sample_spacing_m=float(cfg.get("lane_order_sample_spacing_m", 2.0)),
        maximum_heading_difference_deg=float(cfg.get("lane_order_maximum_heading_difference_deg", 20.0)),
        minimum_lateral_m=float(cfg.get("lane_order_minimum_lateral_m", 1.5)),
        maximum_lateral_m=float(cfg.get("lane_order_maximum_lateral_m", 8.0)),
        maximum_longitudinal_m=float(cfg.get("lane_order_maximum_longitudinal_m", 8.0)),
    )
    result["continuous_lane_tracks"] = final_tracks
    result["topology_supported_stitch_debug"] = topology_debug
    result["topology_supported_stitch_count"] = sum(1 for x in topology_debug if x.get("accepted"))
    result["static_inferred_lanes"] = static_inferred_lanes
    result["static_inferred_lane_debug"] = static_inferred_debug
    result["static_inferred_connector_debug"] = connector_debug
    result["static_inferred_connector_count"] = sum(1 for x in connector_debug if x.get("status") == "connector_created")
    result["static_inferred_lane_count"] = len(static_inferred_lanes)
    result["static_inferred_lane_merge_count"] = sum(
        1 for x in static_inferred_debug if x.get("accepted") and x.get("action") == "merge_front_back_tracks"
    )
    result["static_lane_order_topology"] = lane_order
    result["constructed_lane_network"] = build_constructed_lane_network(final_tracks, lane_order)
    _recompute_frames(recording, result, final_tracks, lane_order, {**(result.get("debug_config") or {}), **cfg})
    result["schema_version"] = "lane-debug-v2-static-inferred-lane-network-v3-connectors"
    return result
