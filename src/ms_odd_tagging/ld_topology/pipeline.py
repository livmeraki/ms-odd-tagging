"""LD intersection topology construction, classification, and per-frame labeling."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

from .config import load_config
from .geometry import (
    acute_angle_delta,
    circle_polygon,
    distance,
    point_in_polygon,
    polyline_distance,
    percentile,
    segment_circle_intersections,
    wrap_degrees,
)
from .models import Arm, Component, LaneGeometry
from .parser import parse_scene


def _lane_endpoint_pairs(lane: LaneGeometry) -> tuple[tuple[float, float], tuple[float, float]]:
    return lane.centerline[0], lane.centerline[-1]


def _connected(a: LaneGeometry, b: LaneGeometry, config: dict[str, Any]) -> bool:
    if {a.left_edge_id, a.right_edge_id} & {b.left_edge_id, b.right_edge_id}:
        return True
    endpoint_tol = float(config["endpoint_connect_tolerance_m"])
    a_endpoints, b_endpoints = _lane_endpoint_pairs(a), _lane_endpoint_pairs(b)
    if min(distance(x, y) for x in a_endpoints for y in b_endpoints) <= endpoint_tol:
        return True
    poly_tol = float(config["polygon_touch_tolerance_m"])
    if min(polyline_distance(p, b.polygon) for p in a.polygon) <= poly_tol:
        return True
    cont_tol = float(config["continuation_endpoint_tolerance_m"])
    heading_tol = float(config["continuation_heading_tolerance_deg"])
    for a0, a1 in ((a.centerline[0], a.centerline[1]), (a.centerline[-1], a.centerline[-2])):
        ha = math.degrees(math.atan2(a1[1] - a0[1], a1[0] - a0[0]))
        for b0, b1 in ((b.centerline[0], b.centerline[1]), (b.centerline[-1], b.centerline[-2])):
            hb = math.degrees(math.atan2(b1[1] - b0[1], b1[0] - b0[0]))
            if distance(a0, b0) <= cont_tol and acute_angle_delta(ha, hb) <= heading_tol:
                return True
    return False


def build_components(lanes: list[LaneGeometry], config: dict[str, Any]) -> tuple[list[Component], list[dict[str, Any]]]:
    strong = [lane for lane in lanes if lane.intersection_evidence == "strong"]
    partial = [lane for lane in lanes if lane.intersection_evidence == "partial"]
    remaining = set(range(len(strong)))
    components: list[Component] = []
    while remaining:
        seed = remaining.pop()
        group = {seed}
        changed = True
        while changed:
            changed = False
            for idx in list(remaining):
                if any(_seed_connected(strong[idx], strong[member], config) for member in group):
                    remaining.remove(idx)
                    group.add(idx)
                    changed = True
        group_lanes = [strong[i] for i in sorted(group)]
        components.append(_make_component(len(components), group_lanes, config, {"seed_lane_count": len(group_lanes), "expanded_partial_lane_ids": []}))

    partial_remaining = {lane.lane_id: lane for lane in partial}
    partial_rejections: dict[str, dict[str, Any]] = {}
    groups: list[tuple[list[LaneGeometry], dict[str, Any]]] = []
    for component in list(components):
        group_lanes = [lane for lane in strong if lane.lane_id in set(component.lane_ids)]
        expanded_ids: list[str] = []
        expansion_reasons: dict[str, list[str]] = {}
        changed = True
        while changed:
            changed = False
            center = _estimate_component_center(group_lanes, config)
            for lane_id, lane in list(partial_remaining.items()):
                reasons = _partial_expansion_reasons(lane, group_lanes, center, config)
                if reasons:
                    group_lanes.append(lane)
                    expanded_ids.append(lane_id)
                    expansion_reasons[lane_id] = reasons
                    del partial_remaining[lane_id]
                    partial_rejections.pop(lane_id, None)
                    changed = True
                else:
                    partial_rejections[lane_id] = _partial_rejection(
                        lane, group_lanes, center, config
                    )
        groups.append(
            (
                group_lanes,
                {
                    "seed_lane_count": len([lane for lane in group_lanes if lane.intersection_evidence == "strong"]),
                    "expanded_partial_lane_ids": expanded_ids,
                    "expanded_partial_reasons": expansion_reasons,
                    "expansion_stage": "strong_seed_then_nearby_partial_before_final_trim",
                    "merged_component_ids": [],
                },
            )
        )

    groups = _merge_expanded_component_groups(groups, config)
    components = [
        _make_component(index, group_lanes, config, diagnostics)
        for index, (group_lanes, diagnostics) in enumerate(groups)
    ]

    uncertain = _uncertain_pieces(list(partial_remaining.values()), config)
    for piece in uncertain:
        piece["rejected_lane_reasons"] = [
            partial_rejections.get(lane_id, {"lane_id": lane_id, "reason": "not_connected_to_any_strong_seed_component"})
            for lane_id in piece["lane_ids"]
        ]
    return components, uncertain


def _merge_expanded_component_groups(
    groups: list[tuple[list[LaneGeometry], dict[str, Any]]],
    config: dict[str, Any],
) -> list[tuple[list[LaneGeometry], dict[str, Any]]]:
    remaining = set(range(len(groups)))
    merged_groups: list[tuple[list[LaneGeometry], dict[str, Any]]] = []
    while remaining:
        seed = remaining.pop()
        member_indices = {seed}
        changed = True
        while changed:
            changed = False
            for idx in list(remaining):
                if any(
                    _component_groups_bridge(groups[idx][0], groups[member][0], config)
                    for member in member_indices
                ):
                    remaining.remove(idx)
                    member_indices.add(idx)
                    changed = True
        lanes_by_id: dict[str, LaneGeometry] = {}
        expanded: list[str] = []
        expanded_reasons: dict[str, list[str]] = {}
        merged_ids: list[str] = []
        seed_count = 0
        for idx in sorted(member_indices):
            for lane in groups[idx][0]:
                lanes_by_id[lane.lane_id] = lane
            diagnostics = groups[idx][1]
            expanded.extend(diagnostics.get("expanded_partial_lane_ids", []))
            expanded_reasons.update(diagnostics.get("expanded_partial_reasons", {}))
            seed_count += int(diagnostics.get("seed_lane_count", 0))
            merged_ids.append(f"pre_merge_component_{idx}")
        merged_groups.append(
            (
                list(lanes_by_id.values()),
                {
                    "seed_lane_count": seed_count,
                    "expanded_partial_lane_ids": sorted(set(expanded)),
                    "expanded_partial_reasons": expanded_reasons,
                    "expansion_stage": "strong_seed_partial_expansion_then_small_gap_component_merge",
                    "merged_component_ids": merged_ids if len(merged_ids) > 1 else [],
                },
            )
        )
    return merged_groups


def _component_groups_bridge(
    first: list[LaneGeometry],
    second: list[LaneGeometry],
    config: dict[str, Any],
) -> bool:
    bridge_gap = float(config["component_bridge_gap_m"])
    if min(_lane_polygon_distance(a, b) for a in first for b in second) <= bridge_gap:
        return True
    if min(distance(x, y) for a in first for b in second for x in _lane_endpoint_pairs(a) for y in _lane_endpoint_pairs(b)) <= bridge_gap:
        return True
    return False


def _seed_connected(a: LaneGeometry, b: LaneGeometry, config: dict[str, Any]) -> bool:
    if {a.left_edge_id, a.right_edge_id} & {b.left_edge_id, b.right_edge_id}:
        return True
    bridge_gap = float(config["component_bridge_gap_m"])
    if min(distance(x, y) for x in _lane_endpoint_pairs(a) for y in _lane_endpoint_pairs(b)) <= bridge_gap:
        return True
    return _lane_polygon_distance(a, b) <= float(config["component_polygon_buffer_m"])


def _partial_expansion_reasons(
    lane: LaneGeometry,
    component_lanes: list[LaneGeometry],
    center: tuple[float, float],
    config: dict[str, Any],
) -> list[str]:
    component_true_edges = {
        edge_id
        for item in component_lanes
        for edge_id, flag in ((item.left_edge_id, item.left_boundary_intersection), (item.right_edge_id, item.right_boundary_intersection))
        if flag
    }
    lane_true_edges = {
        edge_id
        for edge_id, flag in ((lane.left_edge_id, lane.left_boundary_intersection), (lane.right_edge_id, lane.right_boundary_intersection))
        if flag
    }
    reasons = []
    if component_true_edges & lane_true_edges:
        reasons.append("shared_intersection_true_edge")
    if any(_lane_polygon_distance(lane, item) <= float(config["component_polygon_buffer_m"]) for item in component_lanes):
        reasons.append("polygon_overlap_or_touch_after_buffer")
    if min(distance(endpoint, other) for endpoint in _lane_endpoint_pairs(lane) for item in component_lanes for other in _lane_endpoint_pairs(item)) <= float(config["component_endpoint_near_m"]):
        reasons.append("centerline_endpoint_near_component")
    if _continues_toward_center(lane, center, config):
        reasons.append("continues_toward_same_intersection_center")
    return reasons


def _partial_rejection(
    lane: LaneGeometry,
    component_lanes: list[LaneGeometry],
    center: tuple[float, float],
    config: dict[str, Any],
) -> dict[str, Any]:
    component_true_edges = {
        edge_id
        for item in component_lanes
        for edge_id, flag in ((item.left_edge_id, item.left_boundary_intersection), (item.right_edge_id, item.right_boundary_intersection))
        if flag
    }
    lane_true_edges = {
        edge_id
        for edge_id, flag in ((lane.left_edge_id, lane.left_boundary_intersection), (lane.right_edge_id, lane.right_boundary_intersection))
        if flag
    }
    polygon_distance = min(
        (_lane_polygon_distance(lane, item) for item in component_lanes),
        default=math.inf,
    )
    endpoint_distance = min(
        (
            distance(endpoint, other)
            for endpoint in _lane_endpoint_pairs(lane)
            for item in component_lanes
            for other in _lane_endpoint_pairs(item)
        ),
        default=math.inf,
    )
    return {
        "lane_id": lane.lane_id,
        "reason": "partial_lane_failed_component_growth_gates",
        "shared_intersection_true_edge": bool(component_true_edges & lane_true_edges),
        "polygon_distance_m": None if math.isinf(polygon_distance) else round(polygon_distance, 3),
        "endpoint_distance_m": None if math.isinf(endpoint_distance) else round(endpoint_distance, 3),
        "continues_toward_center": _continues_toward_center(lane, center, config),
    }


def _continues_toward_center(
    lane: LaneGeometry,
    center: tuple[float, float],
    config: dict[str, Any],
) -> bool:
    if polyline_distance(center, lane.centerline) > float(config["partial_centerline_center_distance_m"]):
        return False
    for endpoint, index in ((lane.centerline[0], 0), (lane.centerline[-1], len(lane.centerline) - 1)):
        heading = _lane_endpoint_outward_heading(lane, index)
        toward = wrap_degrees(math.degrees(math.atan2(center[1] - endpoint[1], center[0] - endpoint[0])))
        if acute_angle_delta(heading, toward) >= 135.0:
            return True
    return False


def _lane_polygon_distance(a: LaneGeometry, b: LaneGeometry) -> float:
    if any(point_in_polygon(point, b.polygon) for point in a.polygon) or any(point_in_polygon(point, a.polygon) for point in b.polygon):
        return 0.0
    return min(
        min(polyline_distance(point, b.polygon) for point in a.polygon),
        min(polyline_distance(point, a.polygon) for point in b.polygon),
    )


def _uncertain_pieces(lanes: list[LaneGeometry], config: dict[str, Any]) -> list[dict[str, Any]]:
    remaining = set(range(len(lanes)))
    pieces = []
    while remaining:
        seed = remaining.pop()
        group = {seed}
        changed = True
        while changed:
            changed = False
            for idx in list(remaining):
                if any(_seed_connected(lanes[idx], lanes[member], config) for member in group):
                    remaining.remove(idx)
                    group.add(idx)
                    changed = True
        group_lanes = [lanes[i] for i in sorted(group)]
        pieces.append(
            {
                "piece_id": f"uncertain_partial_piece_{len(pieces)}",
                "lane_ids": [lane.lane_id for lane in group_lanes],
                "evidence_counts": {
                    "strong": sum(1 for lane in group_lanes if lane.intersection_evidence == "strong"),
                    "partial": sum(1 for lane in group_lanes if lane.intersection_evidence == "partial"),
                },
                "reason": "partial_evidence_disconnected_from_any_strong_seed_component",
            }
        )
    return pieces


def _make_component(index: int, lanes: list[LaneGeometry], config: dict[str, Any], extra_diagnostics: dict[str, Any] | None = None) -> Component:
    points = [point for lane in lanes for point in lane.centerline]
    center = _estimate_component_center(lanes, config)
    radii = [distance(center, point) for point in points]
    radius = percentile(radii, float(config["core_radius_percentile"]))
    radius = max(float(config["core_radius_min_m"]), min(float(config["core_radius_max_m"]), radius))
    core_polygon, core_method, polygon_valid = _core_polygon(lanes, center, radius, config)
    strong = sum(1 for lane in lanes if lane.intersection_evidence == "strong")
    partial = sum(1 for lane in lanes if lane.intersection_evidence == "partial")
    confidence = min(1.0, 0.25 + 0.12 * strong + 0.07 * partial)
    return Component(
        component_id=f"ld_topology_component_{index}",
        lane_ids=tuple(lane.lane_id for lane in lanes),
        evidence_counts={"strong": strong, "partial": partial, "none": 0},
        center=center,
        core_polygon=core_polygon,
        core_radius_m=radius,
        polygon_valid=polygon_valid,
        confidence=confidence,
        diagnostics={
            "core_method": core_method,
            "lane_count": len(lanes),
            "note": "core is the cleaned union of intersection-supported reconstructed topology lanes; no unconstrained convex hull",
            **(extra_diagnostics or {}),
        },
    )


def _core_polygon(
    lanes: list[LaneGeometry],
    center: tuple[float, float],
    radius: float,
    config: dict[str, Any],
) -> tuple[tuple[tuple[float, float], ...], str, bool]:
    fallback = circle_polygon(center, radius)
    try:
        from shapely.geometry import Point as ShapelyPoint
        from shapely.geometry import Polygon
        from shapely.ops import unary_union
    except ModuleNotFoundError:
        return fallback, "fallback_radial_core_no_shapely", bool(lanes)

    polygons = []
    for lane in lanes:
        if len(lane.polygon) < 3:
            continue
        poly = Polygon(lane.polygon)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if not poly.is_empty and poly.area > 1e-6:
            polygons.append(poly)
    if not polygons:
        return fallback, "fallback_radial_core_no_valid_lane_polygons", False
    union = unary_union(polygons)
    cleanup = float(config.get("topology_union_cleanup_buffer_m", 0.0))
    if cleanup > 0.0:
        union = union.buffer(cleanup).buffer(-cleanup)
    core = union
    max_tail_radius = float(config.get("maximum_topology_tail_radius_m", 0.0))
    if max_tail_radius > 0.0:
        core = core.intersection(ShapelyPoint(center).buffer(max_tail_radius, quad_segs=32))
    if core.is_empty:
        return fallback, "fallback_radial_core_empty_shapely_union", False
    if core.geom_type == "MultiPolygon":
        core = max(core.geoms, key=lambda geom: geom.area)
    if core.geom_type != "Polygon" or core.area <= 1e-6:
        return fallback, f"fallback_radial_core_unsupported_shapely_{core.geom_type}", False
    coords = tuple((float(x), float(y)) for x, y in list(core.exterior.coords)[:-1])
    if len(coords) < 3:
        return fallback, "fallback_radial_core_degenerate_shapely_polygon", False
    return coords, "shapely_cleaned_topology_lane_union_preserves_concavity", True


def _estimate_component_center(lanes: list[LaneGeometry], config: dict[str, Any]) -> tuple[float, float]:
    if not lanes:
        return (0.0, 0.0)
    close: list[tuple[float, float]] = []
    max_dist = float(config["core_radius_max_m"])
    for i, first in enumerate(lanes):
        for second in lanes[i + 1 :]:
            heading_delta = acute_angle_delta(_lane_heading(first), _lane_heading(second))
            if heading_delta < 30.0 or heading_delta > 150.0:
                continue
            intersection = _axis_intersection(first, second)
            if intersection is not None:
                close.append(intersection)
                continue
            best = None
            for a in first.centerline:
                for b in second.centerline:
                    d = distance(a, b)
                    if best is None or d < best[0]:
                        best = (d, ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0))
            if best and best[0] <= max_dist:
                close.append(best[1])
    if close:
        return _mean_point(close)
    points = [point for lane in lanes for point in lane.centerline]
    return _mean_point(points)


def _lane_heading(lane: LaneGeometry) -> float:
    start, end = lane.centerline[0], lane.centerline[-1]
    return wrap_degrees(math.degrees(math.atan2(end[1] - start[1], end[0] - start[0])))


def _axis_intersection(first: LaneGeometry, second: LaneGeometry) -> tuple[float, float] | None:
    a, b = first.centerline[0], first.centerline[-1]
    c, d = second.centerline[0], second.centerline[-1]
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    denom = r[0] * s[1] - r[1] * s[0]
    if abs(denom) <= 1e-9:
        return None
    q = (c[0] - a[0], c[1] - a[1])
    t = (q[0] * s[1] - q[1] * s[0]) / denom
    u = (q[0] * r[1] - q[1] * r[0]) / denom
    if -0.25 <= t <= 1.25 and -0.25 <= u <= 1.25:
        return (a[0] + t * r[0], a[1] + t * r[1])
    return None


def _crossings_for_lane(lane: LaneGeometry, component: Component) -> list[tuple[tuple[float, float], float]]:
    output: list[tuple[tuple[float, float], float]] = []
    polygon = list(component.core_polygon)
    boundary_tol = 1e-5
    for endpoint_index, point in ((0, lane.centerline[0]), (len(lane.centerline) - 1, lane.centerline[-1])):
        if polyline_distance(point, polygon) <= boundary_tol:
            heading = _lane_endpoint_outward_heading(lane, endpoint_index)
            output.append((point, heading))
    for a, b in zip(lane.centerline, lane.centerline[1:]):
        hits = _segment_polygon_intersections(a, b, polygon)
        if not hits:
            hits = segment_circle_intersections(a, b, component.center, component.core_radius_m)
        for point in hits:
            if any(distance(point, existing[0]) <= boundary_tol for existing in output):
                continue
            tangent = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            output.append((point, tangent))
    return output


def _segment_polygon_intersections(
    start: tuple[float, float],
    end: tuple[float, float],
    polygon: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    if len(polygon) < 3:
        return []
    output = []
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        hit = _segment_intersection_point(start, end, a, b)
        if hit is not None and all(distance(hit, existing) > 1e-5 for existing in output):
            output.append(hit)
    return output


def _segment_intersection_point(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> tuple[float, float] | None:
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    denom = r[0] * s[1] - r[1] * s[0]
    if abs(denom) <= 1e-9:
        return None
    q = (c[0] - a[0], c[1] - a[1])
    t = (q[0] * s[1] - q[1] * s[0]) / denom
    u = (q[0] * r[1] - q[1] * r[0]) / denom
    if -1e-9 <= t <= 1.0 + 1e-9 and -1e-9 <= u <= 1.0 + 1e-9:
        return (a[0] + t * r[0], a[1] + t * r[1])
    return None


def extract_arms(lanes: list[LaneGeometry], component: Component, config: dict[str, Any]) -> list[Arm]:
    component_lane_ids = set(component.lane_ids)
    non_intersection_lanes = [
        lane for lane in lanes
        if lane.lane_id not in component_lane_ids and lane.intersection_evidence == "none"
    ]
    corridor_groups, _rejections = _external_corridor_groups(
        non_intersection_lanes, component, config
    )
    raw = [
        _arm_candidate_from_corridor(idx, group, component, config)
        for idx, group in enumerate(corridor_groups)
    ]
    clusters: list[list[dict[str, Any]]] = []
    for item in sorted(raw, key=lambda x: x["angle"]):
        best = None
        best_score = math.inf
        for idx, cluster in enumerate(clusters):
            mean_angle = _mean_angle([v["angle"] for v in cluster])
            mean_point = _mean_point([v["point"] for v in cluster])
            mean_axis = _mean_angle([v["outside_axis_angle"] for v in cluster])
            angle_delta = acute_angle_delta(item["angle"], mean_angle)
            point_delta = distance(item["point"], mean_point)
            axis_delta = min(
                acute_angle_delta(item["outside_axis_angle"], mean_axis),
                abs(180.0 - acute_angle_delta(item["outside_axis_angle"], mean_axis)),
            )
            shared_outside = bool(
                set(item["continuation_lane_ids"])
                & set(lane_id for v in cluster for lane_id in v["continuation_lane_ids"])
            )
            if (
                (
                    angle_delta <= float(config["arm_angle_cluster_deg"])
                    or axis_delta <= float(config["arm_axis_cluster_deg"])
                    or shared_outside
                )
                and point_delta <= float(config["arm_crossing_cluster_distance_m"])
                and angle_delta < 120.0
            ):
                score = angle_delta + axis_delta * 0.5 + point_delta
                if score < best_score:
                    best = idx
                    best_score = score
        if best is None:
            clusters.append([item])
        else:
            clusters[best].append(item)
    arms = []
    for idx, cluster in enumerate(clusters):
        point = _mean_point([v["point"] for v in cluster])
        angle = wrap_degrees(math.degrees(math.atan2(point[1] - component.center[1], point[0] - component.center[0])))
        lane_ids = {lane_id for v in cluster for lane_id in v["lane_ids"]}
        axis_values = [v["outside_axis_angle"] for v in cluster]
        attachment_width = max(
            (distance(a["point"], b["point"]) for a in cluster for b in cluster),
            default=0.0,
        )
        axis_consistency = _axis_consistency(axis_values)
        confidence = min(
            1.0,
            0.35
            + 0.10 * min(3, len(lane_ids))
            + 0.20 * min(1.0, max(v["corridor_length_m"] for v in cluster) / 25.0)
            + 0.20 * axis_consistency
            + 0.15 * min(1.0, max(1.0, attachment_width) / 8.0),
        )
        arms.append(
            Arm(
                arm_id=f"{component.component_id}_arm_{idx}",
                angle_deg=round(angle, 3),
                crossing_point=point,
                lane_ids=tuple(sorted(lane_ids)),
                confidence=confidence,
                continuation_lane_ids=tuple(
                    sorted({lane_id for v in cluster for lane_id in v["continuation_lane_ids"]})
                ),
                outside_axis_angle_deg=round(_mean_axis_angle_mod_180(axis_values), 3),
            )
        )
    arms.sort(key=lambda arm: arm.angle_deg)
    return arms


def _external_corridor_groups(
    non_intersection_lanes: list[LaneGeometry],
    component: Component,
    config: dict[str, Any],
) -> tuple[list[list[LaneGeometry]], list[dict[str, Any]]]:
    rejected = []
    candidate_indices = set()
    for idx, lane in enumerate(non_intersection_lanes):
        reason = _external_lane_rejection_reason(lane, component, config)
        if reason is None:
            candidate_indices.add(idx)
        else:
            rejected.append({"lane_id": lane.lane_id, "reason": reason})

    groups = []
    consumed: set[int] = set()
    for seed in sorted(candidate_indices):
        if seed in consumed:
            continue
        group = {seed}
        consumed.add(seed)
        changed = True
        while changed:
            changed = False
            for idx, lane in enumerate(non_intersection_lanes):
                if idx in group:
                    continue
                if any(
                    _outside_corridor_connected(
                        lane, non_intersection_lanes[member], component, config
                    )
                    for member in group
                ):
                    group.add(idx)
                    if idx in candidate_indices:
                        consumed.add(idx)
                    changed = True
        if group & candidate_indices:
            groups.append([non_intersection_lanes[idx] for idx in sorted(group)])
    return groups, rejected


def _external_lane_rejection_reason(
    lane: LaneGeometry,
    component: Component,
    config: dict[str, Any],
) -> str | None:
    if _lane_fully_inside_polygon(lane, component.core_polygon):
        return "non_intersection_lane_fully_inside_intersection_footprint"
    if not _lane_attaches_to_component(lane, component, config):
        return "non_intersection_lane_not_attached_to_footprint"
    return None


def _lane_fully_inside_polygon(
    lane: LaneGeometry, polygon: tuple[tuple[float, float], ...]
) -> bool:
    if len(polygon) < 3:
        return False
    return all(
        point_in_polygon(point, polygon)
        and polyline_distance(point, polygon) > 1e-5
        for point in lane.centerline
    )


def _lane_attaches_to_component(
    lane: LaneGeometry, component: Component, config: dict[str, Any]
) -> bool:
    tolerance = float(config.get("external_arm_attachment_tolerance_m", 3.0))
    polygon = component.core_polygon
    if len(polygon) < 3:
        return False
    if min(polyline_distance(point, polygon) for point in lane.centerline) <= tolerance:
        return True
    return _lane_polygon_to_component_distance(lane, polygon) <= tolerance


def _lane_polygon_to_component_distance(
    lane: LaneGeometry, polygon: tuple[tuple[float, float], ...]
) -> float:
    return min(
        (polyline_distance(point, polygon) for point in lane.polygon),
        default=math.inf,
    )


def _outside_corridor_connected(
    a: LaneGeometry,
    b: LaneGeometry,
    component: Component,
    config: dict[str, Any],
) -> bool:
    if not _connected(a, b, config):
        if _lane_polygon_distance(a, b) > float(config["parallel_lane_group_distance_m"]):
            return False
    axis_delta = _axis_angle_delta(_lane_heading(a), _lane_heading(b))
    if axis_delta > float(config.get("external_corridor_axis_merge_deg", 25.0)):
        return False
    a_angle = _corridor_attachment_angle(a, component, config)
    b_angle = _corridor_attachment_angle(b, component, config)
    return acute_angle_delta(a_angle, b_angle) <= float(config["arm_angle_cluster_deg"])


def _arm_candidate_from_corridor(
    index: int,
    lanes: list[LaneGeometry],
    component: Component,
    config: dict[str, Any],
) -> dict[str, Any]:
    attachment_points = [
        point
        for lane in lanes
        for point in _attachment_points(lane, component, config)
    ]
    if not attachment_points:
        attachment_points = [
            min(lane.centerline, key=lambda point: polyline_distance(point, component.core_polygon))
            for lane in lanes
        ]
    point = _mean_point(attachment_points)
    angle = wrap_degrees(
        math.degrees(
            math.atan2(point[1] - component.center[1], point[0] - component.center[0])
        )
    )
    axis = _mean_axis_angle_mod_180([_lane_heading(lane) for lane in lanes])
    length = sum(
        distance(a, b)
        for lane in lanes
        for a, b in zip(lane.centerline, lane.centerline[1:])
    )
    lane_ids = tuple(sorted(lane.lane_id for lane in lanes))
    return {
        "corridor_id": f"{component.component_id}_external_corridor_{index}",
        "point": point,
        "angle": angle,
        "lane_ids": lane_ids,
        "continuation_lane_ids": lane_ids,
        "outside_axis_angle": axis,
        "corridor_length_m": length,
    }


def _attachment_points(
    lane: LaneGeometry, component: Component, config: dict[str, Any]
) -> list[tuple[float, float]]:
    tolerance = float(config.get("external_arm_attachment_tolerance_m", 3.0))
    return [
        point
        for point in lane.centerline
        if polyline_distance(point, component.core_polygon) <= tolerance
    ]


def _corridor_attachment_angle(
    lane: LaneGeometry, component: Component, config: dict[str, Any]
) -> float:
    points = _attachment_points(lane, component, config)
    point = _mean_point(points) if points else min(
        lane.centerline, key=lambda p: polyline_distance(p, component.core_polygon)
    )
    return wrap_degrees(math.degrees(math.atan2(point[1] - component.center[1], point[0] - component.center[0])))


def _axis_angle_delta(first: float, second: float) -> float:
    delta = acute_angle_delta(first, second)
    return min(delta, abs(180.0 - delta))


def _mean_axis_angle_mod_180(values: list[float]) -> float:
    doubled = [2.0 * value for value in values]
    return wrap_degrees(_mean_angle(doubled) / 2.0)


def _axis_consistency(values: list[float]) -> float:
    if not values:
        return 0.0
    axis = _mean_axis_angle_mod_180(values)
    max_delta = max(_axis_angle_delta(value, axis) for value in values)
    return max(0.0, 1.0 - max_delta / 90.0)


def _outside_continuation(
    lane: LaneGeometry,
    crossing: tuple[float, float],
    tangent: float,
    component: Component,
    non_intersection_lanes: list[LaneGeometry],
    config: dict[str, Any],
) -> tuple[tuple[str, ...], float] | None:
    outside_endpoint = _outside_endpoint_for_crossing(lane, crossing, component.core_polygon)
    if outside_endpoint is None:
        return None
    endpoint, endpoint_index = outside_endpoint
    continuation_heading = _lane_endpoint_outward_heading(lane, endpoint_index)
    matches = _matching_non_intersection_lanes(endpoint, continuation_heading, non_intersection_lanes, config)
    if not matches:
        return None
    axis = _mean_angle([match[1] for match in matches] + [continuation_heading])
    return tuple(sorted(match[0].lane_id for match in matches)), axis


def _outside_endpoint_for_crossing(
    lane: LaneGeometry,
    crossing: tuple[float, float],
    polygon: tuple[tuple[float, float], ...],
) -> tuple[tuple[float, float], int] | None:
    endpoints = [(lane.centerline[0], 0), (lane.centerline[-1], len(lane.centerline) - 1)]
    outside = [
        (point, index)
        for point, index in endpoints
        if not point_in_polygon(point, polygon) or polyline_distance(point, polygon) <= 1e-5
    ]
    if not outside:
        return None
    return min(outside, key=lambda item: distance(item[0], crossing))


def _lane_endpoint_outward_heading(lane: LaneGeometry, endpoint_index: int) -> float:
    if endpoint_index == 0:
        a, b = lane.centerline[1], lane.centerline[0]
    else:
        a, b = lane.centerline[-2], lane.centerline[-1]
    return wrap_degrees(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])))


def _matching_non_intersection_lanes(
    endpoint: tuple[float, float],
    heading: float,
    non_intersection_lanes: list[LaneGeometry],
    config: dict[str, Any],
) -> list[tuple[LaneGeometry, float, float]]:
    max_distance = float(config["external_continuation_distance_m"])
    max_heading = float(config["external_continuation_heading_deg"])
    matches = []
    for lane in non_intersection_lanes:
        candidates = [
            (lane.centerline[0], _lane_endpoint_outward_heading(lane, 0)),
            (lane.centerline[-1], _lane_endpoint_outward_heading(lane, len(lane.centerline) - 1)),
        ]
        best = None
        for point, lane_heading in candidates:
            dist = distance(endpoint, point)
            heading_delta = min(
                acute_angle_delta(heading, lane_heading),
                abs(180.0 - acute_angle_delta(heading, lane_heading)),
            )
            if dist <= max_distance and heading_delta <= max_heading:
                score = dist + heading_delta * 0.2
                if best is None or score < best[0]:
                    best = (score, lane_heading, dist)
        if best is not None:
            _, lane_heading, dist = best
            matches.append((lane, lane_heading, dist))
    matches.sort(key=lambda item: item[2])
    return matches[: int(config["maximum_external_continuation_matches"])]


def _mean_point(points: list[tuple[float, float]]) -> tuple[float, float]:
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


def _mean_angle(values: list[float]) -> float:
    s = sum(math.sin(math.radians(v)) for v in values)
    c = sum(math.cos(math.radians(v)) for v in values)
    return wrap_degrees(math.degrees(math.atan2(s, c)))


def _opposite_pairs(angles: list[float], threshold: float) -> list[tuple[int, int, float]]:
    pairs = []
    for i, a in enumerate(angles):
        for j, b in enumerate(angles[i + 1 :], start=i + 1):
            delta = acute_angle_delta(a, b)
            if delta >= threshold:
                pairs.append((i, j, round(delta, 3)))
    return pairs


def _opposite_arm_pairs(
    arms: list[Arm], config: dict[str, Any]
) -> list[tuple[int, int, float]]:
    pairs = []
    radial_threshold = float(config["opposite_pair_threshold_deg"])
    axis_threshold = float(config.get("opposite_pair_axis_delta_deg", 22.0))
    minimum_axis_supported_radial = float(
        config.get("opposite_pair_minimum_axis_supported_radial_deg", 120.0)
    )
    for i, first in enumerate(arms):
        for j, second in enumerate(arms[i + 1 :], start=i + 1):
            radial_delta = acute_angle_delta(first.angle_deg, second.angle_deg)
            axis_pair = False
            if (
                first.outside_axis_angle_deg is not None
                and second.outside_axis_angle_deg is not None
            ):
                axis_pair = (
                    _axis_angle_delta(
                        first.outside_axis_angle_deg, second.outside_axis_angle_deg
                    )
                    <= axis_threshold
                    and radial_delta >= minimum_axis_supported_radial
                )
            if radial_delta >= radial_threshold or axis_pair:
                pairs.append((i, j, round(radial_delta, 3)))
    return pairs


def _roundabout_score(lanes: list[LaneGeometry], component: Component, arms: list[Arm], config: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    scores = []
    directions = []
    coverage_angles = []
    for lane in lanes:
        if lane.lane_id not in component.lane_ids:
            continue
        pts = lane.centerline
        if len(pts) < 6:
            continue
        start_end = distance(pts[0], pts[-1])
        length = sum(distance(a, b) for a, b in zip(pts, pts[1:]))
        if start_end > max(6.0, 0.25 * length):
            continue
        tangential = []
        local_dirs = []
        for a, b in zip(pts, pts[1:]):
            mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
            radius_angle = math.degrees(math.atan2(mid[1] - component.center[1], mid[0] - component.center[0]))
            tangent = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            tangential.append(1.0 - abs(acute_angle_delta(tangent, radius_angle) - 90.0) / 90.0)
            local_dirs.append(math.copysign(1.0, (mid[0] - component.center[0]) * (b[1] - a[1]) - (mid[1] - component.center[1]) * (b[0] - a[0])))
            coverage_angles.append(wrap_degrees(radius_angle))
        scores.append(sum(tangential) / len(tangential))
        directions.append(1 if sum(local_dirs) >= 0 else -1)
    coverage = _angular_coverage(coverage_angles)
    direction_consistent = bool(directions) and abs(sum(directions)) == len(directions)
    tangent_score = max(scores) if scores else 0.0
    gates = {
        "closed_or_nearly_closed_loop": bool(scores),
        "tangent_radial_score": round(tangent_score, 3),
        "angular_coverage_deg": round(coverage, 3),
        "consistent_circulation_direction": direction_consistent,
        "external_arm_count": len(arms),
    }
    passed = (
        gates["closed_or_nearly_closed_loop"]
        and tangent_score >= float(config["roundabout_min_tangent_radial_score"])
        and coverage >= float(config["roundabout_min_angular_coverage_deg"])
        and direction_consistent
        and len(arms) >= 3
    )
    return (min(1.0, 0.35 + 0.35 * tangent_score + 0.3 * min(1.0, coverage / 360.0)) if passed else 0.0, gates)


def _angular_coverage(angles: list[float]) -> float:
    if len(angles) < 2:
        return 0.0
    ordered = sorted(wrap_degrees(a) for a in angles)
    gaps = [b - a for a, b in zip(ordered, ordered[1:])]
    gaps.append(ordered[0] + 360.0 - ordered[-1])
    return 360.0 - max(gaps)


def classify_component(lanes: list[LaneGeometry], component: Component, arms: list[Arm], config: dict[str, Any]) -> dict[str, Any]:
    angles = [arm.angle_deg for arm in arms]
    opposite = _opposite_arm_pairs(arms, config)
    circular_score, circular_gates = _roundabout_score(lanes, component, arms, config)
    arm_diagnostics = _external_arm_diagnostics(lanes, component, arms, config)
    ambiguous = None
    strong = int(component.evidence_counts.get("strong", 0))
    partial = int(component.evidence_counts.get("partial", 0))
    intersection_evidence_score = min(1.0, 0.35 * strong + 0.15 * partial)
    component_geometry_confidence = min(
        1.0,
        (0.45 if component.polygon_valid else 0.0)
        + 0.35 * min(1.0, component.confidence)
        + 0.20 * min(1.0, intersection_evidence_score),
    )
    is_intersection_component = (
        component.polygon_valid
        and intersection_evidence_score + 1e-9
        >= float(config.get("minimum_intersection_evidence_score", 0.0))
    )
    label = "intersection_unknown" if is_intersection_component else "normal"
    reason = (
        "intersection-supported geometry exists but subtype is ambiguous"
        if is_intersection_component
        else "intersection presence is not established"
    )
    subtype_confidence = 0.0
    if circular_score > 0.0:
        label, subtype_confidence, reason = "roundabout", circular_score, "roundabout circular-circulation gates passed"
    elif len(arms) == 4 and len(opposite) >= 2:
        label, subtype_confidence, reason = "x-intersection", min(1.0, component.confidence + 0.25), "four reliable physical arms with opposite pairs"
    elif len(arms) == 3 and opposite:
        label, subtype_confidence, reason = "t-intersection", min(1.0, component.confidence + 0.2), "three reliable physical arms with one opposite pair"
    elif len(arms) == 3:
        gaps = sorted(acute_angle_delta(angles[i], angles[(i + 1) % 3]) for i in range(3))
        if min(gaps) >= float(config["minimum_three_way_gap_deg"]):
            label, subtype_confidence, reason = "y-intersection", min(1.0, component.confidence + 0.18), "three separated arms with no T opposite pair"
        else:
            ambiguous = "three_arms_not_sufficiently_separated"
    elif is_intersection_component:
        ambiguous = "intersection_evidence_without_reliable_arm_topology"
    if label not in {"normal", "intersection_unknown"} and subtype_confidence < float(config["minimum_topology_confidence"]):
        ambiguous = f"low_confidence_{label}"
        label = "intersection_unknown" if is_intersection_component else "normal"
        subtype_confidence = 0.0
        reason = "topology subtype confidence below threshold"
    if label == "normal" and not is_intersection_component and component.evidence_counts["strong"] + component.evidence_counts["partial"] > 0:
        ambiguous = "intersection_evidence_without_valid_component_geometry"
    if label != "normal" and not is_intersection_component:
        label = "normal"
        subtype_confidence = 0.0
        reason = "intersection presence is not established"
    if label == "intersection_unknown" and ambiguous is None:
        ambiguous = "subtype_not_classified"
    topology_confidence = (
        subtype_confidence
        if label not in {"normal", "intersection_unknown"}
        else component_geometry_confidence if is_intersection_component else 0.0
    )
    return {
        "topology_class": label,
        "topology_subtype": label,
        "topology_confidence": round(topology_confidence, 4),
        "subtype_confidence": round(subtype_confidence, 4),
        "component_geometry_confidence": round(component_geometry_confidence, 4),
        "intersection_evidence_score": round(intersection_evidence_score, 4),
        "is_intersection_component": is_intersection_component,
        "internal_ambiguous_state": ambiguous,
        "arm_count": len(arms),
        "arm_angles_deg": [round(a, 3) for a in angles],
        "opposite_pairs": opposite,
        "circularity_score": round(circular_score, 4),
        "roundabout_gates": circular_gates,
        "arm_diagnostics": arm_diagnostics,
        "decision_reason": reason,
    }


def _external_arm_diagnostics(
    lanes: list[LaneGeometry],
    component: Component,
    arms: list[Arm],
    config: dict[str, Any],
) -> dict[str, Any]:
    component_lane_ids = set(component.lane_ids)
    non_intersection_lanes = [
        lane for lane in lanes
        if lane.lane_id not in component_lane_ids and lane.intersection_evidence == "none"
    ]
    corridor_groups, rejections = _external_corridor_groups(
        non_intersection_lanes, component, config
    )
    return {
        "arm_source": "external_non_intersection_corridors_attached_to_intersection_footprint",
        "raw_internal_centerline_crossing_count": sum(
            1
            for lane in lanes
            if lane.lane_id in component_lane_ids
            for _ in _crossings_for_lane(lane, component)
        ),
        "raw_centerline_crossing_count": sum(
            1
            for lane in lanes
            if lane.lane_id in component_lane_ids
            for _ in _crossings_for_lane(lane, component)
        ),
        "candidate_external_lane_ids": [lane.lane_id for group in corridor_groups for lane in group],
        "external_corridor_components": [
            {
                "corridor_id": f"{component.component_id}_external_corridor_{index}",
                "lane_ids": [lane.lane_id for lane in group],
                "attachment_angle_deg": round(
                    _corridor_attachment_angle(group[0], component, config), 3
                )
                if group
                else None,
                "axis_angle_deg": round(
                    _mean_axis_angle_mod_180([_lane_heading(lane) for lane in group]), 3
                )
                if group
                else None,
            }
            for index, group in enumerate(corridor_groups)
        ],
        "rejected_external_lanes": rejections,
        "filtered_external_arm_count": len(arms),
        "clustered_external_arm_angles_deg": [round(a.angle_deg, 3) for a in arms],
        "rejected_arm_reason": None if arms else "no_attached_external_non_intersection_corridors",
    }


def classify_scene(recording: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = load_config(overrides=config)
    lanes, parse_meta = parse_scene(recording, config)
    components, uncertain_pieces = build_components(lanes, config)
    by_lane = {lane.lane_id: lane for lane in lanes}
    component_outputs = []
    for component in components:
        arms = extract_arms(lanes, component, config)
        classification = classify_component(lanes, component, arms, config)
        component_outputs.append(
            {
                "component_id": component.component_id,
                "lane_ids": list(component.lane_ids),
                "evidence_counts": component.evidence_counts,
                "center_lcs_m": list(component.center),
                "core_radius_m": round(component.core_radius_m, 3),
                "core_polygon_lcs_m": [list(p) for p in component.core_polygon],
                "polygon_valid": component.polygon_valid,
                "component_confidence": round(component.confidence, 4),
                "is_intersection_component": classification["is_intersection_component"],
                "topology_subtype": classification["topology_subtype"],
                "subtype_confidence": classification["subtype_confidence"],
                "component_geometry_confidence": classification["component_geometry_confidence"],
                "intersection_evidence_score": classification["intersection_evidence_score"],
                "diagnostics": component.diagnostics,
                "arms": [
                    {
                        "arm_id": arm.arm_id,
                        "angle_deg": arm.angle_deg,
                        "crossing_point_lcs_m": [round(arm.crossing_point[0], 3), round(arm.crossing_point[1], 3)],
                        "lane_ids": list(arm.lane_ids),
                        "confidence": round(arm.confidence, 4),
                        "continuation_lane_ids": list(arm.continuation_lane_ids),
                        "outside_axis_angle_deg": arm.outside_axis_angle_deg,
                    }
                    for arm in arms
                ],
                "classification": classification,
            }
        )
    return {
        "recording_id": recording.get("recording_id"),
        "intersection_geometry_source": "lanes.lines[].staticAttributes.intersection via lane boundary references only",
        "parse": parse_meta,
        "lanes": [lane.as_dict() for lane in lanes],
        "components": component_outputs,
        "uncertain_topology_pieces": uncertain_pieces,
    }


def classify_recording(recording: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = load_config(overrides=config)
    scene = classify_scene(recording, config)
    frames = []
    previous_component_id = None
    for frame in recording.get("frames", []):
        ego = frame.get("ego") or {}
        pos = ego.get("position_lcs_m") or []
        point = (float(pos[0]), float(pos[1])) if len(pos) >= 2 else (math.inf, math.inf)
        best = _match_component(point, scene["components"], config, previous_component_id)
        previous_component_id = best["topology_component_id"] if best["ego_inside_topology_polygon"] else None
        frames.append(
            {
                "frame_index": frame.get("frame_index"),
                "timestamp_unix_s": frame.get("timestamp_unix_s"),
                **best,
            }
        )
    return {**scene, "frames": frames}


def _match_component(point: tuple[float, float], components: list[dict[str, Any]], config: dict[str, Any], previous_component_id: str | None) -> dict[str, Any]:
    best = None
    for component in components:
        polygon = tuple((float(p[0]), float(p[1])) for p in component["core_polygon_lcs_m"])
        inside = point_in_polygon(point, polygon)
        dist = 0.0 if inside else polyline_distance(point, polygon)
        tolerance = float(config["entry_tolerance_m"])
        if previous_component_id == component["component_id"]:
            tolerance += float(config["exit_hysteresis_m"])
        if inside or dist <= tolerance:
            if best is None or dist < best[0]:
                best = (dist, inside, component)
    if best is None:
        return _normal_frame(None, False, math.inf, "ego is outside all reliable topology polygons")
    dist, inside, component = best
    cls = component["classification"]
    return {
        "topology_class": cls["topology_class"],
        "topology_subtype": cls["topology_subtype"],
        "topology_confidence": cls["topology_confidence"],
        "topology_component_id": component["component_id"],
        "active_topology_component": component["component_id"],
        "active_is_intersection": cls["is_intersection_component"],
        "active_topology_subtype": cls["topology_subtype"],
        "component_geometry_confidence": cls["component_geometry_confidence"],
        "subtype_confidence": cls["subtype_confidence"],
        "intersection_evidence_score": cls["intersection_evidence_score"],
        "is_intersection_component": cls["is_intersection_component"],
        "intersection_geometry_source": "intersection_true_lane_boundaries",
        "ego_inside_topology_polygon": inside,
        "distance_to_topology_polygon_m": round(dist, 3),
        "arm_count": cls["arm_count"],
        "arm_angles_deg": cls["arm_angles_deg"],
        "opposite_pairs": cls["opposite_pairs"],
        "circularity_score": cls["circularity_score"],
        "internal_ambiguous_state": cls.get("internal_ambiguous_state"),
        "decision_reason": cls["decision_reason"],
    }


def _normal_frame(component_id: str | None, inside: bool, dist: float, reason: str, cls: dict[str, Any] | None = None) -> dict[str, Any]:
    cls = cls or {}
    subtype = cls.get("topology_subtype", "normal")
    is_intersection = bool(cls.get("is_intersection_component", False))
    return {
        "topology_class": subtype if is_intersection else "normal",
        "topology_subtype": subtype if is_intersection else "normal",
        "topology_confidence": cls.get("topology_confidence", 0.0),
        "topology_component_id": component_id,
        "active_topology_component": component_id,
        "active_is_intersection": is_intersection,
        "active_topology_subtype": subtype if is_intersection else "normal",
        "component_geometry_confidence": cls.get("component_geometry_confidence", 0.0),
        "subtype_confidence": cls.get("subtype_confidence", 0.0),
        "intersection_evidence_score": cls.get("intersection_evidence_score", 0.0),
        "is_intersection_component": is_intersection,
        "intersection_geometry_source": "none" if component_id is None else "intersection_true_lane_boundaries",
        "ego_inside_topology_polygon": inside,
        "distance_to_topology_polygon_m": None if math.isinf(dist) else round(dist, 3),
        "arm_count": cls.get("arm_count", 0),
        "arm_angles_deg": cls.get("arm_angles_deg", []),
        "opposite_pairs": cls.get("opposite_pairs", []),
        "circularity_score": cls.get("circularity_score", 0.0),
        "internal_ambiguous_state": cls.get("internal_ambiguous_state"),
        "decision_reason": reason,
    }


def write_frame_csv(result: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "frame_index",
        "timestamp_unix_s",
        "topology_class",
        "topology_subtype",
        "topology_confidence",
        "topology_component_id",
        "active_topology_component",
        "active_is_intersection",
        "active_topology_subtype",
        "component_geometry_confidence",
        "subtype_confidence",
        "intersection_evidence_score",
        "is_intersection_component",
        "intersection_geometry_source",
        "ego_inside_topology_polygon",
        "distance_to_topology_polygon_m",
        "arm_count",
        "arm_angles_deg",
        "opposite_pairs",
        "circularity_score",
        "internal_ambiguous_state",
        "decision_reason",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in result.get("frames", []):
            serialized = dict(row)
            serialized["arm_angles_deg"] = json.dumps(serialized.get("arm_angles_deg", []))
            serialized["opposite_pairs"] = json.dumps(serialized.get("opposite_pairs", []))
            writer.writerow({key: serialized.get(key) for key in fields})
