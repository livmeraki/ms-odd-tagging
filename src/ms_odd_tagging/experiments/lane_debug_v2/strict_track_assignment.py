"""Strict ego-center containment for constructed lane-track assignment.

New ego-track acquisition requires the ego center to lie inside an actual
constructed polygon. The configured outside tolerance is a continuity allowance
only for the previously assigned track; it cannot acquire a nearby adjacent lane.
"""
from __future__ import annotations

import math
from typing import Any

from .lane_geometry import nearest_heading, point_in_polygon, polyline_distance, wrap_angle

_ALLOWED_PIECE_KINDS = {
    "observed_ld",
    "recovered_full_edge",
    "inferred_gap",
    "anchored_ld_bridge",
    "canonical_track_stitch",
    "topology_supported_curvature_stitch",
    "ego_supported_inferred_route",
    "static_inferred_corridor",
    "static_inferred_connector",
}


def _polygon_status(point: tuple[float, float], polygon: list[list[float]]) -> tuple[bool, float]:
    if len(polygon) < 3:
        return False, math.inf
    inside = point_in_polygon(point, polygon)
    boundary = list(polygon)
    if boundary[0] != boundary[-1]:
        boundary = boundary + [boundary[0]]
    distance_m = 0.0 if inside else polyline_distance(point, boundary)
    return inside, distance_m


