"""Final integrated lane-debug-v2 detector.

Order is intentional:
1. run the existing static-order experiment;
2. reject lanes that are both intersection-marked and curved, then rebuild tracks;
3. build recording-level static inferred lanes from overlapping ego-corridor boxes;
4. affiliate each inferred lane to longitudinal BACK/FRONT continuations only;
5. integrate/fill inferred corridors;
6. only after affiliation, run topology-supported neighbor stitching;
7. recompute static lane order and per-frame roles.
"""
from __future__ import annotations

from typing import Any

from .detector import _lane_output, _nearest_member
from .detector_static_order import (
    _apply_static_order,
    run_lane_debug_v2 as run_static_order,
)
from .lane_eligibility import exclude_curved_intersection_lanes
from .neighbor_continuity_stitch import stitch_topology_supported_neighbors
from .static_inferred_affiliation import assign_static_inferred_affiliations
from .static_inferred_connectors import fill_static_inferred_endpoint_gaps
from .static_inferred_lane import build_static_inferred_lanes, integrate_static_inferred_lanes
from .static_lane_order import build_constructed_lane_network, build_static_lane_order, classify_lane_roles
from .strict_track_assignment import assign_point_to_track_strict


def _identity_alias(tracks: list[dict[str, Any]]) -> dict[str, str]:
    return {str(t.get("track_id")): str(t.get("track_id")) for t in tracks}


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
        else:
            frame["ego_lane"] = {
                "lane_id": None,
                "logical_lane_id": None,
                "continuous_track_id": None,
                "method": assignment.get("method", "no_final_track_contains_ego"),
                "confidence": "unknown",
                "source": "final_integrated_static_lane_network",
            }
            frame["lane_roles"] = {
                "ego_track_id": None,
                "left": {"track_id": None},
                "right": {"track_id": None},
                "roles": [
                    {"track_id": str(t.get("track_id")), "role": "irrelevant"}
                    for t in tracks
                ],
                "method": "no_final_ego_track",
            }
            frame["left_lane"] = {"lane_id": None, "method": "ego_track_unknown"}
            frame["right_lane"] = {"lane_id": None, "method": "ego_track_unknown"}

        for obj in frame.get("objects", []):
            lane_id = obj.get("lane_id")
            if lane_id is not None and str(lane_id) in member_to_track:
                obj["logical_lane_id"] = member_to_track[str(lane_id)]
                obj["continuous_track_id"] = member_to_track[str(lane_id)]
            elif lane_id is not None:
                obj["logical_lane_id"] = None
                obj["continuous_track_id"] = None

    result["continuous_track_member_map"] = member_to_track


