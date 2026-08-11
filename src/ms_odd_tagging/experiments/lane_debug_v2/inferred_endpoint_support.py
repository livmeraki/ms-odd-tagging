"""Local, boundary-aware endpoint continuation evidence for static inferred lanes.

Track-wide median width is deliberately avoided. The exact inferred/observed
boundary endpoints are used for endpoint-distance evidence, while tangent,
curvature, and width are measured over a short local interior window so the
smoothed union's terminal cap/hook does not create a false discontinuity.
"""
from __future__ import annotations

import math
from typing import Any


def _dist(a: list[float], b: list[float]) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _wrap(value: float) -> float:
    return (value + math.pi) % (2.0 * math.pi) - math.pi


def _heading(a: list[float], b: list[float]) -> float:
    return math.atan2(float(b[1]) - float(a[1]), float(b[0]) - float(a[0]))


def _axis_heading_difference_deg(a: float, b: float) -> float:
    diff = abs(math.degrees(_wrap(a - b)))
    return min(diff, abs(180.0 - diff))


def _point_at_distance(points: list[list[float]], distance_m: float) -> list[float]:
    remaining = max(0.0, float(distance_m))
    for a, b in zip(points, points[1:]):
        length = _dist(a, b)
        if length <= 1e-8:
            continue
        if remaining <= length:
            ratio = remaining / length
            return [
                float(a[0]) + ratio * (float(b[0]) - float(a[0])),
                float(a[1]) + ratio * (float(b[1]) - float(a[1])),
            ]
        remaining -= length
    return [float(points[-1][0]), float(points[-1][1])]


def _endpoint_state(line: list[list[float]], side: str, window_points: int = 5) -> dict[str, Any] | None:
    """Observed-fragment endpoint state in the fragment's stored orientation."""
    pts = [[float(p[0]), float(p[1])] for p in line if len(p) >= 2]
    if len(pts) < 2:
        return None
    if side == "start":
        sample = pts[: min(window_points, len(pts))]
        endpoint = sample[0]
    else:
        sample = pts[-min(window_points, len(pts)):]
        endpoint = sample[-1]
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
    tangent = headings[0] if side == "start" else headings[-1]
    curvature = 0.0
    if len(headings) >= 2:
        curvature = sum(_wrap(b - a) for a, b in zip(headings, headings[1:])) / max(sum(lengths), 1e-6)
    return {"point": endpoint, "heading": tangent, "curvature": curvature}


def _robust_inferred_motion_state(center: list[list[float]], role: str) -> dict[str, Any] | None:
    """Measure inferred road direction over 3-6 m, past short union end hooks.

    This restores the robust behavior that existed before the local-boundary
    affiliation refactor. The literal endpoint is retained for geometric
    distances, but heading/curvature are inferred from the interior road shape.
    """
    pts = [[float(p[0]), float(p[1])] for p in center if len(p) >= 2]
    if len(pts) < 2:
        return None
    oriented = pts if role == "back" else list(reversed(pts))
    endpoint = oriented[0]
    middle = _point_at_distance(oriented, 3.0)
    far = _point_at_distance(oriented, 6.0)
    if _dist(endpoint, far) <= 1e-6:
        return None
    outward = _heading(endpoint, far)
    travel_heading = outward if role == "back" else _wrap(outward + math.pi)
    first_heading = _heading(endpoint, middle) if _dist(endpoint, middle) > 1e-6 else outward
    second_heading = _heading(middle, far) if _dist(middle, far) > 1e-6 else outward
    curvature = _wrap(second_heading - first_heading) / max(_dist(middle, far), 1e-6)
    if role == "front":
        curvature = -curvature
    return {
        "point": endpoint,
        "heading": travel_heading,
        "curvature": curvature,
        "middle_point": middle,
        "far_point": far,
        "method": "robust_3m_6m_interior_window",
    }


