"""Canonical ODLD parsing and lane reconstruction."""

from __future__ import annotations

import math
from typing import Any

from .geometry import finite_number, polygon_area, polygon_self_intersects, polyline_length, resample_polyline, distance
from .models import Edge, LaneGeometry, Point


def _ordered_point_ids(feature: dict[str, Any]) -> list[str]:
    elements = feature.get("elements") or []
    if elements:
        return [str(item["point_id"]) for item in sorted(elements, key=lambda item: item.get("order", 0))]
    return [str(point_id) for point_id in feature.get("point_ids", [])]


def _edge_order_map(feature: dict[str, Any]) -> dict[Any, int]:
    elements = feature.get("elements") or []
    if elements:
        return {item.get("order"): index for index, item in enumerate(sorted(elements, key=lambda item: item.get("order", 0)))}
    return {index + 1: index for index, _ in enumerate(feature.get("point_ids", []))}


def parse_scene(recording: dict[str, Any], config: dict[str, Any]) -> tuple[list[LaneGeometry], dict[str, Any]]:
    store = recording.get("ld_feature_store") or {}
    point_index: dict[str, Point] = {}
    for point in store.get("points", []):
        coords = point.get("position_lcs_m") or []
        if len(coords) >= 2 and finite_number(coords[0]) and finite_number(coords[1]):
            point_index[str(point.get("point_id"))] = (float(coords[0]), float(coords[1]))

    edge_features: dict[str, dict[str, Any]] = {}
    edges: dict[str, Edge] = {}
    for feature in store.get("lane_lines", []):
        edge_id = str(feature.get("line_id"))
        edge_features[edge_id] = feature
        points = tuple(point_index[pid] for pid in _ordered_point_ids(feature) if pid in point_index)
        edges[edge_id] = Edge(edge_id, "line", points, dict(feature.get("attributes") or {}))
    for feature in store.get("road_boundaries", []):
        edge_id = str(feature.get("road_boundary_id"))
        edge_features[edge_id] = feature
        points = tuple(point_index[pid] for pid in _ordered_point_ids(feature) if pid in point_index)
        attrs = dict(feature.get("attributes") or {})
        if "boundary_attribute" in feature:
            attrs["boundary_attribute"] = feature.get("boundary_attribute")
        edges[edge_id] = Edge(edge_id, "road_boundary", points, attrs)

    lanes, rejected = [], []
    for raw_lane in store.get("lanes", []):
        lane_id = str(raw_lane.get("lane_id"))
        try:
            lane = _build_lane(lane_id, raw_lane, edge_features, edges, config)
        except ValueError as exc:
            rejected.append({"lane_id": lane_id, "stage": "lane_reconstruction", "reasons": [str(exc)]})
            continue
        if lane.validation["valid"]:
            lanes.append(lane)
        else:
            rejected.append({"lane_id": lane_id, "stage": "lane_validation", "reasons": lane.validation["reasons"], "metrics": lane.validation.get("metrics", {})})
    return lanes, {
        "point_count": len(point_index),
        "line_count": len(store.get("lane_lines", [])),
        "road_boundary_count": len(store.get("road_boundaries", [])),
        "source_lane_count": len(store.get("lanes", [])),
        "valid_lane_count": len(lanes),
        "rejected_lanes": rejected,
    }


def _range_points(feature: dict[str, Any], edge: Edge, reference: dict[str, Any]) -> tuple[tuple[Point, ...], dict[str, Any]]:
    order_map = _edge_order_map(feature)
    start_order = reference.get("start_order")
    end_order = reference.get("end_order")
    if start_order not in order_map or end_order not in order_map:
        raise ValueError("invalid_boundary_point_order")
    start, end = order_map[start_order], order_map[end_order]
    step = 1 if end >= start else -1
    if step > 0:
        selected = edge.points[start : end + 1]
    else:
        selected = tuple(reversed(edge.points[end : start + 1]))
    return selected, {
        "edge_id": edge.edge_id,
        "start_order": start_order,
        "end_order": end_order,
        "reversed_range": step < 0,
        "source_kind": edge.source_kind,
        "intersection": edge.intersection,
    }