def run_lane_debug_v2(recording: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = dict(config or {})

    # First pass gives canonical lane geometry and all normal debug evidence.
    result = run_static_order(recording, cfg)
    settings = {**(result.get("debug_config") or {}), **cfg}

    # Hard experimental eligibility rule: intersection=true AND curved => unusable.
    filtered_geometry, eligibility_debug = exclude_curved_intersection_lanes(
        result.get("lane_geometry", []),
        enabled=bool(cfg.get("exclude_curved_intersection_lanes", True)),
        maximum_heading_change_deg=float(cfg.get("intersection_curved_maximum_heading_change_deg", 10.0)),
        maximum_abs_curvature_per_m=float(cfg.get("intersection_curved_maximum_abs_curvature_per_m", 0.02)),
    )
    result["lane_geometry"] = filtered_geometry
    result["lane_eligibility_debug"] = eligibility_debug
    result["excluded_curved_intersection_lane_ids"] = [
        x["lane_id"] for x in eligibility_debug if x.get("rejected")
    ]

    # Rebuild all physical tracks and inferred-route episodes from the filtered
    # geometry so banned lanes cannot influence final ego/adjacent tracking.
    _apply_static_order(recording, result, settings)
    base_tracks = result.get("continuous_lane_tracks", [])

    # Static inferred geometry comes from the complete overlap-box episode.
    static_inferred_lanes = build_static_inferred_lanes(result.get("inferred_ego_routes", []))

    # IMPORTANT: affiliation happens against base physical tracks before any
    # topology-supported neighbor stitching. No lane-order/adjacency evidence is
    # passed to this function.
    affiliated_lanes, affiliation_debug = assign_static_inferred_affiliations(
        static_inferred_lanes,
        base_tracks,
        maximum_endpoint_distance_m=float(cfg.get("static_inferred_lane_maximum_endpoint_distance_m", 20.0)),
        maximum_lateral_error_m=float(cfg.get("static_inferred_affiliation_maximum_lateral_error_m", 2.0)),
        maximum_heading_difference_deg=float(cfg.get("static_inferred_lane_maximum_heading_difference_deg", 30.0)),
        maximum_curvature_difference_per_m=float(cfg.get("static_inferred_affiliation_maximum_curvature_difference_per_m", 0.08)),
        maximum_width_difference_m=float(cfg.get("static_inferred_affiliation_maximum_width_difference_m", 1.0)),
    )

    integrated_tracks, static_inferred_debug = integrate_static_inferred_lanes(
        base_tracks,
        affiliated_lanes,
        _identity_alias(base_tracks),
        maximum_endpoint_distance_m=float(cfg.get("static_inferred_lane_maximum_endpoint_distance_m", 20.0)),
        maximum_heading_difference_deg=float(cfg.get("static_inferred_lane_maximum_heading_difference_deg", 30.0)),
    )
    connected_tracks, connector_debug = fill_static_inferred_endpoint_gaps(
        integrated_tracks,
        maximum_gap_m=float(cfg.get("static_inferred_connector_maximum_gap_m", 20.0)),
    )

    # Adjacency/topology is deliberately downstream of inferred-lane affiliation.
    post_inferred_order = build_static_lane_order(
        connected_tracks,
        sample_spacing_m=float(settings.get("lane_order_sample_spacing_m", 2.0)),
        maximum_heading_difference_deg=float(settings.get("lane_order_maximum_heading_difference_deg", 20.0)),
        minimum_lateral_m=float(settings.get("lane_order_minimum_lateral_m", 1.5)),
        maximum_lateral_m=float(settings.get("lane_order_maximum_lateral_m", 8.0)),
        maximum_longitudinal_m=float(settings.get("lane_order_maximum_longitudinal_m", 8.0)),
    )
    topology_tracks, topology_debug = stitch_topology_supported_neighbors(
        connected_tracks,
        post_inferred_order,
        maximum_gap_m=float(cfg.get("topology_supported_stitch_maximum_gap_m", 15.0)),
        maximum_reference_station_gap_m=float(cfg.get("topology_supported_stitch_maximum_reference_station_gap_m", 16.0)),
    )

    final_tracks = topology_tracks
    lane_order = build_static_lane_order(
        final_tracks,
        sample_spacing_m=float(settings.get("lane_order_sample_spacing_m", 2.0)),
        maximum_heading_difference_deg=float(settings.get("lane_order_maximum_heading_difference_deg", 20.0)),
        minimum_lateral_m=float(settings.get("lane_order_minimum_lateral_m", 1.5)),
        maximum_lateral_m=float(settings.get("lane_order_maximum_lateral_m", 8.0)),
        maximum_longitudinal_m=float(settings.get("lane_order_maximum_longitudinal_m", 8.0)),
    )

    result["continuous_lane_tracks"] = final_tracks
    result["static_inferred_lanes"] = affiliated_lanes
    result["static_inferred_affiliation_debug"] = affiliation_debug
    result["static_inferred_lane_debug"] = static_inferred_debug
    result["static_inferred_connector_debug"] = connector_debug
    result["topology_supported_stitch_debug"] = topology_debug
    result["static_inferred_lane_count"] = len(affiliated_lanes)
    result["static_inferred_lane_merge_count"] = sum(
        1 for x in static_inferred_debug if x.get("accepted") and x.get("action") == "merge_front_back_tracks"
    )
    result["static_inferred_connector_count"] = sum(
        1 for x in connector_debug if x.get("status") == "connector_created"
    )
    result["topology_supported_stitch_count"] = sum(1 for x in topology_debug if x.get("accepted"))
    result["static_lane_order_topology"] = lane_order
    result["constructed_lane_network"] = build_constructed_lane_network(final_tracks, lane_order)

    _recompute_frames(recording, result, final_tracks, lane_order, settings)
    result["schema_version"] = "lane-debug-v2-longitudinal-inferred-affiliation-v1"
    result["inferred_affiliation_policy"] = {
        "method": "longitudinal_endpoint_continuation_no_adjacency",
        "adjacency_used_for_affiliation": False,
        "affiliation_before_neighbor_topology": True,
    }
    return result
