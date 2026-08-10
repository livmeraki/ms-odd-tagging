"""Temporal continuity for boundary-inferred ego corridors.

Consecutive inferred corridors are grouped into persistent ego-route episodes.
The route is ego-specific evidence; it never globally merges physical lane
tracks. Observed tracks immediately before/after an inferred episode are stored
as bridge endpoints.
"""
from __future__ import annotations

import math
from typing import Any

from .lane_geometry import nearest_heading, polyline_distance, wrap_angle


def _endpoint_distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    ca = a.get("centerline_lcs_m") or []
    cb = b.get("centerline_lcs_m") or []
    if not ca or not cb:
        return math.inf
    candidates = []
    for pa in (ca[0], ca[-1]):
        for pb in (cb[0], cb[-1]):
            candidates.append(math.hypot(float(pa[0])-float(pb[0]), float(pa[1])-float(pb[1])))
    return min(candidates)


def corridors_are_continuous(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    *,
    maximum_endpoint_gap_m: float = 5.0,
    maximum_heading_difference_deg: float = 25.0,
) -> bool:
    if not previous or not previous.get("valid") or not current.get("valid"):
        return False
    if (
        previous.get("left_boundary_id") == current.get("left_boundary_id")
        and previous.get("right_boundary_id") == current.get("right_boundary_id")
    ):
        return True
    prev_center = previous.get("centerline_lcs_m") or []
    curr_center = current.get("centerline_lcs_m") or []
    if len(prev_center) < 2 or len(curr_center) < 2:
        return False
    gap = _endpoint_distance(previous, current)
    if gap > maximum_endpoint_gap_m:
        # Overlapping local corridors may have endpoints far apart while the lines
        # themselves overlap; use centerline-to-centerline distance as a fallback.
        gap = min(polyline_distance(tuple(p[:2]), curr_center) for p in prev_center)
        if gap > maximum_endpoint_gap_m:
            return False
    prev_h = nearest_heading(tuple(prev_center[len(prev_center)//2][:2]), prev_center)
    curr_h = nearest_heading(tuple(curr_center[len(curr_center)//2][:2]), curr_center)
    if prev_h is None or curr_h is None:
        return True
    diff = abs(math.degrees(wrap_angle(curr_h-prev_h)))
    return diff <= maximum_heading_difference_deg


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
                "pieces": [],
            }
        route = self.routes[self.active_route_id]
        route["end_frame_index"] = frame_index
        piece = {
            "frame_index": frame_index,
            "kind": "inferred_from_boundaries",
            "left_boundary_id": corridor.get("left_boundary_id"),
            "right_boundary_id": corridor.get("right_boundary_id"),
            "centerline_lcs_m": corridor.get("centerline_lcs_m"),
            "polygon_lcs_m": corridor.get("polygon_lcs_m"),
            "width_m": corridor.get("width_at_ego_m"),
        }
        route["pieces"].append(piece)
        self.previous_corridor = corridor
        return {
            "route_id": self.active_route_id,
            "start_observed_track_id": route.get("start_observed_track_id"),
            "piece_index": len(route["pieces"]) - 1,
            "continuous_with_previous_corridor": continuous,
        }

    def snapshot(self) -> list[dict[str, Any]]:
        return [self.routes[key] for key in sorted(self.routes)]
