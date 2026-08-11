"""Local, boundary-aware endpoint continuation evidence for static inferred lanes.

This module intentionally avoids track-wide median width.  It evaluates the
actual observed lane fragment nearest a physical-track endpoint against the
corresponding inferred-corridor endpoint.
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


def _endpoint_state(line: list[list[float]], side: str, window_points: int = 5) -> dict[str, Any] | None:
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


def _inferred_endpoint(inferred: dict[str, Any], role: str) -> dict[str, Any] | None:
    center = inferred.get("centerline_lcs_m") or []
    left = inferred.get("left_boundary_lcs_m") or []
    right = inferred.get("right_boundary_lcs_m") or []
    if len(center) < 2 or not left or not right:
        return None
    side = "start" if role == "back" else "end"
    state = _endpoint_state(center, side)
    if state is None:
        return None
    index = 0 if side == "start" else -1
    left_point = [float(left[index][0]), float(left[index][1])]
    right_point = [float(right[index][0]), float(right[index][1])]
    state.update({
        "side": side,
        "left_point": left_point,
        "right_point": right_point,
        "local_width_m": _dist(left_point, right_point),
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
        "local_width_m": _dist(left_point, right_point),
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

        reasons: list[str] = []
        if longitudinal <= 0.1 and center_distance > 0.25:
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
        if curvature_diff > maximum_curvature_difference_per_m:
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
            "score": round(score, 4),
            "rejection_reasons": reasons,
            "accepted_by_gates": not reasons,
        })
    return out


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
