"""Lazy Lanelet2 adapter.

Lanelet2 is intentionally imported only when the POC is enabled. The inferred
map is temporary and contains no authoritative regulatory elements.
"""

from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass
from typing import Any, Iterable

from .models import Boundary, LaneCandidate


class Lanelet2Unavailable(RuntimeError):
    """Raised when an enabled POC requires unavailable Lanelet2 bindings."""


@dataclass
class RoutingContext:
    graph: Any
    lanelets_by_poc_id: dict[str, Any]
    poc_id_by_lanelet_id: dict[int, str]


def available() -> bool:
    try:
        return importlib.util.find_spec("lanelet2") is not None
    except (ImportError, AttributeError):
        return False


def _enum_value(container: Any, name: str, fallback: str) -> Any:
    return getattr(container, name, fallback)


def build_routing_context(
    lanes: Iterable[LaneCandidate],
    config: dict[str, Any],
    boundaries: Iterable[Boundary] = (),
) -> RoutingContext:
    if not available():
        raise Lanelet2Unavailable(
            "Lanelet2 Python bindings are unavailable. Install Lanelet2 and its "
            "Python bindings, or use --allow-geometric-only for diagnostic scoring."
        )
    core = importlib.import_module("lanelet2.core")
    traffic_rules = importlib.import_module("lanelet2.traffic_rules")
    routing = importlib.import_module("lanelet2.routing")
    lanelet_map = core.LaneletMap()
    source_boundaries = {boundary.boundary_id: boundary for boundary in boundaries}
    lanelet_boundaries: dict[str, Any] = {}
    lanelets_by_poc_id: dict[str, Any] = {}
    next_id = 1

    def line(boundary_id: str, points: tuple[tuple[float, float], ...]) -> Any:
        nonlocal next_id
        if boundary_id not in lanelet_boundaries:
            source = source_boundaries.get(boundary_id)
            if source is not None:
                points = source.points
            line_points = []
            for x, y in points:
                line_points.append(core.Point3d(next_id, float(x), float(y), 0.0))
                next_id += 1
            lanelet_boundaries[boundary_id] = core.LineString3d(next_id, line_points)
            next_id += 1
            if source is not None:
                pattern = str(source.attributes.get("pattern") or "unknown").lower()
                lanelet_boundaries[boundary_id].attributes["type"] = (
                    "road_border"
                    if source.source_kind == "drivable_road_boundary"
                    else "line_thin"
                )
                lanelet_boundaries[boundary_id].attributes["subtype"] = pattern
        return lanelet_boundaries[boundary_id]

    for lane in lanes:
        left = line(lane.left_boundary_id, lane.left)
        right = line(lane.right_boundary_id, lane.right)
        lanelet = core.Lanelet(next_id, left, right)
        next_id += 1
        lanelet.attributes["subtype"] = "road"
        lanelet.attributes["location"] = "urban"
        lanelet_map.add(lanelet)
        lanelets_by_poc_id[lane.lane_id] = lanelet

    location = _enum_value(
        traffic_rules.Locations, str(config.get("location", "Germany")), "Germany"
    )
    participant = _enum_value(
        traffic_rules.Participants, str(config.get("participant", "Vehicle")), "Vehicle"
    )
    rules = traffic_rules.create(location, participant)
    graph = routing.RoutingGraph(lanelet_map, rules)
    return RoutingContext(
        graph,
        lanelets_by_poc_id,
        {int(lanelet.id): poc_id for poc_id, lanelet in lanelets_by_poc_id.items()},
    )


def _query(graph: Any, method: str, lanelet: Any) -> Any | None:
    function = getattr(graph, method, None)
    if function is None:
        return None
    try:
        value = function(lanelet)
    except (RuntimeError, ValueError):
        return None
    if value is None:
        return None
    # Some binding versions return Optional-like wrappers.
    if hasattr(value, "get"):
        try:
            value = value.get()
        except (RuntimeError, ValueError):
            return None
    return value


def query_neighbors(context: RoutingContext, ego_lane_id: str) -> dict[str, Any]:
    lanelet = context.lanelets_by_poc_id[ego_lane_id]
    output: dict[str, Any] = {}
    for method in ("left", "right", "adjacentLeft", "adjacentRight"):
        value = _query(context.graph, method, lanelet)
        output[method] = (
            context.poc_id_by_lanelet_id.get(int(value.id)) if value is not None else None
        )
    return output


def geometric_neighbors(
    lanes: Iterable[LaneCandidate], ego_lane_id: str
) -> dict[str, str | None]:
    by_id = {lane.lane_id: lane for lane in lanes}
    ego = by_id[ego_lane_id]
    left = [
        lane for lane in by_id.values()
        if lane.lane_id != ego_lane_id
        and lane.right_boundary_id == ego.left_boundary_id
    ]
    right = [
        lane for lane in by_id.values()
        if lane.lane_id != ego_lane_id
        and lane.left_boundary_id == ego.right_boundary_id
    ]
    left.sort(key=lambda lane: (-lane.pair_score, lane.lane_id))
    right.sort(key=lambda lane: (-lane.pair_score, lane.lane_id))
    return {
        "left": left[0].lane_id if left else None,
        "right": right[0].lane_id if right else None,
    }
