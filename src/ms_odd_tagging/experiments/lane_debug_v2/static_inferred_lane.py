"""Build recording-level static inferred lane components from ego corridor boxes.

The overlapping per-frame corridor boxes remain the evidence source. Completed
routes are converted into one static corridor available for the whole recording.
The corridor geometry is reconstructed from the union area of all overlapping
box polygons, then smoothed before front/back affiliation and track integration.
"""
from __future__ import annotations

import copy
import math
from typing import Any

from .lane_geometry import nearest_heading, wrap_angle
from .static_inferred_union import build_smoothed_box_union_corridor


def _dist(a: list[float], b: list[float]) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _append_points(target: list[list[float]], points: list[list[float]]) -> None:
    for p in points:
        if len(p) < 2:
            continue
        q = [float(p[0]), float(p[1])]
        if not target or _dist(target[-1], q) > 1e-4:
            target.append(q)


def build_static_inferred_lanes(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert overlapping-box routes into static smoothed union corridors.

    The final lane width/polygon is not a fixed-width fit through ego centers.
    Instead, every local cross-section is derived from the area union of the
    green evidence boxes and the resulting left/right envelopes are smoothed.
    """
    out: list[dict[str, Any]] = []
    for route in routes:
        pieces = sorted(route.get("pieces") or [], key=lambda p: int(p.get("frame_index", 0)))
        union = build_smoothed_box_union_corridor(pieces)
        if union is None or len(union.get("polygon_lcs_m") or []) < 4:
            continue
        out.append({
            "static_inferred_lane_id": f"static_{route.get('route_id')}",
            "route_id": route.get("route_id"),
            "start_observed_track_id": route.get("start_observed_track_id"),
            "end_observed_track_id": route.get("end_observed_track_id"),
            "bridge_complete": bool(route.get("bridge_complete")),
            "start_frame_index": route.get("start_frame_index"),
            "end_frame_index": route.get("end_frame_index"),
            "source": "smoothed_union_of_overlapping_ego_corridor_boxes",
            "evidence_box_count": len(pieces),
            "evidence_boxes": pieces,
            "centerline_lcs_m": union["centerline_lcs_m"],
            "left_boundary_lcs_m": union["left_boundary_lcs_m"],
            "right_boundary_lcs_m": union["right_boundary_lcs_m"],
            "polygon_lcs_m": union["polygon_lcs_m"],
            "median_width_m": round(float(union.get("median_width_m", 3.5)), 3),
            "geometry_method": union.get("method"),
            "union_debug": {
                "sample_spacing_m": union.get("sample_spacing_m"),
                "sample_count": union.get("sample_count"),
                "evidence_polygon_count": union.get("evidence_polygon_count"),
                "maximum_union_component_count_at_station": union.get("maximum_union_component_count_at_station"),
                "smoothing_passes": union.get("smoothing_passes"),
                "maximum_smoothing_deviation_m": union.get("maximum_smoothing_deviation_m"),
            },
            "longitudinal_extent_method": "smoothed_cross_sectional_area_union_of_all_overlapping_boxes",
        })
    return out


def _endpoint_support(track: dict[str, Any], point: list[float], inferred_heading: float | None) -> dict[str, Any] | None:
    line = track.get("centerline_lcs_m") or []
    if len(line) < 2:
        return None
    options = [("start", line[0]), ("end", line[-1])]
    side, endpoint = min(options, key=lambda x: _dist(x[1], point))
    distance = _dist(endpoint, point)
    lane_heading = nearest_heading((float(endpoint[0]), float(endpoint[1])), line)
    heading_diff = 0.0
    if inferred_heading is not None and lane_heading is not None:
        diff = abs(math.degrees(wrap_angle(float(lane_heading) - float(inferred_heading))))
        heading_diff = min(diff, abs(180.0 - diff))
    return {"side": side, "distance_m": distance, "heading_difference_deg": heading_diff}


def _robust_endpoint_heading(line: list[list[float]], side: str, window_m: float = 6.0) -> float | None:
    points = [[float(p[0]), float(p[1])] for p in line if len(p) >= 2]
    if len(points) < 2:
        return None
    oriented = points if side == "start" else list(reversed(points))
    endpoint = oriented[0]
    remaining = window_m
    target = oriented[-1]
    for a, b in zip(oriented, oriented[1:]):
        length = _dist(a, b)
        if length <= 1e-8:
            continue
        if remaining <= length:
            ratio = remaining / length
            target = [a[0] + ratio * (b[0] - a[0]), a[1] + ratio * (b[1] - a[1])]
            break
        remaining -= length
    outward = math.atan2(target[1] - endpoint[1], target[0] - endpoint[0])
    return outward if side == "start" else wrap_angle(outward + math.pi)


def _orient_for_exit(track: dict[str, Any], exit_side: str) -> list[list[float]]:
    line = [[float(p[0]), float(p[1])] for p in track.get("centerline_lcs_m") or []]
    return line if exit_side == "end" else list(reversed(line))


def _orient_for_entry(track: dict[str, Any], entry_side: str) -> list[list[float]]:
    line = [[float(p[0]), float(p[1])] for p in track.get("centerline_lcs_m") or []]
    return line if entry_side == "start" else list(reversed(line))


def integrate_static_inferred_lanes(
    tracks: list[dict[str, Any]],
    static_lanes: list[dict[str, Any]],
    alias: dict[str, str],
    *,
    maximum_endpoint_distance_m: float = 20.0,
    maximum_heading_difference_deg: float = 40.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Attach static corridors and merge supported before/after track pairs."""
    working = copy.deepcopy(tracks)
    debug: list[dict[str, Any]] = []

    for inferred in static_lanes:
        by_id = {str(t.get("track_id")): t for t in working}
        start_raw = inferred.get("start_observed_track_id")
        end_raw = inferred.get("end_observed_track_id")
        start_id = alias.get(str(start_raw), str(start_raw)) if start_raw else None
        end_id = alias.get(str(end_raw), str(end_raw)) if end_raw else None
        center = inferred.get("centerline_lcs_m") or []
        record = {
            "static_inferred_lane_id": inferred.get("static_inferred_lane_id"),
            "route_id": inferred.get("route_id"),
            "start_track_id": start_id,
            "end_track_id": end_id,
            "accepted": False,
            "action": "none",
        }
        if len(center) < 2 or not inferred.get("bridge_complete") or not start_id or not end_id:
            record["rejection_reason"] = "incomplete_route_or_missing_track_endpoint"
            debug.append(record)
            continue
        start_track, end_track = by_id.get(start_id), by_id.get(end_id)
        if start_track is None or end_track is None:
            record["rejection_reason"] = "resolved_track_not_found"
            debug.append(record)
            continue

        start_h = _robust_endpoint_heading(center, "start")
        end_h = _robust_endpoint_heading(center, "end")
        start_support = _endpoint_support(start_track, center[0], start_h)
        end_support = _endpoint_support(end_track, center[-1], end_h)
        record["start_support"] = start_support
        record["end_support"] = end_support
        if start_support is None or end_support is None:
            record["rejection_reason"] = "missing_track_centerline"
            debug.append(record)
            continue
        if start_support["distance_m"] > maximum_endpoint_distance_m or end_support["distance_m"] > maximum_endpoint_distance_m:
            record["rejection_reason"] = "endpoint_distance"
            debug.append(record)
            continue
        if start_support["heading_difference_deg"] > maximum_heading_difference_deg or end_support["heading_difference_deg"] > maximum_heading_difference_deg:
            record["rejection_reason"] = "endpoint_heading_difference"
            debug.append(record)
            continue

        static_piece = {
            "kind": "static_inferred_corridor",
            "route_id": inferred.get("route_id"),
            "static_inferred_lane_id": inferred.get("static_inferred_lane_id"),
            "centerline_lcs_m": center,
            "left_boundary_lcs_m": inferred.get("left_boundary_lcs_m"),
            "right_boundary_lcs_m": inferred.get("right_boundary_lcs_m"),
            "polygon_lcs_m": inferred.get("polygon_lcs_m"),
            "evidence_box_count": inferred.get("evidence_box_count"),
            "geometry_method": inferred.get("geometry_method"),
            "source": "static_lane_from_smoothed_box_area_union",
        }

        if start_id == end_id:
            track = start_track
            track.setdefault("pieces", []).append(static_piece)
            track["piece_count"] = len(track.get("pieces") or [])
            track["static_inferred_corridor_count"] = int(track.get("static_inferred_corridor_count", 0)) + 1
            track["source"] = "canonical_with_static_inferred_corridor"
            record.update({"accepted": True, "action": "attach_to_same_track", "final_track_id": start_id})
            debug.append(record)
            continue

        a_line = _orient_for_exit(start_track, start_support["side"])
        b_line = _orient_for_entry(end_track, end_support["side"])
        merged_center: list[list[float]] = []
        _append_points(merged_center, a_line)
        _append_points(merged_center, center)
        _append_points(merged_center, b_line)
        source_ids = list(dict.fromkeys(
            [str(x) for x in (start_track.get("merged_from_track_ids") or [start_id])]
            + [str(x) for x in (end_track.get("merged_from_track_ids") or [end_id])]
        ))
        new_id = source_ids[0]
        merged_track = {
            "track_id": new_id,
            "logical_lane_id": new_id,
            "member_lane_ids": list(start_track.get("member_lane_ids") or []) + list(end_track.get("member_lane_ids") or []),
            "centerline_lcs_m": merged_center,
            "polygon_lcs_m": [],
            "median_width_m": round((float(start_track.get("median_width_m", 3.5)) + float(end_track.get("median_width_m", 3.5))) / 2.0, 3),
            "pieces": list(start_track.get("pieces") or []) + [static_piece] + list(end_track.get("pieces") or []),
            "piece_count": len(start_track.get("pieces") or []) + len(end_track.get("pieces") or []) + 1,
            "observed_segment_count": int(start_track.get("observed_segment_count", 0)) + int(end_track.get("observed_segment_count", 0)),
            "inferred_gap_count": int(start_track.get("inferred_gap_count", 0)) + int(end_track.get("inferred_gap_count", 0)) + 1,
            "canonical_stitch_count": int(start_track.get("canonical_stitch_count", 0)) + int(end_track.get("canonical_stitch_count", 0)),
            "topology_supported_stitch_count": int(start_track.get("topology_supported_stitch_count", 0)) + int(end_track.get("topology_supported_stitch_count", 0)),
            "static_inferred_corridor_count": 1,
            "merged_from_track_ids": source_ids,
            "source": "static_inferred_corridor_merged_track",
        }
        working = [t for t in working if str(t.get("track_id")) not in {start_id, end_id}]
        working.append(merged_track)
        for old in source_ids:
            alias[str(old)] = new_id
        alias[start_id] = new_id
        alias[end_id] = new_id
        record.update({"accepted": True, "action": "merge_front_back_tracks", "final_track_id": new_id})
        debug.append(record)

    return working, debug
