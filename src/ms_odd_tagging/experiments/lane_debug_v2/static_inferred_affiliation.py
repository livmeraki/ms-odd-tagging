"""Choose static inferred-lane affiliations from longitudinal continuation only.

Adjacency is deliberately not used.  The backward end must connect to a track
endpoint behind the inferred corridor; the forward end must connect to a track
endpoint ahead of it.  Candidates are gated by lateral offset, heading,
curvature magnitude, width, and endpoint distance.
"""
from __future__ import annotations

import copy
import math
from typing import Any


def _dist(a, b) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _wrap(value: float) -> float:
    return (value + math.pi) % (2.0 * math.pi) - math.pi


def _heading(a, b) -> float:
    return math.atan2(float(b[1]) - float(a[1]), float(b[0]) - float(a[0]))


def _axis_heading_difference_deg(a: float, b: float) -> float:
    diff = abs(math.degrees(_wrap(a - b)))
    return min(diff, abs(180.0 - diff))


def _endpoint_metrics(line: list[list[float]], side: str) -> tuple[list[float], float, float] | None:
    pts = [[float(p[0]), float(p[1])] for p in line if len(p) >= 2]
    if len(pts) < 2:
        return None
    sample = pts[: min(5, len(pts))] if side == "start" else pts[-min(5, len(pts)):]
    if side == "start":
        sample = list(reversed(sample))
    headings: list[float] = []
    lengths: list[float] = []
    for a, b in zip(sample, sample[1:]):
        d = _dist(a, b)
        if d <= 1e-6:
            continue
        headings.append(_heading(a, b))
        lengths.append(d)
    if not headings:
        return None
    curvature = 0.0
    if len(headings) >= 2:
        curvature = sum(_wrap(b - a) for a, b in zip(headings, headings[1:])) / max(sum(lengths), 1e-6)
    return sample[-1], headings[-1], curvature


def _inferred_endpoint_state(center: list[list[float]], role: str) -> tuple[list[float], float, float] | None:
    if len(center) < 2:
        return None
    side = "start" if role == "back" else "end"
    metric = _endpoint_metrics(center, side)
    if metric is None:
        return None
    point, outward_heading, curvature = metric
    if role == "back":
        # endpoint_metrics(start) points from inferred interior toward the back;
        # travel direction through the inferred lane is the opposite.
        travel_heading = _wrap(outward_heading + math.pi)
        travel_curvature = -curvature
    else:
        travel_heading = outward_heading
        travel_curvature = curvature
    return point, travel_heading, travel_curvature


def _candidate(
    track: dict[str, Any],
    inferred_point: list[float],
    inferred_heading: float,
    inferred_curvature: float,
    inferred_width: float,
    role: str,
    *,
    maximum_endpoint_distance_m: float,
    maximum_lateral_error_m: float,
    maximum_heading_difference_deg: float,
    maximum_curvature_difference_per_m: float,
    maximum_width_difference_m: float,
) -> list[dict[str, Any]]:
    line = track.get("centerline_lcs_m") or []
    if len(line) < 2:
        return []
    width = float(track.get("median_width_m", 3.5))
    out: list[dict[str, Any]] = []
    ux, uy = math.cos(inferred_heading), math.sin(inferred_heading)
    nx, ny = -uy, ux
    for side in ("start", "end"):
        state = _endpoint_metrics(line, side)
        if state is None:
            continue
        endpoint, endpoint_outward_heading, endpoint_curvature = state
        if role == "back":
            # endpoint must lie behind the inferred start; its outward tangent
            # should point toward the inferred corridor.
            vx, vy = inferred_point[0] - endpoint[0], inferred_point[1] - endpoint[1]
            longitudinal = vx * ux + vy * uy
            lateral = abs(vx * nx + vy * ny)
            candidate_travel_heading = endpoint_outward_heading
            candidate_curvature = endpoint_curvature
        else:
            # endpoint must lie ahead of inferred end; entering the candidate
            # track is opposite its outward endpoint tangent.
            vx, vy = endpoint[0] - inferred_point[0], endpoint[1] - inferred_point[1]
            longitudinal = vx * ux + vy * uy
            lateral = abs(vx * nx + vy * ny)
            candidate_travel_heading = _wrap(endpoint_outward_heading + math.pi)
            candidate_curvature = -endpoint_curvature
        distance = _dist(endpoint, inferred_point)
        heading_diff = _axis_heading_difference_deg(candidate_travel_heading, inferred_heading)
        curvature_diff = abs(abs(candidate_curvature) - abs(inferred_curvature))
        width_diff = abs(width - inferred_width)
        rejections: list[str] = []
        if longitudinal <= 0.1:
            rejections.append("not_longitudinally_before_or_after")
        if distance > maximum_endpoint_distance_m:
            rejections.append("endpoint_distance")
        if lateral > maximum_lateral_error_m:
            rejections.append("lateral_error_adjacent_or_parallel")
        if heading_diff > maximum_heading_difference_deg:
            rejections.append("heading_difference")
        if curvature_diff > maximum_curvature_difference_per_m:
            rejections.append("curvature_difference")
        if width_diff > maximum_width_difference_m:
            rejections.append("width_difference")
        score = (
            distance
            + lateral * 5.0
            + heading_diff * 0.08
            + curvature_diff * 20.0
            + width_diff * 2.0
        )
        out.append({
            "track_id": str(track.get("track_id")),
            "endpoint_side": side,
            "role": role,
            "distance_m": round(distance, 3),
            "longitudinal_m": round(longitudinal, 3),
            "lateral_error_m": round(lateral, 3),
            "heading_difference_deg": round(heading_diff, 3),
            "curvature_difference_per_m": round(curvature_diff, 5),
            "width_difference_m": round(width_diff, 3),
            "score": round(score, 4),
            "rejection_reasons": rejections,
        })
    return out


