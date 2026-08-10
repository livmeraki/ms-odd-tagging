"""Boundary-aware ego-corridor inference for lane-debug v2.

When no reconstructed lane polygon validly contains ego, infer a temporary ego
corridor from physical LD lines / reconstructed lane boundaries that enclose the
ego center. This is explicit inferred geometry, never promoted to observed LD.
"""
from __future__ import annotations

import math
from typing import Any

from .lane_geometry import point_in_polygon, wrap_angle


def _dist(a, b) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _orientation_difference_deg(a: float, b: float) -> float:
    diff = abs(math.degrees(wrap_angle(a - b)))
    return min(diff, abs(180.0 - diff))


def _nearest_projection(point: tuple[float, float], line: list[list[float]]) -> tuple[float, list[float], float] | None:
    best = None
    for a, b in zip(line, line[1:]):
        ax, ay, bx, by = float(a[0]), float(a[1]), float(b[0]), float(b[1])
        dx, dy = bx - ax, by - ay
        denom = dx * dx + dy * dy
        if denom <= 1e-12:
            continue
        t = max(0.0, min(1.0, ((point[0] - ax) * dx + (point[1] - ay) * dy) / denom))
        q = [ax + t * dx, ay + t * dy]
        d = _dist(point, q)
        h = math.atan2(dy, dx)
        item = (d, q, h)
        if best is None or d < best[0]:
            best = item
    return best


def _raw_ld_lines(recording: dict[str, Any]) -> list[dict[str, Any]]:
    store = recording.get("ld_feature_store") or {}
    point_lookup = {
        str(p.get("point_id")): p.get("position_lcs_m", [])[:2]
        for p in store.get("points", [])
        if len(p.get("position_lcs_m") or []) >= 2
    }
    out = []
    for collection, id_key, kind in (
        ("lane_lines", "line_id", "lane_line"),
        ("road_boundaries", "road_boundary_id", "road_boundary"),
    ):
        for feat in store.get(collection, []):
            point_ids = list(feat.get("point_ids") or [])
            if not point_ids:
                point_ids = [e.get("point_id") for e in feat.get("elements") or []]
            pts = [point_lookup[str(pid)] for pid in point_ids if str(pid) in point_lookup]
            if len(pts) >= 2:
                out.append({"boundary_id": str(feat.get(id_key)), "kind": kind, "points": pts, "source": "raw_ld"})
    return out


def _reconstructed_boundaries(lane_geometry: list[dict[str, Any]], member_to_track: dict[str, str]) -> list[dict[str, Any]]:
    out = []
    for lane in lane_geometry:
        if not lane.get("assignment_valid"):
            continue
        lane_id = str(lane.get("lane_id"))
        track_id = member_to_track.get(lane_id)
        for side, key, edge_key in (
            ("left", "left_boundary_lcs_m", "left_edge_id"),
            ("right", "right_boundary_lcs_m", "right_edge_id"),
        ):
            pts = lane.get(key) or []
            if len(pts) >= 2:
                out.append({
                    "boundary_id": str(lane.get(edge_key)) if lane.get(edge_key) is not None else f"lane:{lane_id}:{side}",
                    "kind": "reconstructed_lane_boundary",
                    "points": pts,
                    "source": "reconstructed_lane",
                    "lane_id": lane_id,
                    "track_id": track_id,
                    "lane_side": side,
                })
    return out


def _candidate_record(boundary: dict[str, Any], point: tuple[float, float], heading: float, maximum_heading_difference_deg: float, maximum_boundary_distance_m: float) -> dict[str, Any] | None:
    projection = _nearest_projection(point, boundary["points"])
    if projection is None:
        return None
    distance_m, q, line_heading = projection
    heading_difference = _orientation_difference_deg(line_heading, heading)
    if heading_difference > maximum_heading_difference_deg or distance_m > maximum_boundary_distance_m:
        return None
    nx, ny = -math.sin(heading), math.cos(heading)
    signed_lateral = (q[0] - point[0]) * nx + (q[1] - point[1]) * ny
    if abs(signed_lateral) < 0.25:
        return None
    return {
        **boundary,
        "nearest_point": q,
        "distance_m": distance_m,
        "signed_lateral_m": signed_lateral,
        "heading_difference_deg": heading_difference,
    }


def _sample_boundary_in_ego_frame(boundary: dict[str, Any], point: tuple[float, float], heading: float, stations: list[float]) -> list[list[float]] | None:
    c, s = math.cos(heading), math.sin(heading)
    nx, ny = -s, c
    projected = []
    for p in boundary["points"]:
        dx, dy = float(p[0]) - point[0], float(p[1]) - point[1]
        lon = c * dx + s * dy
        lat = nx * dx + ny * dy
        projected.append((lon, lat))
    projected.sort(key=lambda x: x[0])
    if len(projected) < 2 or projected[-1][0] - projected[0][0] < 2.0:
        return None
    out = []
    j = 0
    for target in stations:
        if target < projected[0][0] or target > projected[-1][0]:
            return None
        while j + 2 < len(projected) and projected[j + 1][0] < target:
            j += 1
        a, b = projected[j], projected[j + 1]
        span = b[0] - a[0]
        if span <= 1e-6:
            lat = a[1]
        else:
            t = (target - a[0]) / span
            lat = a[1] + t * (b[1] - a[1])
        out.append([point[0] + c * target + nx * lat, point[1] + s * target + ny * lat])
    return out


