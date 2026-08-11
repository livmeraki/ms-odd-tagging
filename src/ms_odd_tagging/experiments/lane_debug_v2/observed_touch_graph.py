"""Observed-fragment exact-touch continuation graph for lane-debug v2.

This stage runs before curvature/inferred-gap track construction. It links
canonical observed fragments whose physical endpoints already touch, so the
track builder never needs to leapfrog over real LD geometry.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


def _dist(a: list[float], b: list[float]) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _heading(a: list[float], b: list[float]) -> float:
    return math.atan2(float(b[1]) - float(a[1]), float(b[0]) - float(a[0]))


def _angle_diff_deg(a: float, b: float) -> float:
    d = (a - b + math.pi) % (2.0 * math.pi) - math.pi
    return abs(math.degrees(d))


def _endpoint_width(lane: dict[str, Any], *, at_end: bool) -> float | None:
    left = lane.get("left_boundary_lcs_m") or []
    right = lane.get("right_boundary_lcs_m") or []
    if not left or not right:
        return None
    lp = left[-1] if at_end else left[0]
    rp = right[-1] if at_end else right[0]
    if len(lp) < 2 or len(rp) < 2:
        return None
    return _dist(lp, rp)


def _candidate(
    source: dict[str, Any],
    destination: dict[str, Any],
    *,
    maximum_center_gap_m: float,
    maximum_boundary_gap_m: float,
    maximum_heading_difference_deg: float,
    maximum_local_width_difference_m: float,
) -> dict[str, Any] | None:
    src_center = source.get("centerline_lcs_m") or []
    dst_center = destination.get("centerline_lcs_m") or []
    src_left = source.get("left_boundary_lcs_m") or []
    src_right = source.get("right_boundary_lcs_m") or []
    dst_left = destination.get("left_boundary_lcs_m") or []
    dst_right = destination.get("right_boundary_lcs_m") or []
    if min(len(src_center), len(dst_center), len(src_left), len(src_right), len(dst_left), len(dst_right)) < 2:
        return None

    center_gap = _dist(src_center[-1], dst_center[0])
    if center_gap > maximum_center_gap_m:
        return None

    left_gap = _dist(src_left[-1], dst_left[0])
    right_gap = _dist(src_right[-1], dst_right[0])
    heading_diff = _angle_diff_deg(
        _heading(src_center[-2], src_center[-1]),
        _heading(dst_center[0], dst_center[1]),
    )
    source_width = _endpoint_width(source, at_end=True)
    destination_width = _endpoint_width(destination, at_end=False)
    width_diff = (
        math.inf
        if source_width is None or destination_width is None
        else abs(source_width - destination_width)
    )
    same_left = (
        source.get("left_edge_id") is not None
        and str(source.get("left_edge_id")) == str(destination.get("left_edge_id"))
    )
    same_right = (
        source.get("right_edge_id") is not None
        and str(source.get("right_edge_id")) == str(destination.get("right_edge_id"))
    )
    boundary_identity_score = int(same_left) + int(same_right)

    reasons: list[str] = []
    if left_gap > maximum_boundary_gap_m:
        reasons.append("left_boundary_endpoint_gap")
    if right_gap > maximum_boundary_gap_m:
        reasons.append("right_boundary_endpoint_gap")
    if heading_diff > maximum_heading_difference_deg:
        reasons.append("local_heading_difference")
    if not math.isfinite(width_diff) or width_diff > maximum_local_width_difference_m:
        reasons.append("local_endpoint_width_difference")

    return {
        "source_lane_id": str(source.get("lane_id")),
        "destination_lane_id": str(destination.get("lane_id")),
        "center_gap_m": round(center_gap, 4),
        "left_boundary_gap_m": round(left_gap, 4),
        "right_boundary_gap_m": round(right_gap, 4),
        "heading_difference_deg": round(heading_diff, 3),
        "source_local_width_m": None if source_width is None else round(source_width, 3),
        "destination_local_width_m": None if destination_width is None else round(destination_width, 3),
        "local_width_difference_m": None if not math.isfinite(width_diff) else round(width_diff, 3),
        "same_left_edge_id": same_left,
        "same_right_edge_id": same_right,
        "boundary_identity_score": boundary_identity_score,
        "rejection_reasons": reasons,
        "eligible": not reasons,
        "method": "observed_exact_touch_continuation",
    }


def build_observed_touch_graph(
    lane_geometry: list[dict[str, Any]],
    *,
    maximum_center_gap_m: float = 0.25,
    maximum_boundary_gap_m: float = 0.25,
    maximum_heading_difference_deg: float = 8.0,
    maximum_local_width_difference_m: float = 0.5,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Return one unambiguous exact-touch outgoing edge per observed fragment."""
    lanes = [
        lane for lane in lane_geometry
        if lane.get("assignment_valid") and not lane.get("intersection_connector")
    ]
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    debug: list[dict[str, Any]] = []

    for source in lanes:
        sid = str(source.get("lane_id"))
        for destination in lanes:
            if source is destination:
                continue
            row = _candidate(
                source,
                destination,
                maximum_center_gap_m=maximum_center_gap_m,
                maximum_boundary_gap_m=maximum_boundary_gap_m,
                maximum_heading_difference_deg=maximum_heading_difference_deg,
                maximum_local_width_difference_m=maximum_local_width_difference_m,
            )
            if row is not None:
                by_source[sid].append(row)

    selected: dict[str, dict[str, Any]] = {}
    for sid, rows in by_source.items():
        eligible = [r for r in rows if r.get("eligible")]
        if not eligible:
            debug.extend(rows)
            continue
        if len(eligible) > 1:
            best_identity = max(int(r.get("boundary_identity_score", 0)) for r in eligible)
            strongest = [r for r in eligible if int(r.get("boundary_identity_score", 0)) == best_identity]
            if best_identity <= 0 or len(strongest) != 1:
                for row in rows:
                    out = dict(row)
                    if out.get("eligible"):
                        out["eligible"] = False
                        out["rejection_reasons"] = list(out.get("rejection_reasons") or []) + [
                            "ambiguous_fork_multiple_observed_touch_destinations"
                        ]
                    debug.append(out)
                continue
            eligible = strongest
        chosen = min(
            eligible,
            key=lambda r: (
                -int(r.get("boundary_identity_score", 0)),
                float(r.get("center_gap_m", math.inf)),
                float(r.get("heading_difference_deg", math.inf)),
                str(r.get("destination_lane_id")),
            ),
        )
        selected[sid] = chosen
        for row in rows:
            out = dict(row)
            out["accepted"] = (
                out.get("source_lane_id") == chosen.get("source_lane_id")
                and out.get("destination_lane_id") == chosen.get("destination_lane_id")
            )
            debug.append(out)

    # Incoming fork protection: a destination may have only one accepted source.
    incoming: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for sid, edge in selected.items():
        incoming[str(edge["destination_lane_id"])].append((sid, edge))
    for destination_id, incoming_edges in incoming.items():
        if len(incoming_edges) <= 1:
            continue
        best_identity = max(int(edge.get("boundary_identity_score", 0)) for _, edge in incoming_edges)
        strongest = [(sid, edge) for sid, edge in incoming_edges if int(edge.get("boundary_identity_score", 0)) == best_identity]
        if best_identity > 0 and len(strongest) == 1:
            keep_sid = strongest[0][0]
            for sid, _ in incoming_edges:
                if sid != keep_sid:
                    selected.pop(sid, None)
        else:
            for sid, _ in incoming_edges:
                selected.pop(sid, None)
        for row in debug:
            if row.get("destination_lane_id") != destination_id or not row.get("accepted"):
                continue
            if str(row.get("source_lane_id")) not in selected:
                row["accepted"] = False
                row["eligible"] = False
                row["rejection_reasons"] = list(row.get("rejection_reasons") or []) + [
                    "ambiguous_fork_multiple_observed_touch_sources"
                ]

    return selected, debug