def _local_endpoint_width(left: list[list[float]], right: list[list[float]], side: str, sample_count: int = 5) -> float | None:
    """Robust local width near an endpoint, never the whole-track median width."""
    n = min(len(left), len(right))
    if n <= 0:
        return None
    count = min(sample_count, n)
    indices = range(count) if side == "start" else range(n - count, n)
    widths = [
        _dist(
            [float(left[i][0]), float(left[i][1])],
            [float(right[i][0]), float(right[i][1])],
        )
        for i in indices
        if len(left[i]) >= 2 and len(right[i]) >= 2
    ]
    widths = [w for w in widths if math.isfinite(w) and w > 0.1]
    if not widths:
        return None
    widths.sort()
    return widths[len(widths) // 2]


def _inferred_endpoint(inferred: dict[str, Any], role: str) -> dict[str, Any] | None:
    center = inferred.get("centerline_lcs_m") or []
    left = inferred.get("left_boundary_lcs_m") or []
    right = inferred.get("right_boundary_lcs_m") or []
    if len(center) < 2 or not left or not right:
        return None
    side = "start" if role == "back" else "end"
    state = _robust_inferred_motion_state(center, role)
    if state is None:
        return None
    index = 0 if side == "start" else -1
    left_point = [float(left[index][0]), float(left[index][1])]
    right_point = [float(right[index][0]), float(right[index][1])]
    local_width = _local_endpoint_width(left, right, side)
    if local_width is None:
        local_width = _dist(left_point, right_point)
    state.update({
        "side": side,
        "left_point": left_point,
        "right_point": right_point,
        "local_width_m": local_width,
        "width_method": "median_first_or_last_5_union_cross_sections",
    })
    return state


def _nearest_observed_endpoint(
    track: dict[str, Any],
    lane_by_id: dict[str, dict[str, Any]],
    track_side: str,
) -> dict[str, Any] | None:
    track_line = track.get("centerline_lcs_m") or []
    if len(track_line) < 2:
        return None
    track_point = track_line[0] if track_side == "start" else track_line[-1]
    candidates: list[tuple[float, str, str, dict[str, Any], dict[str, Any]]] = []
    for piece in track.get("pieces") or []:
        lane_id = piece.get("lane_id")
        if lane_id is None:
            continue
        lane = lane_by_id.get(str(lane_id))
        if not lane:
            continue
        center = lane.get("centerline_lcs_m") or []
        if len(center) < 2:
            continue
        for lane_side, lane_point in (("start", center[0]), ("end", center[-1])):
            state = _endpoint_state(center, lane_side)
            if state is None:
                continue
            candidates.append((_dist(track_point, lane_point), str(lane_id), lane_side, lane, state))
    if not candidates:
        return None
    _, lane_id, lane_side, lane, state = min(candidates, key=lambda x: (x[0], x[1], x[2]))
    left = lane.get("left_boundary_lcs_m") or []
    right = lane.get("right_boundary_lcs_m") or []
    if not left or not right:
        return None
    index = 0 if lane_side == "start" else -1
    left_point = [float(left[index][0]), float(left[index][1])]
    right_point = [float(right[index][0]), float(right[index][1])]
    local_width = _local_endpoint_width(left, right, lane_side)
    if local_width is None:
        local_width = _dist(left_point, right_point)
    return {
        "track_id": str(track.get("track_id")),
        "track_endpoint_side": track_side,
        "lane_id": lane_id,
        "lane_endpoint_side": lane_side,
        "point": state["point"],
        "heading": state["heading"],
        "curvature": state["curvature"],
        "left_point": left_point,
        "right_point": right_point,
        "local_width_m": local_width,
        "width_method": "median_first_or_last_5_observed_cross_sections",
    }


def evaluate_inferred_endpoint_candidate(
    inferred: dict[str, Any],
    track: dict[str, Any],
    lane_by_id: dict[str, dict[str, Any]],
    role: str,
    *,
    maximum_endpoint_distance_m: float,
    maximum_boundary_endpoint_distance_m: float,
    maximum_lateral_error_m: float,
    maximum_heading_difference_deg: float,
    maximum_curvature_difference_per_m: float,
    maximum_width_difference_m: float,
) -> list[dict[str, Any]]:
    """Evaluate both physical-track endpoints against one inferred endpoint."""
    inferred_state = _inferred_endpoint(inferred, role)
    if inferred_state is None:
        return []
    ip = inferred_state["point"]
    ih = float(inferred_state["heading"])
    ux, uy = math.cos(ih), math.sin(ih)
    nx, ny = -uy, ux
    out: list[dict[str, Any]] = []

    for track_side in ("start", "end"):
        observed = _nearest_observed_endpoint(track, lane_by_id, track_side)
        if observed is None:
            continue
        cp = observed["point"]
        if role == "back":
            vx, vy = ip[0] - cp[0], ip[1] - cp[1]
        else:
            vx, vy = cp[0] - ip[0], cp[1] - ip[1]
        longitudinal = vx * ux + vy * uy
        lateral = abs(vx * nx + vy * ny)
        center_distance = _dist(cp, ip)
        heading_diff = _axis_heading_difference_deg(float(observed["heading"]), ih)
        curvature_diff = abs(abs(float(observed["curvature"])) - abs(float(inferred_state["curvature"])))
        width_diff = abs(float(observed["local_width_m"]) - float(inferred_state["local_width_m"]))

        # If the observed lane is stored in the opposite orientation, physical
        # left/right swap relative to the inferred travel direction.
        reverse_orientation = abs(math.degrees(_wrap(float(observed["heading"]) - ih))) > 90.0
        observed_left = observed["right_point"] if reverse_orientation else observed["left_point"]
        observed_right = observed["left_point"] if reverse_orientation else observed["right_point"]
        left_distance = _dist(observed_left, inferred_state["left_point"])
        right_distance = _dist(observed_right, inferred_state["right_point"])
        endpoint_inside_corridor = _point_in_polygon(cp, inferred.get("polygon_lcs_m") or [])

        reasons: list[str] = []
        if longitudinal <= 0.1 and center_distance > 0.25 and not endpoint_inside_corridor:
            reasons.append("not_longitudinally_before_or_after")
        if center_distance > maximum_endpoint_distance_m:
            reasons.append("center_endpoint_distance")
        if left_distance > maximum_boundary_endpoint_distance_m:
            reasons.append("left_boundary_endpoint_distance")
        if right_distance > maximum_boundary_endpoint_distance_m:
            reasons.append("right_boundary_endpoint_distance")
        if lateral > maximum_lateral_error_m:
            reasons.append("lateral_error_adjacent_or_parallel")
        if heading_diff > maximum_heading_difference_deg:
            reasons.append("local_tangent_difference")
        if width_diff > maximum_width_difference_m:
            reasons.append("local_endpoint_width_difference")
        # Retain the old overlap safeguard: when an observed endpoint already
        # lies in the inferred area, terminal union curvature is not a reliable
        # reason by itself to break a longitudinal continuation.
        if curvature_diff > maximum_curvature_difference_per_m and not endpoint_inside_corridor:
            reasons.append("local_curvature_difference")

        score = (
            center_distance
            + 0.35 * (left_distance + right_distance)
            + 5.0 * lateral
            + 0.08 * heading_diff
            + 20.0 * curvature_diff
            + 2.0 * width_diff
        )
        out.append({
            "track_id": str(track.get("track_id")),
            "role": role,
            "track_endpoint_side": track_side,
            "supporting_lane_id": observed["lane_id"],
            "supporting_lane_endpoint_side": observed["lane_endpoint_side"],
            "center_endpoint_distance_m": round(center_distance, 3),
            "left_boundary_endpoint_distance_m": round(left_distance, 3),
            "right_boundary_endpoint_distance_m": round(right_distance, 3),
            "longitudinal_m": round(longitudinal, 3),
            "lateral_error_m": round(lateral, 3),
            "heading_difference_deg": round(heading_diff, 3),
            "inferred_local_width_m": round(float(inferred_state["local_width_m"]), 3),
            "candidate_local_width_m": round(float(observed["local_width_m"]), 3),
            "local_width_difference_m": round(width_diff, 3),
            "curvature_difference_per_m": round(curvature_diff, 5),
            "reverse_boundary_orientation": reverse_orientation,
            "endpoint_inside_inferred_polygon": endpoint_inside_corridor,
            "inferred_heading_method": inferred_state.get("method"),
            "inferred_width_method": inferred_state.get("width_method"),
            "candidate_width_method": observed.get("width_method"),
            "score": round(score, 4),
            "rejection_reasons": reasons,
            "accepted_by_gates": not reasons,
        })
    return out


def _point_in_polygon(point: list[float], polygon: list[list[float]]) -> bool:
    if len(polygon) < 3:
        return False
    x, y = float(point[0]), float(point[1])
    inside = False
    j = len(polygon) - 1
    for i, current in enumerate(polygon):
        previous = polygon[j]
        if ((float(current[1]) > y) != (float(previous[1]) > y)) and (
            x < (float(previous[0]) - float(current[0])) * (y - float(current[1]))
            / (float(previous[1]) - float(current[1])) + float(current[0])
        ):
            inside = not inside
        j = i
    return inside


def select_unique_continuation(
    candidates: list[dict[str, Any]],
    *,
    minimum_score_margin: float,
) -> tuple[dict[str, Any] | None, str | None]:
    """Choose one track continuation only when it is unambiguous."""
    best_by_track: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        if candidate.get("rejection_reasons"):
            continue
        tid = str(candidate.get("track_id"))
        previous = best_by_track.get(tid)
        if previous is None or float(candidate.get("score", math.inf)) < float(previous.get("score", math.inf)):
            best_by_track[tid] = candidate
    accepted = sorted(best_by_track.values(), key=lambda x: (float(x.get("score", math.inf)), str(x.get("track_id"))))
    if not accepted:
        return None, "no_candidate_passed_local_endpoint_gates"
    if len(accepted) > 1:
        margin = float(accepted[1]["score"]) - float(accepted[0]["score"])
        if margin < minimum_score_margin:
            return None, "ambiguous_multiple_local_endpoint_continuations"
        accepted[0]["runner_up_score_margin"] = round(margin, 4)
    accepted[0]["selected"] = True
    return accepted[0], None
