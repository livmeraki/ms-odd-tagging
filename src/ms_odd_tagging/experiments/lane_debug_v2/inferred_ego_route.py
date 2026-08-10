"""Temporal continuity for boundary-inferred ego corridors.

Consecutive inferred corridors are grouped into persistent ego-route episodes.
The primary continuity evidence is direct polygon overlap between consecutive
per-frame inferred corridor boxes, with heading consistency as a guard against
crossing-road false joins.  Observed tracks immediately before/after an inferred
episode are stored as bridge endpoints.
"""
from __future__ import annotations

import math
from typing import Any

from .lane_geometry import nearest_heading, point_in_polygon, wrap_angle


def _orientation(a: list[float], b: list[float], c: list[float]) -> float:
    return (float(b[0]) - float(a[0])) * (float(c[1]) - float(a[1])) - (
        float(b[1]) - float(a[1])
    ) * (float(c[0]) - float(a[0]))


def _on_segment(a: list[float], b: list[float], p: list[float], eps: float = 1e-6) -> bool:
    return (
        min(float(a[0]), float(b[0])) - eps <= float(p[0]) <= max(float(a[0]), float(b[0])) + eps
        and min(float(a[1]), float(b[1])) - eps <= float(p[1]) <= max(float(a[1]), float(b[1])) + eps
        and abs(_orientation(a, b, p)) <= eps
    )


def _segments_intersect(a: list[float], b: list[float], c: list[float], d: list[float]) -> bool:
    o1, o2 = _orientation(a, b, c), _orientation(a, b, d)
    o3, o4 = _orientation(c, d, a), _orientation(c, d, b)
    if (o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0):
        return True
    return (
        _on_segment(a, b, c)
        or _on_segment(a, b, d)
        or _on_segment(c, d, a)
        or _on_segment(c, d, b)
    )


def corridor_polygons_overlap(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    """Return True when two inferred corridor polygons overlap or touch."""
    if not previous:
        return False
    a = previous.get("polygon_lcs_m") or []
    b = current.get("polygon_lcs_m") or []
    if len(a) < 3 or len(b) < 3:
        return False

    if any(point_in_polygon((float(p[0]), float(p[1])), b) for p in a):
        return True
    if any(point_in_polygon((float(p[0]), float(p[1])), a) for p in b):
        return True

    a_edges = list(zip(a, a[1:] + a[:1]))
    b_edges = list(zip(b, b[1:] + b[:1]))
    return any(_segments_intersect(a0, a1, b0, b1) for a0, a1 in a_edges for b0, b1 in b_edges)


def _heading_difference_deg(previous: dict[str, Any], current: dict[str, Any]) -> float | None:
    prev_center = previous.get("centerline_lcs_m") or []
    curr_center = current.get("centerline_lcs_m") or []
    if len(prev_center) < 2 or len(curr_center) < 2:
        return None
    prev_h = nearest_heading(tuple(prev_center[len(prev_center) // 2][:2]), prev_center)
    curr_h = nearest_heading(tuple(curr_center[len(curr_center) // 2][:2]), curr_center)
    if prev_h is None or curr_h is None:
        return None
    return abs(math.degrees(wrap_angle(curr_h - prev_h)))


def corridors_are_continuous(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    *,
    maximum_endpoint_gap_m: float = 5.0,
    maximum_heading_difference_deg: float = 25.0,
) -> bool:
    """Group corridors only when their physical boxes overlap and headings agree.

    ``maximum_endpoint_gap_m`` is retained in the signature for compatibility
    with existing configuration/callers, but endpoint proximity is no longer the
    basis of inferred-route continuity.
    """
    del maximum_endpoint_gap_m
    if not previous or not previous.get("valid") or not current.get("valid"):
        return False
    if not corridor_polygons_overlap(previous, current):
        return False
    heading_difference = _heading_difference_deg(previous, current)
    return heading_difference is None or heading_difference <= maximum_heading_difference_deg


class InferredEgoRouteTracker:
    def __init__(self, maximum_endpoint_gap_m: float = 5.0, maximum_heading_difference_deg: float = 25.0):
        self.maximum_endpoint_gap_m = maximum_endpoint_gap_m
        self.maximum_heading_difference_deg = maximum_heading_difference_deg
        self.counter = 0
        self.active_route_id: str | None = None
        self.active_start_track_id: str | None = None
        self.previous_corridor: dict[str, Any] | None = None
        self.routes: dict[str, dict[str, Any]] = {}

    def observe_actual_track(self, track_id: str | None, frame_index: int) -> None:
        if self.active_route_id and track_id:
            route = self.routes[self.active_route_id]
            route["end_observed_track_id"] = str(track_id)
            route["end_frame_index"] = frame_index
            route["bridge_complete"] = True
            self.active_route_id = None
            self.active_start_track_id = str(track_id)
            self.previous_corridor = None
        elif track_id:
            self.active_start_track_id = str(track_id)
            self.previous_corridor = None

    def observe_corridor(self, corridor: dict[str, Any], frame_index: int) -> dict[str, Any]:
        overlaps_previous = corridor_polygons_overlap(self.previous_corridor, corridor)
        heading_difference = (
            None if self.previous_corridor is None else _heading_difference_deg(self.previous_corridor, corridor)
        )
        continuous = corridors_are_continuous(
            self.previous_corridor,
            corridor,
            maximum_endpoint_gap_m=self.maximum_endpoint_gap_m,
            maximum_heading_difference_deg=self.maximum_heading_difference_deg,
        )
        if not self.active_route_id or not continuous:
            self.counter += 1
            self.active_route_id = f"inferred_ego_route_{self.counter:04d}"
            self.routes[self.active_route_id] = {
                "route_id": self.active_route_id,
                "start_observed_track_id": self.active_start_track_id,
                "end_observed_track_id": None,
                "start_frame_index": frame_index,
                "end_frame_index": frame_index,
                "bridge_complete": False,
                "continuity_method": "overlapping_inferred_corridor_polygons",
                "pieces": [],
            }
        route = self.routes[self.active_route_id]
        route["end_frame_index"] = frame_index
        piece = {
            "frame_index": frame_index,
            "kind": "inferred_from_overlapping_corridor",
            "left_boundary_id": corridor.get("left_boundary_id"),
            "right_boundary_id": corridor.get("right_boundary_id"),
            "centerline_lcs_m": corridor.get("centerline_lcs_m"),
            "polygon_lcs_m": corridor.get("polygon_lcs_m"),
            "width_m": corridor.get("width_at_ego_m"),
            "overlaps_previous_piece": overlaps_previous,
            "heading_difference_from_previous_deg": None if heading_difference is None else round(heading_difference, 3),
        }
        route["pieces"].append(piece)
        self.previous_corridor = corridor
        return {
            "route_id": self.active_route_id,
            "start_observed_track_id": route.get("start_observed_track_id"),
            "piece_index": len(route["pieces"]) - 1,
            "continuous_with_previous_corridor": continuous,
            "overlaps_previous_corridor": overlaps_previous,
            "continuity_method": "polygon_overlap_and_heading",
        }

    def snapshot(self) -> list[dict[str, Any]]:
        return [self.routes[key] for key in sorted(self.routes)]
