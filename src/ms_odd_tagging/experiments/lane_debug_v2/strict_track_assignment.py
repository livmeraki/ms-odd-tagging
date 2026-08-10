"""Strict ego-center containment for continuous lane-track assignment.

A track is eligible as the ego lane only when the ego center lies inside one
of its actual reconstructed member-lane polygons (or an accepted inferred-gap
polygon), or within the configured tolerance of that polygon boundary.
Centerline proximity is used only for scoring among already eligible tracks.
"""
from __future__ import annotations

import math
from typing import Any

from .lane_geometry import nearest_heading, point_in_polygon, polyline_distance, wrap_angle


def _polygon_membership(
    point: tuple[float, float],
    polygon: list[list[float]],
    tolerance_m: float,
) -> tuple[bool, bool, float]:
    if len(polygon) < 3:
        return False, False, math.inf
    inside = point_in_polygon(point, polygon)
    boundary = list(polygon)
    if boundary[0] != boundary[-1]:
        boundary = boundary + [boundary[0]]
    distance_m = 0.0 if inside else polyline_distance(point, boundary)
    return inside or distance_m <= tolerance_m, inside, distance_m


def assign_point_to_track_strict(
    point: tuple[float, float],
    heading: float | None,
    tracks: list[dict[str, Any]],
    *,
    previous_track_id: str | None = None,
    maximum_heading_difference_deg: float = 60.0,
    outside_tolerance_m: float = 1.0,
) -> dict[str, Any]:
    """Assign ego center using actual lane polygons with a hard tolerance gate."""
    candidates = []
    rejected = []

    for track in tracks:
        centerline = track.get("centerline_lcs_m") or []
        if len(centerline) < 2:
            continue

        lane_heading = nearest_heading(point, centerline)
        heading_difference = (
            0.0
            if heading is None or lane_heading is None
            else abs(math.degrees(wrap_angle(float(heading) - float(lane_heading))))
        )
        if heading_difference > maximum_heading_difference_deg:
            rejected.append(
                {
                    "track_id": track.get("track_id"),
                    "rejection_reason": "heading_difference",
                    "heading_difference_deg": round(heading_difference, 2),
                }
            )
            continue

        polygon_matches = []
        for piece_index, piece in enumerate(track.get("pieces") or []):
            kind = piece.get("kind")
            if kind not in {"observed_ld", "recovered_full_edge", "inferred_gap"}:
                continue
            polygon = piece.get("polygon_lcs_m") or []
            eligible, inside, polygon_distance = _polygon_membership(
                point, polygon, outside_tolerance_m
            )
            if eligible:
                polygon_matches.append(
                    {
                        "piece_index": piece_index,
                        "piece_kind": kind,
                        "lane_id": piece.get("lane_id"),
                        "source_lane_id": piece.get("source_lane_id"),
                        "destination_lane_id": piece.get("destination_lane_id"),
                        "inside_polygon": inside,
                        "polygon_distance_m": polygon_distance,
                    }
                )

        if not polygon_matches:
            rejected.append(
                {
                    "track_id": track.get("track_id"),
                    "rejection_reason": "ego_center_outside_lane_polygon_tolerance",
                    "outside_tolerance_m": outside_tolerance_m,
                    "center_distance_m": round(polyline_distance(point, centerline), 3),
                    "heading_difference_deg": round(heading_difference, 2),
                }
            )
            continue

        best_match = min(
            polygon_matches,
            key=lambda item: (
                0 if item["inside_polygon"] else 1,
                item["polygon_distance_m"],
                item["piece_index"],
            ),
        )
        center_distance = polyline_distance(point, centerline)
        score = (
            (0.0 if best_match["inside_polygon"] else best_match["polygon_distance_m"] * 10.0)
            + center_distance
            + heading_difference * 0.04
        )
        if track.get("track_id") == previous_track_id:
            score -= 0.9

        candidates.append(
            (
                score,
                track,
                best_match,
                center_distance,
                heading_difference,
            )
        )

    candidates.sort(key=lambda item: (item[0], str(item[1].get("track_id"))))
    if not candidates:
        return {
            "track_id": None,
            "logical_lane_id": None,
            "method": "no_track_contains_ego_center_within_tolerance",
            "confidence": "unknown",
            "outside_tolerance_m": outside_tolerance_m,
            "candidates": [],
            "rejected_candidates": rejected[:12],
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
        "method": "ego_center_in_actual_lane_polygon_with_tolerance",
        "confidence": confidence,
        "inside_polygon": match["inside_polygon"],
        "polygon_distance_m": round(match["polygon_distance_m"], 3),
        "matched_piece_kind": match["piece_kind"],
        "matched_lane_id": match.get("lane_id"),
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
                "inside_polygon": item[2]["inside_polygon"],
                "polygon_distance_m": round(item[2]["polygon_distance_m"], 3),
                "matched_piece_kind": item[2]["piece_kind"],
                "matched_lane_id": item[2].get("lane_id"),
                "center_distance_m": round(item[3], 3),
                "heading_difference_deg": round(item[4], 2),
            }
            for item in candidates[:5]
        ],
        "rejected_candidates": rejected[:12],
    }