def assign_point_to_track_strict(
    point: tuple[float, float],
    heading: float | None,
    tracks: list[dict[str, Any]],
    *,
    previous_track_id: str | None = None,
    maximum_heading_difference_deg: float = 60.0,
    outside_tolerance_m: float = 1.0,
) -> dict[str, Any]:
    candidates = []
    rejected = []
    for track in tracks:
        centerline = track.get("centerline_lcs_m") or []
        if len(centerline) < 2:
            continue
        track_id = str(track.get("track_id"))
        matches = []
        near_previous = []
        piece_heading_rejections = []
        for piece_index, piece in enumerate(track.get("pieces") or []):
            if piece.get("kind") not in _ALLOWED_PIECE_KINDS:
                continue
            piece_centerline = piece.get("centerline_lcs_m") or []
            lane_heading = nearest_heading(point, piece_centerline)
            heading_difference = (
                0.0
                if heading is None or lane_heading is None
                else abs(math.degrees(wrap_angle(float(heading) - float(lane_heading))))
            )
            inside, distance_m = _polygon_status(point, piece.get("polygon_lcs_m") or [])
            local_center_distance = (
                polyline_distance(point, piece_centerline)
                if len(piece_centerline) >= 2
                else math.inf
            )
            record = {
                "piece_index": piece_index,
                "piece_kind": piece.get("kind"),
                "lane_id": piece.get("lane_id"),
                "static_inferred_lane_id": piece.get("static_inferred_lane_id"),
                "route_id": piece.get("route_id"),
                "source_lane_id": piece.get("source_lane_id"),
                "destination_lane_id": piece.get("destination_lane_id"),
                "inside_polygon": inside,
                "polygon_distance_m": distance_m,
                "center_distance_m": local_center_distance,
                "heading_difference_deg": heading_difference,
            }
            if heading_difference > maximum_heading_difference_deg:
                if inside or (track_id == str(previous_track_id) and distance_m <= outside_tolerance_m):
                    piece_heading_rejections.append({
                        "piece_index": piece_index,
                        "piece_kind": piece.get("kind"),
                        "heading_difference_deg": round(heading_difference, 2),
                    })
                continue
            if inside:
                matches.append(record)
            elif track_id == str(previous_track_id) and distance_m <= outside_tolerance_m:
                near_previous.append(record)

        method = "inside_actual_lane_polygon"
        if matches:
            usable = matches
        elif near_previous:
            usable = near_previous
            method = "previous_track_tolerance_hold"
        else:
            near_any = any(
                _polygon_status(point, piece.get("polygon_lcs_m") or [])[1] <= outside_tolerance_m
                for piece in track.get("pieces") or []
                if piece.get("kind") in _ALLOWED_PIECE_KINDS
            )
            reason = (
                "heading_difference"
                if piece_heading_rejections and not near_any
                else "outside_polygon_tolerance_cannot_acquire_new_track"
                if near_any
                else "ego_center_outside_lane_polygon_tolerance"
            )
            rejected.append({
                "track_id": track_id,
                "rejection_reason": reason,
                "outside_tolerance_m": outside_tolerance_m,
                "center_distance_m": round(polyline_distance(point, centerline), 3),
                "piece_heading_rejections": piece_heading_rejections,
            })
            continue

        best_match = min(
            usable,
            key=lambda item: (
                0 if item["inside_polygon"] else 1,
                item["polygon_distance_m"],
                item["heading_difference_deg"],
                item["center_distance_m"],
                item["piece_index"],
            ),
        )
        center_distance = best_match["center_distance_m"]
        heading_difference = best_match["heading_difference_deg"]
        score = center_distance + heading_difference * 0.04
        if not best_match["inside_polygon"]:
            score += best_match["polygon_distance_m"] * 10.0
        if track_id == str(previous_track_id):
            score -= 0.9
        if best_match["piece_kind"] in {
            "anchored_ld_bridge",
            "canonical_track_stitch",
            "topology_supported_curvature_stitch",
            "ego_supported_inferred_route",
            "static_inferred_corridor",
            "static_inferred_connector",
        }:
            score += 0.15
        candidates.append((score, track, best_match, center_distance, heading_difference, method))

    candidates.sort(key=lambda item: (item[0], str(item[1].get("track_id"))))
    if not candidates:
        return {
            "track_id": None,
            "logical_lane_id": None,
            "method": "no_track_contains_ego_center",
            "confidence": "unknown",
            "outside_tolerance_m": outside_tolerance_m,
            "candidates": [],
            "rejected_candidates": rejected[:16],
        }

    best = candidates[0]
    margin = candidates[1][0] - best[0] if len(candidates) > 1 else None
    match = best[2]
    confidence = (
        "high"
        if match["inside_polygon"] and (margin is None or margin >= 1.0)
        else "medium"
        if match["inside_polygon"]
        else "low"
    )
    return {
        "track_id": best[1].get("track_id"),
        "logical_lane_id": best[1].get("logical_lane_id"),
        "member_lane_ids": best[1].get("member_lane_ids", []),
        "method": best[5],
        "confidence": confidence,
        "inside_polygon": match["inside_polygon"],
        "polygon_distance_m": round(match["polygon_distance_m"], 3),
        "matched_piece_kind": match["piece_kind"],
        "matched_lane_id": match.get("lane_id"),
        "matched_static_inferred_lane_id": match.get("static_inferred_lane_id"),
        "matched_route_id": match.get("route_id"),
        "matched_source_lane_id": match.get("source_lane_id"),
        "matched_destination_lane_id": match.get("destination_lane_id"),
        "outside_tolerance_m": outside_tolerance_m,
        "center_distance_m": round(best[3], 3),
        "heading_difference_deg": round(best[4], 2),
        "runner_up_score_margin": None if margin is None else round(margin, 3),
        "candidates": [
            {
                "track_id": item[1].get("track_id"),
                "score": round(item[0], 3),
                "method": item[5],
                "inside_polygon": item[2]["inside_polygon"],
                "polygon_distance_m": round(item[2]["polygon_distance_m"], 3),
                "matched_piece_kind": item[2]["piece_kind"],
                "matched_lane_id": item[2].get("lane_id"),
                "matched_static_inferred_lane_id": item[2].get("static_inferred_lane_id"),
                "matched_route_id": item[2].get("route_id"),
                "center_distance_m": round(item[3], 3),
                "heading_difference_deg": round(item[4], 2),
            }
            for item in candidates[:5]
        ],
        "rejected_candidates": rejected[:16],
    }