def inferred_gap_occupied_by_observed_fragment(
    source_lane: dict[str, Any],
    destination_lane: dict[str, Any],
    lane_geometry: list[dict[str, Any]],
    *,
    endpoint_tolerance_m: float = 0.35,
    maximum_heading_difference_deg: float = 12.0,
) -> dict[str, Any] | None:
    """Find a real fragment spanning an inferred source→destination gap."""
    src_center = source_lane.get("centerline_lcs_m") or []
    dst_center = destination_lane.get("centerline_lcs_m") or []
    if len(src_center) < 2 or len(dst_center) < 2:
        return None
    src_heading = _heading(src_center[-2], src_center[-1])
    for lane in lane_geometry:
        if not lane.get("assignment_valid"):
            continue
        lane_id = str(lane.get("lane_id"))
        if lane_id in {str(source_lane.get("lane_id")), str(destination_lane.get("lane_id"))}:
            continue
        center = lane.get("centerline_lcs_m") or []
        if len(center) < 2:
            continue
        start_gap = _dist(src_center[-1], center[0])
        end_gap = _dist(center[-1], dst_center[0])
        heading_diff = _angle_diff_deg(src_heading, _heading(center[0], center[1]))
        same_boundary = any(
            source_lane.get(key) is not None
            and str(source_lane.get(key)) == str(lane.get(key))
            for key in ("left_edge_id", "right_edge_id")
        )
        if (
            start_gap <= endpoint_tolerance_m
            and end_gap <= endpoint_tolerance_m
            and heading_diff <= maximum_heading_difference_deg
            and same_boundary
        ):
            return {
                "occupying_lane_id": lane_id,
                "source_to_fragment_start_gap_m": round(start_gap, 4),
                "fragment_end_to_destination_gap_m": round(end_gap, 4),
                "heading_difference_deg": round(heading_diff, 3),
                "reason": "compatible_observed_fragment_occupies_inferred_gap",
            }
    return None
