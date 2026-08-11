"""Fallback continuation for fragmented observed lanes using local interior geometry.

This stage sits between exact observed-touch and curvature-only inference. Literal
center/left/right endpoints are used for physical gap checks, while tangent,
curvature, and width are measured from the same 3/4.5/6 m interior window used
for static inferred-lane affiliation. Only unique outgoing/incoming continuation
pairs are returned.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from .curvature_gap_fill import build_curvature_gap
from .inferred_endpoint_support import (
    _axis_heading_difference_deg,
    _dist,
    _interior_endpoint_width,
    _robust_endpoint_motion_state,
)


def _edge_identity(source: dict[str, Any], destination: dict[str, Any]) -> tuple[bool, bool, int]:
    same_left = (
        source.get("left_edge_id") is not None
        and str(source.get("left_edge_id")) == str(destination.get("left_edge_id"))
    )
    same_right = (
        source.get("right_edge_id") is not None
        and str(source.get("right_edge_id")) == str(destination.get("right_edge_id"))
    )
    return same_left, same_right, int(same_left) + int(same_right)


def _candidate(
    source: dict[str, Any],
    destination: dict[str, Any],
    *,
    maximum_center_gap_m: float,
    maximum_boundary_gap_m: float,
    maximum_lateral_error_m: float,
    maximum_heading_difference_deg: float,
    maximum_curvature_difference_per_m: float,
    maximum_width_difference_m: float,
) -> dict[str, Any] | None:
    src_center = source.get("centerline_lcs_m") or []
    dst_center = destination.get("centerline_lcs_m") or []
    src_left = source.get("left_boundary_lcs_m") or []
    src_right = source.get("right_boundary_lcs_m") or []
    dst_left = destination.get("left_boundary_lcs_m") or []
    dst_right = destination.get("right_boundary_lcs_m") or []
    if min(len(src_center), len(dst_center), len(src_left), len(src_right), len(dst_left), len(dst_right)) < 2:
        return None

    # Canonical observed lanes carry a forward orientation, so fragmented-lane
    # continuation is source END -> destination START. Geometry at those ends is
    # evaluated using interior-only anchors rather than terminal samples.
    src_state = _robust_endpoint_motion_state(src_center, "end")
    dst_state = _robust_endpoint_motion_state(dst_center, "start")
    if src_state is None or dst_state is None:
        return None

    src_point = src_state["point"]
    dst_point = dst_state["point"]
    center_gap = _dist(src_point, dst_point)
    if center_gap > maximum_center_gap_m:
        return None

    src_heading = float(src_state["heading"])
    ux, uy = math.cos(src_heading), math.sin(src_heading)
    nx, ny = -uy, ux
    vx, vy = float(dst_point[0]) - float(src_point[0]), float(dst_point[1]) - float(src_point[1])
    longitudinal = vx * ux + vy * uy
    lateral = abs(vx * nx + vy * ny)

    left_gap = _dist(src_left[-1], dst_left[0])
    right_gap = _dist(src_right[-1], dst_right[0])
    heading_diff = _axis_heading_difference_deg(src_heading, float(dst_state["heading"]))
    curvature_diff = abs(abs(float(src_state["curvature"])) - abs(float(dst_state["curvature"])))

    src_width = _interior_endpoint_width(src_left, src_right, "end")
    dst_width = _interior_endpoint_width(dst_left, dst_right, "start")
    width_diff = math.inf if src_width is None or dst_width is None else abs(src_width - dst_width)
    same_left, same_right, identity_score = _edge_identity(source, destination)

    reasons: list[str] = []
    if longitudinal < -0.25:
        reasons.append("destination_not_longitudinally_ahead")
    if left_gap > maximum_boundary_gap_m:
        reasons.append("left_boundary_endpoint_gap")
    if right_gap > maximum_boundary_gap_m:
        reasons.append("right_boundary_endpoint_gap")
    if lateral > maximum_lateral_error_m:
        reasons.append("lateral_error_adjacent_or_parallel")
    if heading_diff > maximum_heading_difference_deg:
        reasons.append("interior_tangent_difference")
    if curvature_diff > maximum_curvature_difference_per_m:
        reasons.append("interior_curvature_difference")
    if not math.isfinite(width_diff) or width_diff > maximum_width_difference_m:
        reasons.append("interior_width_difference")

    score = (
        center_gap
        + 0.35 * (left_gap + right_gap)
        + 5.0 * lateral
        + 0.08 * heading_diff
        + 20.0 * curvature_diff
        + 2.0 * (width_diff if math.isfinite(width_diff) else 999.0)
        - 0.75 * identity_score
    )

    fill = None
    if not reasons and center_gap > 0.25 and src_width is not None and dst_width is not None:
        fill = build_curvature_gap(
            src_center,
            "end",
            dst_center,
            "start",
            width_a_m=float(src_width),
            width_b_m=float(dst_width),
        )
        if fill is None:
            reasons.append("connector_generation_failed")
        else:
            if float(fill.get("arc_to_chord_ratio", 999.0)) > 1.6:
                reasons.append("connector_arc_too_long")
            if float(fill.get("maximum_abs_bridge_curvature_per_m", 999.0)) > 0.25:
                reasons.append("connector_curvature_too_high")

    return {
        "source_lane_id": str(source.get("lane_id")),
        "destination_lane_id": str(destination.get("lane_id")),
        "center_gap_m": round(center_gap, 4),
        "left_boundary_gap_m": round(left_gap, 4),
        "right_boundary_gap_m": round(right_gap, 4),
        "longitudinal_m": round(longitudinal, 4),
        "lateral_error_m": round(lateral, 4),
        "heading_difference_deg": round(heading_diff, 3),
        "curvature_difference_per_m": round(curvature_diff, 5),
        "source_local_width_m": None if src_width is None else round(src_width, 3),
        "destination_local_width_m": None if dst_width is None else round(dst_width, 3),
        "local_width_difference_m": None if not math.isfinite(width_diff) else round(width_diff, 3),
        "same_left_edge_id": same_left,
        "same_right_edge_id": same_right,
        "boundary_identity_score": identity_score,
        "source_interior_near_point": src_state.get("near_point"),
        "source_interior_middle_point": src_state.get("middle_point"),
        "source_interior_far_point": src_state.get("far_point"),
        "destination_interior_near_point": dst_state.get("near_point"),
        "destination_interior_middle_point": dst_state.get("middle_point"),
        "destination_interior_far_point": dst_state.get("far_point"),
        "interior_geometry_method": src_state.get("method"),
        "score": round(score, 4),
        "rejection_reasons": reasons,
        "eligible": not reasons,
        "connection_centerline_lcs_m": [] if fill is None else fill.get("centerline_lcs_m", []),
        "connection_polygon_lcs_m": [] if fill is None else fill.get("polygon_lcs_m", []),
        "connector_method": None if fill is None else fill.get("method"),
        "method": "observed_fragment_local_interior_endpoint_affiliation",
    }


def build_observed_local_affiliation_graph(
    lane_geometry: list[dict[str, Any]],
    *,
    excluded_source_ids: set[str] | None = None,
    maximum_center_gap_m: float = 12.0,
    maximum_boundary_gap_m: float = 12.0,
    maximum_lateral_error_m: float = 1.5,
    maximum_heading_difference_deg: float = 20.0,
    maximum_curvature_difference_per_m: float = 0.08,
    maximum_width_difference_m: float = 0.9,
    minimum_unique_score_margin: float = 0.75,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Return unique observed-fragment continuations not covered by exact touch."""
    excluded_source_ids = {str(x) for x in (excluded_source_ids or set())}
    lanes = [
        lane for lane in lane_geometry
        if lane.get("assignment_valid") and not lane.get("intersection_connector")
    ]
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    debug: list[dict[str, Any]] = []

    for source in lanes:
        sid = str(source.get("lane_id"))
        if sid in excluded_source_ids:
            continue
        for destination in lanes:
            if source is destination:
                continue
            row = _candidate(
                source,
                destination,
                maximum_center_gap_m=maximum_center_gap_m,
                maximum_boundary_gap_m=maximum_boundary_gap_m,
                maximum_lateral_error_m=maximum_lateral_error_m,
                maximum_heading_difference_deg=maximum_heading_difference_deg,
                maximum_curvature_difference_per_m=maximum_curvature_difference_per_m,
                maximum_width_difference_m=maximum_width_difference_m,
            )
            if row is not None:
                by_source[sid].append(row)

    outgoing_selected: dict[str, dict[str, Any]] = {}
    for sid, rows in by_source.items():
        eligible = sorted(
            (row for row in rows if row.get("eligible")),
            key=lambda row: (
                -int(row.get("boundary_identity_score", 0)),
                float(row.get("score", math.inf)),
                str(row.get("destination_lane_id")),
            ),
        )
        if not eligible:
            debug.extend(rows)
            continue

        chosen = eligible[0]
        if len(eligible) > 1:
            identity0 = int(eligible[0].get("boundary_identity_score", 0))
            identity1 = int(eligible[1].get("boundary_identity_score", 0))
            margin = float(eligible[1]["score"]) - float(eligible[0]["score"])
            if identity0 <= identity1 and margin < minimum_unique_score_margin:
                for row in rows:
                    out = dict(row)
                    if out.get("eligible"):
                        out["eligible"] = False
                        out["rejection_reasons"] = list(out.get("rejection_reasons") or []) + [
                            "ambiguous_multiple_local_continuations"
                        ]
                    debug.append(out)
                continue
            chosen["runner_up_score_margin"] = round(margin, 4)
        outgoing_selected[sid] = chosen

    # Destination uniqueness: one fragment cannot be consumed by two upstream
    # fragments unless one has strictly stronger boundary identity or score.
    incoming: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for sid, edge in outgoing_selected.items():
        incoming[str(edge["destination_lane_id"])].append((sid, edge))

    selected = dict(outgoing_selected)
    for destination_id, items in incoming.items():
        if len(items) <= 1:
            continue
        ranked = sorted(
            items,
            key=lambda pair: (
                -int(pair[1].get("boundary_identity_score", 0)),
                float(pair[1].get("score", math.inf)),
                pair[0],
            ),
        )
        best_sid, best = ranked[0]
        second = ranked[1][1]
        identity0 = int(best.get("boundary_identity_score", 0))
        identity1 = int(second.get("boundary_identity_score", 0))
        margin = float(second["score"]) - float(best["score"])
        unique = identity0 > identity1 or margin >= minimum_unique_score_margin
        if unique:
            for sid, _ in ranked[1:]:
                selected.pop(sid, None)
        else:
            for sid, _ in ranked:
                selected.pop(sid, None)
        for sid, edge in ranked:
            if sid in selected:
                continue
            out = dict(edge)
            out["eligible"] = False
            out["rejection_reasons"] = list(out.get("rejection_reasons") or []) + [
                "ambiguous_multiple_local_incoming_continuations"
            ]
            debug.append(out)

    for sid, edge in outgoing_selected.items():
        if sid in selected:
            debug.append({**edge, "accepted": True})
        elif not any(
            row.get("source_lane_id") == sid and row.get("destination_lane_id") == edge.get("destination_lane_id")
            for row in debug
        ):
            debug.append({**edge, "accepted": False})

    return selected, debug