def assign_static_inferred_affiliations(
    static_lanes: list[dict[str, Any]],
    tracks: list[dict[str, Any]],
    *,
    maximum_endpoint_distance_m: float = 20.0,
    maximum_lateral_error_m: float = 2.0,
    maximum_heading_difference_deg: float = 30.0,
    maximum_curvature_difference_per_m: float = 0.08,
    maximum_width_difference_m: float = 1.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Overwrite remembered temporal IDs with geometric before/after tracks."""
    resolved = copy.deepcopy(static_lanes)
    debug: list[dict[str, Any]] = []
    for inferred in resolved:
        center = inferred.get("centerline_lcs_m") or []
        width = float(inferred.get("median_width_m", 3.5))
        record = {
            "static_inferred_lane_id": inferred.get("static_inferred_lane_id"),
            "route_id": inferred.get("route_id"),
            "method": "longitudinal_endpoint_continuation_no_adjacency",
            "remembered_start_track_id": inferred.get("start_observed_track_id"),
            "remembered_end_track_id": inferred.get("end_observed_track_id"),
        }
        chosen: dict[str, str | None] = {"back": None, "front": None}
        for role in ("back", "front"):
            state = _inferred_endpoint_state(center, role)
            if state is None:
                record[f"{role}_candidates"] = []
                continue
            point, heading, curvature = state
            candidates: list[dict[str, Any]] = []
            for track in tracks:
                candidates.extend(_candidate(
                    track, point, heading, curvature, width, role,
                    maximum_endpoint_distance_m=maximum_endpoint_distance_m,
                    maximum_lateral_error_m=maximum_lateral_error_m,
                    maximum_heading_difference_deg=maximum_heading_difference_deg,
                    maximum_curvature_difference_per_m=maximum_curvature_difference_per_m,
                    maximum_width_difference_m=maximum_width_difference_m,
                ))
            candidates.sort(key=lambda x: (len(x["rejection_reasons"]) > 0, x["score"], x["track_id"], x["endpoint_side"]))
            accepted = [c for c in candidates if not c["rejection_reasons"]]
            if accepted:
                chosen[role] = accepted[0]["track_id"]
                accepted[0]["selected"] = True
            record[f"{role}_candidates"] = candidates[:16]
            record[f"{role}_selected_track_id"] = chosen[role]
        inferred["start_observed_track_id"] = chosen["back"]
        inferred["end_observed_track_id"] = chosen["front"]
        inferred["bridge_complete"] = bool(chosen["back"] and chosen["front"])
        inferred["affiliation_method"] = "longitudinal_endpoint_continuation_no_adjacency"
        record["accepted"] = bool(inferred["bridge_complete"])
        debug.append(record)
    return resolved, debug