def infer_ego_corridor_from_boundaries(
    recording: dict[str, Any],
    lane_geometry: list[dict[str, Any]],
    member_to_track: dict[str, str],
    point: tuple[float, float],
    heading: float,
    *,
    maximum_heading_difference_deg: float = 25.0,
    minimum_corridor_width_m: float = 2.2,
    maximum_corridor_width_m: float = 6.5,
    maximum_boundary_distance_m: float = 7.0,
    half_length_m: float = 15.0,
    previous_boundary_ids: tuple[str | None, str | None] | None = None,
) -> dict[str, Any]:
    """Infer an ego corridor from an enclosing left/right physical-boundary pair."""
    raw = _raw_ld_lines(recording)
    reconstructed = _reconstructed_boundaries(lane_geometry, member_to_track)
    # Reconstructed boundaries retain lane/track identity; raw LD ensures lines
    # that are visible in the map but unused by a valid lane can still participate.
    candidates = []
    seen = set()
    for boundary in reconstructed + raw:
        key = (boundary.get("source"), boundary.get("boundary_id"), tuple(tuple(p) for p in boundary.get("points", [])[:2]))
        if key in seen:
            continue
        seen.add(key)
        record = _candidate_record(boundary, point, heading, maximum_heading_difference_deg, maximum_boundary_distance_m)
        if record is not None:
            candidates.append(record)
    left = [c for c in candidates if c["signed_lateral_m"] > 0]
    right = [c for c in candidates if c["signed_lateral_m"] < 0]
    pair_candidates = []
    previous_boundary_ids = previous_boundary_ids or (None, None)
    for l in left:
        for r in right:
            width = l["signed_lateral_m"] - r["signed_lateral_m"]
            if not (minimum_corridor_width_m <= width <= maximum_corridor_width_m):
                continue
            source_bonus = (0.35 if l["source"] == "reconstructed_lane" else 0.0) + (0.35 if r["source"] == "reconstructed_lane" else 0.0)
            continuity_bonus = (0.6 if l["boundary_id"] == previous_boundary_ids[0] else 0.0) + (0.6 if r["boundary_id"] == previous_boundary_ids[1] else 0.0)
            score = abs(width - 3.5) + 0.08 * (l["heading_difference_deg"] + r["heading_difference_deg"]) + 0.05 * (l["distance_m"] + r["distance_m"]) - source_bonus - continuity_bonus
            pair_candidates.append((score, l, r, width))
    pair_candidates.sort(key=lambda x: (x[0], x[1]["boundary_id"], x[2]["boundary_id"]))
    if not pair_candidates:
        return {"valid": False, "method": "no_enclosing_boundary_pair", "candidates": [{"boundary_id": c["boundary_id"], "source": c["source"], "signed_lateral_m": round(c["signed_lateral_m"], 3), "heading_difference_deg": round(c["heading_difference_deg"], 2)} for c in sorted(candidates, key=lambda x: abs(x["signed_lateral_m"]))[:12]]}

    score, left_boundary, right_boundary, width = pair_candidates[0]
    stations = [-half_length_m, -half_length_m / 2.0, 0.0, half_length_m / 2.0, half_length_m]
    left_pts = _sample_boundary_in_ego_frame(left_boundary, point, heading, stations)
    right_pts = _sample_boundary_in_ego_frame(right_boundary, point, heading, stations)
    if left_pts is None or right_pts is None:
        # Fall back to a short local cross-section corridor rather than inventing
        # long geometry outside the physical line support.
        c, s = math.cos(heading), math.sin(heading)
        nx, ny = -s, c
        half = min(5.0, half_length_m)
        left_lat = left_boundary["signed_lateral_m"]
        right_lat = right_boundary["signed_lateral_m"]
        left_pts = [[point[0] + c * st + nx * left_lat, point[1] + s * st + ny * left_lat] for st in (-half, half)]
        right_pts = [[point[0] + c * st + nx * right_lat, point[1] + s * st + ny * right_lat] for st in (-half, half)]
    centerline = [[(l[0] + r[0]) / 2.0, (l[1] + r[1]) / 2.0] for l, r in zip(left_pts, right_pts)]
    polygon = left_pts + list(reversed(right_pts))
    return {
        "valid": point_in_polygon(point, polygon),
        "method": "inferred_between_physical_boundaries",
        "confidence": "medium",
        "source": "raw_ld_and_reconstructed_boundaries",
        "score": round(score, 3),
        "width_at_ego_m": round(width, 3),
        "left_boundary_id": left_boundary["boundary_id"],
        "right_boundary_id": right_boundary["boundary_id"],
        "left_boundary_source": left_boundary["source"],
        "right_boundary_source": right_boundary["source"],
        "left_track_id": left_boundary.get("track_id"),
        "right_track_id": right_boundary.get("track_id"),
        "left_lane_id": left_boundary.get("lane_id"),
        "right_lane_id": right_boundary.get("lane_id"),
        "left_boundary_lcs_m": left_pts,
        "right_boundary_lcs_m": right_pts,
        "centerline_lcs_m": centerline,
        "polygon_lcs_m": polygon,
        "ego_center_inside_inferred_corridor": point_in_polygon(point, polygon),
        "candidate_pair_count": len(pair_candidates),
    }
