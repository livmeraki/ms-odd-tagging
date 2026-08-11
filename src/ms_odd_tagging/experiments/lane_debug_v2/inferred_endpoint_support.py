"""Local, boundary-aware endpoint continuation evidence for static inferred lanes.

Literal inferred/observed endpoints are retained for center and boundary gap
checks. Tangent, curvature, and width are deliberately measured several metres
inside *both* lanes so terminal hooks/noise cannot dominate affiliation.
Track-wide median width is never used.
"""
from __future__ import annotations

import math
from typing import Any


INTERIOR_NEAR_M = 3.0
INTERIOR_FAR_M = 6.0


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


def _robust_endpoint_motion_state(
    center: list[list[float]],
    side: str,
) -> dict[str, Any] | None:
    """Measure stored lane direction using points 3 m and 6 m inside an endpoint.

    ``point`` remains the literal endpoint. ``near_point`` and ``far_point`` are
    reached by walking inward from that endpoint. For an ``end`` endpoint the
    inward walking direction is opposite the stored lane travel direction, so
    the reported heading and curvature are converted back to stored orientation.
    """
    pts = [[float(p[0]), float(p[1])] for p in center if len(p) >= 2]
    if len(pts) < 2:
        return None
    oriented = pts if side == "start" else list(reversed(pts))
    endpoint = oriented[0]
    near = _point_at_distance(oriented, INTERIOR_NEAR_M)
    far = _point_at_distance(oriented, INTERIOR_FAR_M)
    if _dist(endpoint, far) <= 1e-6:
        return None

    inward_heading = _heading(endpoint, far)
    travel_heading = inward_heading if side == "start" else _wrap(inward_heading + math.pi)
    first_heading = _heading(endpoint, near) if _dist(endpoint, near) > 1e-6 else inward_heading
    second_heading = _heading(near, far) if _dist(near, far) > 1e-6 else inward_heading
    curvature = _wrap(second_heading - first_heading) / max(_dist(near, far), 1e-6)
    if side == "end":
        curvature = -curvature

    return {
        "point": endpoint,
        "heading": travel_heading,
        "curvature": curvature,
        "near_point": near,
        "far_point": far,
        "method": "robust_3m_6m_interior_window",
    }


def _interior_endpoint_width(
    left: list[list[float]],
    right: list[list[float]],
    side: str,
) -> float | None:
    """Estimate local width from 3 m and 6 m interior boundary samples."""
    lpts = [[float(p[0]), float(p[1])] for p in left if len(p) >= 2]
    rpts = [[float(p[0]), float(p[1])] for p in right if len(p) >= 2]
    if not lpts or not rpts:
        return None
    if side == "end":
        lpts.reverse()
        rpts.reverse()
    widths = []
    for distance_m in (INTERIOR_NEAR_M, INTERIOR_FAR_M):
        lp = _point_at_distance(lpts, distance_m)
        rp = _point_at_distance(rpts, distance_m)
        width = _dist(lp, rp)
        if math.isfinite(width) and width > 0.1:
            widths.append(width)
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
    state = _robust_endpoint_motion_state(center, side)
    if state is None:
        return None
    index = 0 if side == "start" else -1
    left_point = [float(left[index][0]), float(left[index][1])]
    right_point = [float(right[index][0]), float(right[index][1])]
    local_width = _interior_endpoint_width(left, right, side)
    if local_width is None:
        local_width = _dist(left_point, right_point)
    state.update({
        "side": side,
        "left_point": left_point,
        "right_point": right_point,
        "local_width_m": local_width,
        "width_method": "median_3m_6m_interior_boundary_width",
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
            state = _robust_endpoint_motion_state(center, lane_side)
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
    local_width = _interior_endpoint_width(left, right, lane_side)
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
        "near_point": state["near_point"],
        "far_point": state["far_point"],
        "motion_method": state["method"],
        "left_point": left_point,
        "right_point": right_point,
        "local_width_m": local_width,
        "width_method": "median_3m_6m_interior_boundary_width",
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
            "candidate_heading_method": observed.get("motion_method"),
            "inferred_width_method": inferred_state.get("width_method"),
            "candidate_width_method": observed.get("width_method"),
            "inferred_interior_near_point": inferred_state.get("near_point"),
            "inferred_interior_far_point": inferred_state.get("far_point"),
            "candidate_interior_near_point": observed.get("near_point"),
            "candidate_interior_far_point": observed.get("far_point"),
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