def _build_lane(
    lane_id: str,
    raw_lane: dict[str, Any],
    edge_features: dict[str, dict[str, Any]],
    edges: dict[str, Edge],
    config: dict[str, Any],
) -> LaneGeometry:
    refs = raw_lane.get("boundaries") or {}
    left_ref, right_ref = refs.get("left") or {}, refs.get("right") or {}
    left_edge = edges.get(str(left_ref.get("edge_id")))
    right_edge = edges.get(str(right_ref.get("edge_id")))
    if left_edge is None or right_edge is None:
        raise ValueError("missing_boundary_edge_reference")
    left, left_meta = _range_points(edge_features[left_edge.edge_id], left_edge, left_ref)
    right, right_meta = _range_points(edge_features[right_edge.edge_id], right_edge, right_ref)
    count = max(4, int(config["resample_count"]))
    left_r = resample_polyline(left, count)
    right_r = resample_polyline(right, count)
    if len(left_r) != count or len(right_r) != count:
        raise ValueError("boundary_resampling_failed")
    widths = [distance(a, b) for a, b in zip(left_r, right_r)]
    centerline = tuple(((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0) for a, b in zip(left_r, right_r))
    polygon = tuple(left_r + tuple(reversed(right_r)))
    reasons = []
    if polyline_length(centerline) < float(config["minimum_lane_length_m"]):
        reasons.append("lane_too_short")
    if any(distance(a, b) > float(config["maximum_boundary_gap_m"]) for a, b in zip(left, left[1:])):
        reasons.append("left_boundary_discontinuous")
    if any(distance(a, b) > float(config["maximum_boundary_gap_m"]) for a, b in zip(right, right[1:])):
        reasons.append("right_boundary_discontinuous")
    left_i, right_i = left_edge.intersection, right_edge.intersection
    has_intersection_evidence = left_i or right_i
    maximum_width = float(
        config[
            "maximum_intersection_lane_width_m"
            if has_intersection_evidence
            else "maximum_lane_width_m"
        ]
    )
    maximum_width_range = float(
        config[
            "maximum_intersection_lane_width_range_m"
            if has_intersection_evidence
            else "maximum_lane_width_range_m"
        ]
    )
    if min(widths, default=0.0) < float(config["minimum_lane_width_m"]):
        reasons.append("lane_too_narrow")
    if max(widths, default=math.inf) > maximum_width:
        reasons.append("lane_too_wide")
    if widths and max(widths) - min(widths) > maximum_width_range:
        reasons.append("lane_width_unstable")
    if polygon_area(polygon) <= 1e-6:
        reasons.append("lane_polygon_zero_area")
    if polygon_self_intersects(polygon):
        reasons.append("lane_polygon_self_intersects")
    evidence = "strong" if left_i and right_i else "partial" if left_i or right_i else "none"
    return LaneGeometry(
        lane_id=lane_id,
        left_edge_id=left_edge.edge_id,
        right_edge_id=right_edge.edge_id,
        left_source_kind=left_edge.source_kind,
        right_source_kind=right_edge.source_kind,
        left_boundary=left_r,
        right_boundary=right_r,
        centerline=centerline,
        polygon=polygon,
        left_boundary_intersection=left_i,
        right_boundary_intersection=right_i,
        intersection_evidence=evidence,
        validation={
            "valid": not reasons,
            "reasons": reasons,
            "metrics": {
                "centerline_length_m": round(polyline_length(centerline), 3),
                "minimum_width_m": round(min(widths), 3) if widths else None,
                "maximum_width_m": round(max(widths), 3) if widths else None,
                "width_range_m": round(max(widths) - min(widths), 3) if widths else None,
                "maximum_allowed_width_m": round(maximum_width, 3),
                "maximum_allowed_width_range_m": round(maximum_width_range, 3),
            },
        },
        geometry_source={"left": left_meta, "right": right_meta},
    )
