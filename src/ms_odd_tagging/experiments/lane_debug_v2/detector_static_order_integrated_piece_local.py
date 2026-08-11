"""Final role pass using piece-local track geometry.

The existing integrated detector owns reconstruction, inferred affiliation,
connectors, and topology-supported stitching. This wrapper adds a conservative
embedded-observed-fragment absorption pass before final lane ordering, then uses
piece-local geometry for ego/left/right role classification.
"""
from __future__ import annotations

from typing import Any

from .detector import _lane_output, _nearest_member
from .detector_static_order_integrated import run_lane_debug_v2 as run_integrated
from .embedded_fragment_absorption import absorb_embedded_observed_fragments
from .static_lane_order_piece_local import (
    build_constructed_lane_network,
    build_static_lane_order,
    classify_lane_roles,
)
from .strict_track_assignment import assign_point_to_track_strict


def _recompute_frames_piece_local(
    recording: dict[str, Any],
    result: dict[str, Any],
    tracks: list[dict[str, Any]],
    lane_order: dict[str, Any],
    config: dict[str, Any],
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
            point,
            float(heading),
            tracks,
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
                "source": "final_piece_local_static_lane_network",
                "track_source": None if not track else track.get("source"),
                "matched_piece_kind": matched_kind,
                "inferred": matched_kind in {
                    "ego_supported_inferred_route",
                    "static_inferred_corridor",
                    "static_inferred_connector",
                },
            }
            roles = classify_lane_roles(point, track_id, tracks, lane_order, float(heading))
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
                "source": "final_piece_local_static_lane_network",
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
    result = run_integrated(recording, cfg)
    settings = {**(result.get("debug_config") or {}), **cfg}

    # Repair duplicate track identities where a standalone observed fragment is
    # already embedded in one host track's inferred-gap geometry. Preserve the
    # host track ID and replace only the inferred gap with the observed fragment.
    tracks, absorption_debug = absorb_embedded_observed_fragments(
        result.get("continuous_lane_tracks", []),
        result.get("lane_geometry", []),
        maximum_endpoint_error_m=float(cfg.get("embedded_fragment_maximum_endpoint_error_m", 0.35)),
        maximum_heading_difference_deg=float(cfg.get("embedded_fragment_maximum_heading_difference_deg", 12.0)),
        maximum_centerline_deviation_m=float(cfg.get("embedded_fragment_maximum_centerline_deviation_m", 0.5)),
        maximum_width_difference_m=float(cfg.get("embedded_fragment_maximum_width_difference_m", 0.75)),
        require_boundary_continuity=bool(cfg.get("embedded_fragment_require_boundary_continuity", True)),
    )
    result["continuous_lane_tracks"] = tracks
    result["embedded_observed_fragment_absorption_debug"] = absorption_debug
    result["embedded_observed_fragment_absorption_count"] = sum(
        1 for row in absorption_debug if row.get("accepted")
    )

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
    _recompute_frames_piece_local(recording, result, tracks, lane_order, settings)
    result["final_lane_role_policy"] = {
        "method": "static_cross_section_piece_local_lane_order",
        "candidate_projection": "nearest_valid_track_piece_centerline",
        "static_inferred_corridor_participates": True,
        "embedded_observed_fragment_absorption_before_final_order": True,
    }
    result["embedded_fragment_absorption_policy"] = {
        "method": "replace_unambiguous_host_inferred_gap_with_standalone_observed_fragment",
        "preserve_host_track_id": True,
        "global_zero_gap_relaxation": False,
    }
    result["schema_version"] = "lane-debug-v2-piece-local-final-role-v3-embedded-fragment-absorption"
    return result
