"""Eligibility filters applied before experimental physical-track construction."""
from __future__ import annotations

import copy
import math
from typing import Any


def _wrap(value: float) -> float:
    return (value + math.pi) % (2.0 * math.pi) - math.pi


def _curvature_metrics(centerline: list[list[float]]) -> tuple[float, float]:
    pts = [[float(p[0]), float(p[1])] for p in centerline if len(p) >= 2]
    if len(pts) < 3:
        return 0.0, 0.0
    headings: list[float] = []
    lengths: list[float] = []
    for a, b in zip(pts, pts[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length <= 1e-6:
            continue
        headings.append(math.atan2(dy, dx))
        lengths.append(length)
    if len(headings) < 2:
        return 0.0, 0.0
    deltas = [_wrap(b - a) for a, b in zip(headings, headings[1:])]
    total_heading_change_deg = abs(math.degrees(sum(deltas)))
    local_curvatures = [abs(delta) / max(lengths[i], 1e-6) for i, delta in enumerate(deltas)]
    return total_heading_change_deg, max(local_curvatures, default=0.0)


def _raw_intersection_true(lane: dict[str, Any]) -> bool:
    evidence = set(str(x) for x in lane.get("intersection_evidence") or [])
    if "left_boundary_attribute" in evidence or "right_boundary_attribute" in evidence:
        return True
    return bool(
        (lane.get("left_boundary_attributes") or {}).get("intersection") is True
        or (lane.get("right_boundary_attributes") or {}).get("intersection") is True
    )


def exclude_curved_intersection_lanes(
    lane_geometry: list[dict[str, Any]],
    *,
    enabled: bool = True,
    maximum_heading_change_deg: float = 10.0,
    maximum_abs_curvature_per_m: float = 0.02,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Reject only lanes with raw ``intersection=true`` evidence AND curvature.

    A topology-only intersection connector is not rejected by this policy.
    Geometry remains available for debug/visualization, but assignment_valid is
    forced false for rejected lanes so they cannot enter final physical tracks.
    """
    lanes = copy.deepcopy(lane_geometry)
    debug: list[dict[str, Any]] = []
    for lane in lanes:
        heading_change_deg, max_curvature = _curvature_metrics(lane.get("centerline_lcs_m") or [])
        raw_intersection_true = _raw_intersection_true(lane)
        topology_intersection_connector = bool(lane.get("intersection_connector"))
        curved = (
            heading_change_deg > maximum_heading_change_deg
            or max_curvature > maximum_abs_curvature_per_m
        )
        rejected = bool(enabled and raw_intersection_true and curved and lane.get("assignment_valid"))
        record = {
            "lane_id": str(lane.get("lane_id")),
            "raw_intersection_true": raw_intersection_true,
            "topology_or_attribute_intersection_connector": topology_intersection_connector,
            "heading_change_deg": round(heading_change_deg, 3),
            "maximum_abs_curvature_per_m": round(max_curvature, 5),
            "curved": curved,
            "rejected": rejected,
            "intersection_evidence": list(lane.get("intersection_evidence") or []),
        }
        if rejected:
            lane["assignment_valid"] = False
            lane["invalid_reason"] = "excluded_curved_intersection_lane"
            lane["lane_detection_eligibility"] = {
                "eligible": False,
                "reason": "raw_intersection_true_and_curved",
                "heading_change_deg": record["heading_change_deg"],
                "maximum_abs_curvature_per_m": record["maximum_abs_curvature_per_m"],
            }
        else:
            lane["lane_detection_eligibility"] = {
                "eligible": bool(lane.get("assignment_valid")),
                "reason": lane.get("invalid_reason"),
                "heading_change_deg": record["heading_change_deg"],
                "maximum_abs_curvature_per_m": record["maximum_abs_curvature_per_m"],
            }
        debug.append(record)
    return lanes, debug
