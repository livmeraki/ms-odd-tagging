"""Second-pass integration for lane-debug-v2.

Runs the existing static-order detector, then:
1. merges fragmented lanes supported by consecutive static neighbor topology;
2. promotes completed ego-inferred route pieces into the same observed ego track
   when both ends resolve to that track;
3. recomputes ego/left/right roles against the final static network.
"""
from __future__ import annotations

import copy
from typing import Any

from .detector import _lane_output, _nearest_member
from .detector_static_order import run_lane_debug_v2 as run_static_order
from .neighbor_continuity_stitch import stitch_topology_supported_neighbors
from .static_lane_order import build_constructed_lane_network, build_static_lane_order, classify_lane_roles
from .strict_track_assignment import assign_point_to_track_strict


def _track_alias_map(tracks: list[dict[str, Any]]) -> dict[str, str]:
    out = {}
    for track in tracks:
        final_id = str(track.get("track_id"))
        out[final_id] = final_id
        for old in track.get("merged_from_track_ids") or []:
            out[str(old)] = final_id
    return out


def _promote_completed_inferred_routes(
    tracks: list[dict[str, Any]], routes: list[dict[str, Any]], alias: dict[str, str]
) -> list[dict[str, Any]]:
    tracks = copy.deepcopy(tracks)
    by_id = {str(t.get("track_id")): t for t in tracks}
    for route in routes:
        start = route.get("start_observed_track_id")
        end = route.get("end_observed_track_id")
        if not route.get("bridge_complete") or not start or not end:
            continue
        start_final = alias.get(str(start), str(start))
        end_final = alias.get(str(end), str(end))
        # Only promote when the inferred episode leaves and re-enters the same
        # final physical lane.  This avoids converting an unseen lane change into
        # a false static merge.
        if start_final != end_final or start_final not in by_id:
            continue
        track = by_id[start_final]
        existing_frames = {
            int(p.get("frame_index")) for p in track.get("pieces") or []
            if p.get("kind") == "ego_supported_inferred_route" and p.get("frame_index") is not None
        }
        promoted = 0
        for piece in route.get("pieces") or []:
            fi = piece.get("frame_index")
            if fi is not None and int(fi) in existing_frames:
                continue
            polygon = piece.get("polygon_lcs_m") or []
            center = piece.get("centerline_lcs_m") or []
            if len(polygon) < 3 or len(center) < 2:
                continue
            track.setdefault("pieces", []).append({
                "kind": "ego_supported_inferred_route",
                "frame_index": fi,
                "route_id": route.get("route_id"),
                "centerline_lcs_m": center,
                "polygon_lcs_m": polygon,
                "source": "boundary_inference_promoted_after_same_track_reentry",
            })
            promoted += 1
        if promoted:
            track["piece_count"] = len(track.get("pieces") or [])
            track["inferred_ego_route_piece_count"] = int(track.get("inferred_ego_route_piece_count", 0)) + promoted
            track["source"] = "canonical_with_ego_supported_gap_completion"
    return tracks


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
                "inferred": matched_kind == "ego_supported_inferred_route",
            }
            roles = classify_lane_roles(point, track_id, tracks, lane_order)
            frame["lane_roles"] = roles
            frame["left_lane"] = _lane_output(roles.get("left") or {}, point, track_by_id, lane_by_id)
            frame["right_lane"] = _lane_output(roles.get("right") or {}, point, track_by_id, lane_by_id)
        # If no final track contains ego, keep first-pass inferred evidence rather
        # than replacing it with an ungrounded assignment.

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
    final_tracks = _promote_completed_inferred_routes(
        topology_tracks, result.get("inferred_ego_routes", []), alias
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
    result["static_lane_order_topology"] = lane_order
    result["constructed_lane_network"] = build_constructed_lane_network(final_tracks, lane_order)
    _recompute_frames(recording, result, final_tracks, lane_order, {**(result.get("debug_config") or {}), **cfg})
    result["schema_version"] = "lane-debug-v2-integrated-route-topology-stitch-v1"
    return result
