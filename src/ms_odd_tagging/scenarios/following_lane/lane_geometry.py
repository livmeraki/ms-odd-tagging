"""Lane geometry reconstruction and per-frame lane assignment.

The LD map is static in LCS coordinates. Lane boundary references select an
inclusive range of ordered edge points. The resulting left/right polylines are
resampled to form a centerline and a lane polygon. Invalid boundary ranges are
excluded unless canonicalization explicitly permits a full-edge fallback and
the two physical edges pass direction, overlap, and lane-width validation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, Iterable


def finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def wrap_angle(value: float) -> float:
    return math.atan2(math.sin(value), math.cos(value))


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def point_segment_distance(point, start, end) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    denominator = dx * dx + dy * dy
    if denominator <= 1e-12:
        return distance(point, start)
    ratio = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / denominator))
    return distance(point, (start[0] + ratio * dx, start[1] + ratio * dy))


def polyline_distance(point, points) -> float:
    if not points:
        return math.inf
    if len(points) == 1:
        return distance(point, points[0])
    return min(point_segment_distance(point, a, b) for a, b in zip(points, points[1:]))


def point_in_polygon(point, polygon) -> bool:
    if len(polygon) < 3:
        return False
    inside = False
    x, y = point
    j = len(polygon) - 1
    for i, current in enumerate(polygon):
        previous = polygon[j]
        if ((current[1] > y) != (previous[1] > y)) and (
            x < (previous[0] - current[0]) * (y - current[1]) / (previous[1] - current[1]) + current[0]
        ):
            inside = not inside
        j = i
    return inside


def resample_polyline(points: list[tuple[float, float]], count: int) -> list[tuple[float, float]]:
    if not points:
        return []
    if len(points) == 1 or count <= 1:
        return [points[0]] * max(count, 1)
    cumulative = [0.0]
    for a, b in zip(points, points[1:]):
        cumulative.append(cumulative[-1] + distance(a, b))
    total = cumulative[-1]
    if total <= 1e-9:
        return [points[0]] * count
    result = []
    segment = 0
    for index in range(count):
        if index == count - 1:
            result.append(points[-1])
            continue
        target = total * index / (count - 1)
        while segment + 2 < len(cumulative) and cumulative[segment + 1] < target:
            segment += 1
        start_d, end_d = cumulative[segment], cumulative[segment + 1]
        ratio = 0.0 if end_d == start_d else (target - start_d) / (end_d - start_d)
        a, b = points[segment], points[segment + 1]
        result.append((a[0] + ratio * (b[0] - a[0]), a[1] + ratio * (b[1] - a[1])))
    return result


def nearest_heading(point, centerline) -> float | None:
    if len(centerline) < 2:
        return None
    segments = [
        (point_segment_distance(point, a, b), a, b)
        for a, b in zip(centerline, centerline[1:])
        if distance(a, b) > 1e-9
    ]
    if not segments:
        return None
    _, a, b = min(segments)
    return math.atan2(b[1] - a[1], b[0] - a[0])


@dataclass(frozen=True)
class LaneGeometry:
    lane_id: str
    left_edge_id: str | None
    right_edge_id: str | None
    left: tuple[tuple[float, float], ...]
    right: tuple[tuple[float, float], ...]
    centerline: tuple[tuple[float, float], ...]
    polygon: tuple[tuple[float, float], ...]
    assignment_valid: bool
    invalid_reason: str | None
    left_attributes: dict[str, Any]
    right_attributes: dict[str, Any]
    drivable_status: str
    intersection_connector: bool
    intersection_evidence: tuple[str, ...]
    geometry_recovered: bool = False
    recovery_method: str | None = None
    recovery_evidence: dict[str, Any] | None = None
    curvature_continuations: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "lane_id": self.lane_id,
            "left_edge_id": self.left_edge_id,
            "right_edge_id": self.right_edge_id,
            "left_boundary_lcs_m": [list(point) for point in self.left],
            "right_boundary_lcs_m": [list(point) for point in self.right],
            "centerline_lcs_m": [list(point) for point in self.centerline],
            "polygon_lcs_m": [list(point) for point in self.polygon],
            "assignment_valid": self.assignment_valid,
            "invalid_reason": self.invalid_reason,
            "left_boundary_attributes": self.left_attributes,
            "right_boundary_attributes": self.right_attributes,
            "drivable_status": self.drivable_status,
            "intersection_connector": self.intersection_connector,
            "intersection_evidence": list(self.intersection_evidence),
            "geometry_recovered": self.geometry_recovered,
            "recovery_method": self.recovery_method,
            "recovery_evidence": self.recovery_evidence,
            "curvature_continuations": list(self.curvature_continuations),
        }


def _edge_points(edge: dict[str, Any], point_lookup: dict[str, tuple[float, float]], boundary: dict[str, Any]) -> list[tuple[float, float]]:
    if not boundary or not boundary.get("edge_reference_valid") or not boundary.get("endpoint_order_valid"):
        return []
    elements = edge.get("elements") or []
    order_to_index = {item.get("order"): index for index, item in enumerate(elements)}
    start = order_to_index.get(boundary.get("start_order"))
    end = order_to_index.get(boundary.get("end_order"))
    if start is None or end is None:
        return []
    step = 1 if end >= start else -1
    # A negative slice whose inclusive end is index 0 would use -1 as the
    # exclusive stop and therefore return an empty list. Explicit indices keep
    # both endpoints for forward and reverse LD boundary references.
    selected = [elements[index] for index in range(start, end + step, step)]
    return [point_lookup[str(item["point_id"])] for item in selected if str(item["point_id"]) in point_lookup]


def _full_edge_points(
    edge: dict[str, Any], point_lookup: dict[str, tuple[float, float]]
) -> list[tuple[float, float]]:
    """Return the complete ordered edge for an explicitly marked full-edge fallback."""
    return [
        point_lookup[str(item["point_id"])]
        for item in edge.get("elements") or []
        if str(item.get("point_id")) in point_lookup
    ]


def _endpoint_heading(points: list[tuple[float, float]]) -> float | None:
    if len(points) < 2:
        return None
    for start, end in ((points[0], points[-1]), *zip(points, points[1:])):
        if distance(start, end) > 1e-6:
            return math.atan2(end[1] - start[1], end[0] - start[0])
    return None


def _interpolate_projected_polyline(
    points: list[tuple[float, float]],
    longitudinal_axis: tuple[float, float],
    stations: list[float],
) -> list[tuple[float, float]] | None:
    projected = [
        (point[0] * longitudinal_axis[0] + point[1] * longitudinal_axis[1], point)
        for point in points
    ]
    # Physical LD edges should progress in one direction. Small duplicate or
    # locally noisy stations are harmless; a materially folding edge is not.
    decreases = sum(
        max(0.0, previous[0] - current[0])
        for previous, current in zip(projected, projected[1:])
    )
    span = projected[-1][0] - projected[0][0]
    if span <= 1e-6 or decreases > max(1.0, span * 0.1):
        return None
    ordered: list[tuple[float, tuple[float, float]]] = []
    for station, point in projected:
        if ordered and abs(station - ordered[-1][0]) <= 1e-6:
            ordered[-1] = (station, point)
        else:
            ordered.append((station, point))
    if len(ordered) < 2:
        return None
    output = []
    segment = 0
    for target in stations:
        while segment + 2 < len(ordered) and ordered[segment + 1][0] < target:
            segment += 1
        start_s, start = ordered[segment]
        end_s, end = ordered[segment + 1]
        ratio = 0.0 if end_s == start_s else (target - start_s) / (end_s - start_s)
        output.append(
            (
                start[0] + ratio * (end[0] - start[0]),
                start[1] + ratio * (end[1] - start[1]),
            )
        )
    return output


def _recover_full_edge_pair(
    left: list[tuple[float, float]],
    right: list[tuple[float, float]],
    *,
    maximum_heading_difference_deg: float = 20.0,
    minimum_overlap_m: float = 5.0,
    minimum_lane_width_m: float = 2.0,
    maximum_lane_width_m: float = 6.0,
    maximum_width_range_m: float = 2.5,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]], dict[str, Any]] | None:
    """Align two complete physical edges on their shared longitudinal extent.

    This recovery is deliberately geometric rather than ID- or type-based:
    a solid/dashed LD line and a drivable road boundary may form the two sides
    even when their IDs change. Implausible direction, overlap, or width keeps
    the lane invalid instead of manufacturing a polygon.
    """
    left_heading = _endpoint_heading(left)
    right_heading = _endpoint_heading(right)
    if left_heading is None or right_heading is None:
        return None
    if abs(math.degrees(wrap_angle(left_heading - right_heading))) > 90.0:
        right = list(reversed(right))
        right_heading = wrap_angle(right_heading + math.pi)
    heading_difference = abs(math.degrees(wrap_angle(left_heading - right_heading)))
    if heading_difference > maximum_heading_difference_deg:
        return None
    mean_heading = left_heading + wrap_angle(right_heading - left_heading) / 2.0
    axis = (math.cos(mean_heading), math.sin(mean_heading))
    left_stations = [point[0] * axis[0] + point[1] * axis[1] for point in left]
    right_stations = [point[0] * axis[0] + point[1] * axis[1] for point in right]
    overlap_start = max(min(left_stations), min(right_stations))
    overlap_end = min(max(left_stations), max(right_stations))
    overlap = overlap_end - overlap_start
    if overlap < minimum_overlap_m:
        return None
    count = max(8, min(80, max(len(left), len(right))))
    stations = [
        overlap_start + (overlap_end - overlap_start) * index / (count - 1)
        for index in range(count)
    ]
    left_aligned = _interpolate_projected_polyline(left, axis, stations)
    right_aligned = _interpolate_projected_polyline(right, axis, stations)
    if left_aligned is None or right_aligned is None:
        return None
    widths = [distance(a, b) for a, b in zip(left_aligned, right_aligned)]
    sorted_widths = sorted(widths)
    median_width = sorted_widths[len(sorted_widths) // 2]
    if (
        median_width < minimum_lane_width_m
        or median_width > maximum_lane_width_m
        or max(widths) - min(widths) > maximum_width_range_m
    ):
        return None
    return left_aligned, right_aligned, {
        "heading_difference_deg": round(heading_difference, 2),
        "shared_longitudinal_overlap_m": round(overlap, 3),
        "minimum_lane_width_m": round(min(widths), 3),
        "median_lane_width_m": round(median_width, 3),
        "maximum_lane_width_m": round(max(widths), 3),
    }


def _lane_width_evidence(
    left: list[tuple[float, float]],
    right: list[tuple[float, float]],
    *,
    minimum_lane_width_m: float = 2.0,
    maximum_lane_width_m: float = 6.0,
    maximum_width_range_m: float = 2.5,
) -> tuple[bool, dict[str, Any]]:
    if len(left) < 2 or len(right) < 2:
        return False, {"reason": "insufficient_boundary_points"}
    count = max(8, min(80, max(len(left), len(right))))
    left_r = resample_polyline(left, count)
    right_r = resample_polyline(right, count)
    direct = sum(distance(a, b) for a, b in zip(left_r, right_r))
    reverse = sum(distance(a, b) for a, b in zip(left_r, reversed(right_r)))
    if reverse < direct:
        right_r = list(reversed(right_r))
    widths = [distance(a, b) for a, b in zip(left_r, right_r)]
    sorted_widths = sorted(widths)
    median_width = sorted_widths[len(sorted_widths) // 2]
    evidence = {
        "minimum_lane_width_m": round(min(widths), 3),
        "median_lane_width_m": round(median_width, 3),
        "maximum_lane_width_m": round(max(widths), 3),
        "lane_width_range_m": round(max(widths) - min(widths), 3),
    }
    valid = (
        median_width >= minimum_lane_width_m
        and median_width <= maximum_lane_width_m
        and max(widths) - min(widths) <= maximum_width_range_m
    )
    if not valid:
        evidence["reason"] = "implausible_lane_width"
    return valid, evidence


def _maximum_segment_gap(points: list[tuple[float, float]]) -> float:
    if len(points) < 2:
        return 0.0
    return max(distance(a, b) for a, b in zip(points, points[1:]))


def _projected_span(
    points: list[tuple[float, float]],
    axis: tuple[float, float],
) -> tuple[float, float] | None:
    if not points:
        return None
    stations = [point[0] * axis[0] + point[1] * axis[1] for point in points]
    return min(stations), max(stations)


def _full_edge_expansion_evidence(
    exact_left: list[tuple[float, float]],
    exact_right: list[tuple[float, float]],
    expanded_left: list[tuple[float, float]],
    expanded_right: list[tuple[float, float]],
) -> dict[str, Any]:
    heading = _endpoint_heading(expanded_left)
    if heading is None:
        heading = _endpoint_heading(expanded_right)
    if heading is None:
        return {}
    axis = (math.cos(heading), math.sin(heading))
    exact_left_span = _projected_span(exact_left, axis)
    exact_right_span = _projected_span(exact_right, axis)
    expanded_left_span = _projected_span(expanded_left, axis)
    expanded_right_span = _projected_span(expanded_right, axis)
    evidence: dict[str, Any] = {}
    if exact_left_span and expanded_left_span:
        evidence["left_forward_extension_m"] = round(
            max(0.0, expanded_left_span[1] - exact_left_span[1]), 3
        )
        evidence["left_backward_extension_m"] = round(
            max(0.0, exact_left_span[0] - expanded_left_span[0]), 3
        )
    if exact_right_span and expanded_right_span:
        evidence["right_forward_extension_m"] = round(
            max(0.0, expanded_right_span[1] - exact_right_span[1]), 3
        )
        evidence["right_backward_extension_m"] = round(
            max(0.0, exact_right_span[0] - expanded_right_span[0]), 3
        )
    return evidence


def _lane_median_width(lane: LaneGeometry) -> float | None:
    if len(lane.left) < 2 or len(lane.right) < 2:
        return None
    count = max(8, min(30, max(len(lane.left), len(lane.right))))
    widths = [
        distance(a, b)
        for a, b in zip(
            resample_polyline(list(lane.left), count),
            resample_polyline(list(lane.right), count),
        )
    ]
    if not widths:
        return None
    return sorted(widths)[len(widths) // 2]


def _polyline_curvature(points: tuple[tuple[float, float], ...], *, use_tail: bool) -> float:
    if len(points) < 3:
        return 0.0
    sample = list(points[-5:] if use_tail else points[:5])
    headings = []
    lengths = []
    for a, b in zip(sample, sample[1:]):
        length = distance(a, b)
        if length <= 1e-6:
            continue
        headings.append(math.atan2(b[1] - a[1], b[0] - a[0]))
        lengths.append(length)
    if len(headings) < 2:
        return 0.0
    unwrapped = [headings[0]]
    for heading in headings[1:]:
        unwrapped.append(unwrapped[-1] + wrap_angle(heading - unwrapped[-1]))
    arc = sum(lengths)
    if arc <= 1e-6:
        return 0.0
    return (unwrapped[-1] - unwrapped[0]) / arc


def _project_constant_curvature(
    start: tuple[float, float],
    heading: float,
    curvature: float,
    length_m: float,
    *,
    steps: int = 12,
) -> list[tuple[float, float]]:
    if length_m <= 0:
        return [start]
    count = max(3, min(40, steps))
    points = [start]
    x, y = start
    ds = length_m / (count - 1)
    current_heading = heading
    for _ in range(1, count):
        mid_heading = current_heading + curvature * ds * 0.5
        x += math.cos(mid_heading) * ds
        y += math.sin(mid_heading) * ds
        current_heading += curvature * ds
        points.append((x, y))
    return points


def _curve_heading_at(heading: float, curvature: float, length_m: float) -> float:
    return heading + curvature * max(0.0, length_m)


def _lateral_error_to_heading(
    source_end: tuple[float, float],
    heading: float,
    point: tuple[float, float],
) -> float:
    dx, dy = point[0] - source_end[0], point[1] - source_end[1]
    return abs(-math.sin(heading) * dx + math.cos(heading) * dy)


def _continuation_gap_polygon(
    projected: list[tuple[float, float]],
    width_m: float,
) -> list[tuple[float, float]]:
    if len(projected) < 2:
        return []
    left: list[tuple[float, float]] = []
    right: list[tuple[float, float]] = []
    half_width = width_m / 2.0
    for index, point in enumerate(projected):
        if index + 1 < len(projected):
            next_point = projected[index + 1]
            heading = math.atan2(next_point[1] - point[1], next_point[0] - point[0])
        else:
            previous = projected[index - 1]
            heading = math.atan2(point[1] - previous[1], point[0] - previous[0])
        normal = (-math.sin(heading), math.cos(heading))
        left.append((point[0] + normal[0] * half_width, point[1] + normal[1] * half_width))
        right.append((point[0] - normal[0] * half_width, point[1] - normal[1] * half_width))
    return left + list(reversed(right))


def _curvature_aware_lane_continuations(
    lanes: dict[str, LaneGeometry],
    *,
    maximum_gap_m: float = 15.0,
    maximum_lateral_error_m: float = 1.25,
    maximum_heading_difference_deg: float = 18.0,
    maximum_curvature_difference_per_m: float = 0.08,
    maximum_lane_width_difference_m: float = 0.9,
) -> dict[str, LaneGeometry]:
    updated: dict[str, LaneGeometry] = {}
    valid_lanes = [
        lane
        for lane in lanes.values()
        if lane.assignment_valid
        and not lane.intersection_connector
        and len(lane.centerline) >= 2
    ]
    for source in lanes.values():
        if (
            not source.assignment_valid
            or source.intersection_connector
            or len(source.centerline) < 3
            or len(source.left) < 2
            or len(source.right) < 2
        ):
            updated[source.lane_id] = source
            continue
        source_heading = math.atan2(
            source.centerline[-1][1] - source.centerline[-2][1],
            source.centerline[-1][0] - source.centerline[-2][0],
        )
        source_curvature = _polyline_curvature(source.centerline, use_tail=True)
        source_width = _lane_median_width(source)
        if source_width is None:
            updated[source.lane_id] = source
            continue
        candidates = []
        debug_candidates = []
        for destination in valid_lanes:
            if destination.lane_id == source.lane_id or len(destination.centerline) < 3:
                continue
            dx = destination.centerline[0][0] - source.centerline[-1][0]
            dy = destination.centerline[0][1] - source.centerline[-1][1]
            forward_gap = math.cos(source_heading) * dx + math.sin(source_heading) * dy
            gap = math.hypot(dx, dy)
            if forward_gap <= 0.1 or gap > maximum_gap_m:
                continue
            projected = _project_constant_curvature(
                source.centerline[-1],
                source_heading,
                source_curvature,
                gap,
            )
            projected_end = projected[-1]
            lateral_error = _lateral_error_to_heading(
                source.centerline[-1],
                source_heading,
                destination.centerline[0],
            )
            projection_error = distance(projected_end, destination.centerline[0])
            destination_heading = math.atan2(
                destination.centerline[1][1] - destination.centerline[0][1],
                destination.centerline[1][0] - destination.centerline[0][0],
            )
            expected_heading = _curve_heading_at(source_heading, source_curvature, gap)
            heading_difference = abs(math.degrees(wrap_angle(destination_heading - expected_heading)))
            destination_curvature = _polyline_curvature(destination.centerline, use_tail=False)
            curvature_difference = abs(destination_curvature - source_curvature)
            destination_width = _lane_median_width(destination)
            width_difference = (
                math.inf
                if destination_width is None
                else abs(destination_width - source_width)
            )
            rejection_reasons = []
            if lateral_error > maximum_lateral_error_m:
                rejection_reasons.append("lateral_error")
            if heading_difference > maximum_heading_difference_deg:
                rejection_reasons.append("heading_difference")
            if curvature_difference > maximum_curvature_difference_per_m:
                rejection_reasons.append("curvature_difference")
            if width_difference > maximum_lane_width_difference_m:
                rejection_reasons.append("lane_width_difference")
            if (
                source.left_edge_id == destination.right_edge_id
                or source.right_edge_id == destination.left_edge_id
            ):
                rejection_reasons.append("adjacent_lane_boundary_swap")
            score = (
                gap
                + projection_error * 4.0
                + lateral_error * 3.0
                + heading_difference * 0.08
                + curvature_difference * 15.0
                + width_difference
            )
            record = {
                "candidate_lane_id": destination.lane_id,
                "gap_m": round(gap, 3),
                "lateral_error_m": round(lateral_error, 3),
                "projection_error_m": round(projection_error, 3),
                "heading_difference_deg": round(heading_difference, 2),
                "curvature_difference_per_m": round(curvature_difference, 4),
                "lane_width_difference_m": round(width_difference, 3)
                if math.isfinite(width_difference)
                else None,
                "score": round(score, 3),
                "rejection_reasons": rejection_reasons,
            }
            debug_candidates.append(record)
            if rejection_reasons:
                continue
            candidates.append((score, destination, projected, record))
        if not candidates:
            updated[source.lane_id] = replace(
                source,
                curvature_continuations=(
                    {
                        "source_lane_id": source.lane_id,
                        "observed_segment_end_lcs_m": list(source.centerline[-1]),
                        "source_heading_deg": round(math.degrees(source_heading), 2),
                        "source_curvature_per_m": round(source_curvature, 5),
                        "accepted": False,
                        "candidate_next_segments": debug_candidates[:8],
                    },
                ) if debug_candidates else (),
            )
            continue
        _, destination, projected, accepted_record = min(
            candidates,
            key=lambda item: (item[0], item[1].lane_id),
        )
        gap_polygon = _continuation_gap_polygon(projected, source_width)
        updated[source.lane_id] = replace(
            source,
            curvature_continuations=(
                {
                    "source_lane_id": source.lane_id,
                    "destination_lane_id": destination.lane_id,
                    "confidence": "inferred_gap_reduced_confidence",
                    "method": "curvature_aware_lane_continuation",
                    "observed_segment_end_lcs_m": list(source.centerline[-1]),
                    "projected_centerline_lcs_m": [list(point) for point in projected],
                    "inferred_gap_polygon_lcs_m": [list(point) for point in gap_polygon],
                    "observed_destination_polygon_lcs_m": [
                        list(point) for point in destination.polygon
                    ],
                    "observed_destination_centerline_lcs_m": [
                        list(point) for point in destination.centerline
                    ],
                    "bridged_distance_m": accepted_record["gap_m"],
                    "source_heading_deg": round(math.degrees(source_heading), 2),
                    "source_curvature_per_m": round(source_curvature, 5),
                    "accepted_candidate": accepted_record,
                    "candidate_next_segments": debug_candidates[:8],
                    "observed_vs_inferred": {
                        "source_polygon": "observed_ld",
                        "gap_polygon": "inferred_projection",
                        "destination_polygon": "observed_ld",
                    },
                },
            ),
        )
    for lane_id, lane in lanes.items():
        updated.setdefault(lane_id, lane)
    return updated


def build_lane_geometries(
    recording: dict[str, Any],
    *,
    minimum_recovered_boundary_overlap_m: float = 3.0,
    minimum_full_edge_expansion_m: float = 6.0,
    maximum_full_edge_segment_gap_m: float = 10.0,
    continuation_maximum_gap_m: float = 15.0,
    continuation_maximum_lateral_error_m: float = 1.25,
    continuation_maximum_heading_difference_deg: float = 18.0,
    continuation_maximum_curvature_difference_per_m: float = 0.08,
    continuation_maximum_lane_width_difference_m: float = 0.9,
) -> tuple[dict[str, LaneGeometry], list[dict[str, Any]]]:
    store = recording.get("ld_feature_store") or {}
    point_lookup = {
        str(point["point_id"]): (float(point["position_lcs_m"][0]), float(point["position_lcs_m"][1]))
        for point in store.get("points", [])
        if len(point.get("position_lcs_m") or []) >= 2
    }
    edge_lookup = {
        str(edge[key]): {**edge, "_boundary_source_kind": source_kind}
        for key, collection, source_kind in (
            ("line_id", "lane_lines", "lane_line"),
            ("road_boundary_id", "road_boundaries", "road_boundary"),
        )
        for edge in store.get(collection, [])
    }

    def assignment_boundary_attributes(edge: dict[str, Any] | None) -> dict[str, Any]:
        if not edge:
            return {}
        attributes = dict(edge.get("attributes") or {})
        source_kind = edge.get("_boundary_source_kind", "lane_line")
        attributes["source_kind"] = source_kind
        if source_kind == "road_boundary":
            boundary_attribute = edge.get("boundary_attribute")
            attributes["boundary_attribute"] = boundary_attribute
            if boundary_attribute == "drivable":
                # A drivable LD boundary participates exactly like a regular
                # solid lane line for polygon construction and assignment.
                attributes["drivable"] = True
                attributes.setdefault("pattern", "solid")
                attributes["normalized_as_lane_line"] = True
        return attributes
    topologies = list(store.get("topologies", []))
    topology_intersection_ids = {
        str(item["destination_lane_id"])
        for item in topologies
        if item.get("subclass") == "intersection_in"
    } | {
        str(item["source_lane_id"])
        for item in topologies
        if item.get("subclass") == "intersection_out"
    }
    result: dict[str, LaneGeometry] = {}
    for lane in store.get("lanes", []):
        lane_id = str(lane["lane_id"])
        boundaries = lane.get("boundaries") or {}
        left_ref, right_ref = boundaries.get("left"), boundaries.get("right")
        left_edge = edge_lookup.get(str((left_ref or {}).get("edge_id")))
        right_edge = edge_lookup.get(str((right_ref or {}).get("edge_id")))
        left_attributes = assignment_boundary_attributes(left_edge)
        right_attributes = assignment_boundary_attributes(right_edge)
        intersection_evidence = []
        if left_attributes.get("intersection") is True:
            intersection_evidence.append("left_boundary_attribute")
        if right_attributes.get("intersection") is True:
            intersection_evidence.append("right_boundary_attribute")
        if lane_id in topology_intersection_ids:
            intersection_evidence.append("topology_intersection_connector")
        left = _edge_points(left_edge or {}, point_lookup, left_ref or {})
        right = _edge_points(right_edge or {}, point_lookup, right_ref or {})
        exact_boundary_range_valid = (
            bool(lane.get("validity", {}).get("boundary_ranges_valid"))
            and len(left) >= 2
            and len(right) >= 2
        )
        geometry_recovered = False
        recovery_method = None
        recovery_evidence = None
        recovered_sides = []
        if not exact_boundary_range_valid:
            # Canonicalization explicitly labels stale endpoint-order metadata
            # with geometry_fallback=full_edge. Only physical evidence is
            # recoverable here; virtual lines remain a scored last resort when
            # they have valid ranges, never a source for manufactured geometry.
            recovered_left = left
            recovered_right = right
            if (
                len(recovered_left) < 2
                and (left_ref or {}).get("edge_reference_valid")
                and (left_ref or {}).get("geometry_fallback") == "full_edge"
                and left_attributes.get("pattern") != "virtual"
            ):
                recovered_left = _full_edge_points(left_edge or {}, point_lookup)
                recovered_sides.append("left")
            if (
                len(recovered_right) < 2
                and (right_ref or {}).get("edge_reference_valid")
                and (right_ref or {}).get("geometry_fallback") == "full_edge"
                and right_attributes.get("pattern") != "virtual"
            ):
                recovered_right = _full_edge_points(right_edge or {}, point_lookup)
                recovered_sides.append("right")
            if recovered_sides and len(recovered_left) >= 2 and len(recovered_right) >= 2:
                recovered = _recover_full_edge_pair(
                    recovered_left,
                    recovered_right,
                    minimum_overlap_m=minimum_recovered_boundary_overlap_m,
                )
                if recovered is not None:
                    left, right, recovery_evidence = recovered
                    recovery_evidence["recovered_sides"] = recovered_sides
                    geometry_recovered = True
                    recovery_method = "validated_aligned_full_edge_pair"
        elif (
            not intersection_evidence
            and left_edge is not None
            and right_edge is not None
            and left_attributes.get("pattern") != "virtual"
            and right_attributes.get("pattern") != "virtual"
        ):
            full_left = _full_edge_points(left_edge, point_lookup)
            full_right = _full_edge_points(right_edge, point_lookup)
            if (
                len(full_left) >= len(left)
                and len(full_right) >= len(right)
                and _maximum_segment_gap(full_left) <= maximum_full_edge_segment_gap_m
                and _maximum_segment_gap(full_right) <= maximum_full_edge_segment_gap_m
            ):
                expanded = _recover_full_edge_pair(
                    full_left,
                    full_right,
                    minimum_overlap_m=max(
                        minimum_recovered_boundary_overlap_m,
                        minimum_full_edge_expansion_m,
                    ),
                )
                if expanded is not None:
                    expanded_left, expanded_right, expansion_evidence = expanded
                    expansion_evidence.update(
                        _full_edge_expansion_evidence(
                            left,
                            right,
                            expanded_left,
                            expanded_right,
                        )
                    )
                    forward_extension = max(
                        float(expansion_evidence.get("left_forward_extension_m", 0.0)),
                        float(expansion_evidence.get("right_forward_extension_m", 0.0)),
                    )
                    if forward_extension >= minimum_full_edge_expansion_m:
                        left, right = expanded_left, expanded_right
                        recovery_evidence = expansion_evidence
                        recovery_evidence["recovered_sides"] = ["left", "right"]
                        geometry_recovered = True
                        recovery_method = "validated_full_edge_range_expansion"
        boundary_range_valid = exact_boundary_range_valid or geometry_recovered
        drivable_values = [
            attributes.get("drivable")
            for attributes in (left_attributes, right_attributes)
            if isinstance(attributes.get("drivable"), bool)
        ]
        if False in drivable_values:
            drivable_status = "explicitly_non_drivable"
        elif True in drivable_values:
            drivable_status = "explicitly_drivable"
        else:
            drivable_status = "unknown"
        width_valid = False
        if boundary_range_valid:
            width_valid, _ = _lane_width_evidence(left, right)
        valid = (
            boundary_range_valid
            and width_valid
            and drivable_status != "explicitly_non_drivable"
        )
        reason = (
            None
            if valid
            else "explicit_non_drivable_boundary"
            if boundary_range_valid and width_valid
            else "implausible_lane_width"
            if boundary_range_valid
            else "invalid_or_incomplete_boundary_range"
        )
        centerline: list[tuple[float, float]] = []
        polygon: list[tuple[float, float]] = []
        if valid:
            count = max(8, min(80, max(len(left), len(right))))
            left_r = resample_polyline(left, count)
            right_r = resample_polyline(right, count)
            direct = sum(distance(a, b) for a, b in zip(left_r, right_r))
            reverse = sum(distance(a, b) for a, b in zip(left_r, reversed(right_r)))
            if reverse < direct:
                right = list(reversed(right))
                right_r = list(reversed(right_r))
            centerline = [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in zip(left_r, right_r)]
            polygon = list(left) + list(reversed(right))
        result[lane_id] = LaneGeometry(
            lane_id, str((left_ref or {}).get("edge_id")) if left_ref else None,
            str((right_ref or {}).get("edge_id")) if right_ref else None,
            tuple(left), tuple(right), tuple(centerline), tuple(polygon), valid, reason,
            left_attributes, right_attributes, drivable_status,
            bool(intersection_evidence), tuple(intersection_evidence),
            geometry_recovered, recovery_method, recovery_evidence,
        )
    result = _curvature_aware_lane_continuations(
        result,
        maximum_gap_m=continuation_maximum_gap_m,
        maximum_lateral_error_m=continuation_maximum_lateral_error_m,
        maximum_heading_difference_deg=continuation_maximum_heading_difference_deg,
        maximum_curvature_difference_per_m=(
            continuation_maximum_curvature_difference_per_m
        ),
        maximum_lane_width_difference_m=(
            continuation_maximum_lane_width_difference_m
        ),
    )
    return result, topologies


def assign_point_to_lane(
    point: tuple[float, float], heading: float | None, candidate_ids: Iterable[str], lanes: dict[str, LaneGeometry],
    *, maximum_heading_difference_deg: float = 60.0, outside_lane_tolerance_m: float = 1.0,
    previous_lane_id: str | None = None, successor_ids: set[str] | None = None,
    logical_lane_ids: dict[str, str] | None = None,
    preferred_logical_lane_id: str | None = None,
    same_logical_lane_score_bonus: float = 0.9,
    virtual_only_score_penalty: float = 1.5,
    mixed_virtual_score_penalty: float = 0.35,
    dashed_drivable_boundary_score_bonus: float = 0.75,
    maximum_virtual_lane_curvature_deg: float = 25.0,
) -> dict[str, Any]:
    scored = []
    for lane_id in dict.fromkeys(str(value) for value in candidate_ids):
        lane = lanes.get(lane_id)
        if lane is None or not lane.assignment_valid:
            continue
        boundary_attributes = (lane.left_attributes, lane.right_attributes)
        patterns = [str(attributes.get("pattern") or "unknown") for attributes in boundary_attributes]
        virtual_boundary_count = sum(pattern == "virtual" for pattern in patterns)
        virtual_curvature_deg = lane_centerline_heading_variation_deg(lane)
        if (
            virtual_boundary_count
            and virtual_curvature_deg > maximum_virtual_lane_curvature_deg
        ):
            continue
        lane_heading = nearest_heading(point, lane.centerline)
        heading_difference = 0.0 if heading is None or lane_heading is None else abs(math.degrees(wrap_angle(heading - lane_heading)))
        if heading_difference > maximum_heading_difference_deg:
            continue
        inside = point_in_polygon(point, lane.polygon)
        polygon_distance = 0.0 if inside else polyline_distance(point, list(lane.polygon) + [lane.polygon[0]])
        if not inside and polygon_distance > outside_lane_tolerance_m:
            continue
        center_distance = polyline_distance(point, lane.centerline)
        score = polygon_distance * 10.0 + center_distance + heading_difference * 0.04
        if lane.drivable_status == "explicitly_drivable":
            score -= 0.25
        has_physical_lane_line = any(
            attributes.get("source_kind") == "lane_line"
            and attributes.get("pattern") != "virtual"
            for attributes in boundary_attributes
        )
        has_dashed_lane_line = any(
            attributes.get("source_kind") == "lane_line"
            and attributes.get("pattern") in {"dashed", "broken"}
            for attributes in boundary_attributes
        )
        has_drivable_road_boundary = any(
            attributes.get("source_kind") == "road_boundary"
            and attributes.get("boundary_attribute") == "drivable"
            for attributes in boundary_attributes
        )
        if virtual_boundary_count == 2:
            boundary_reliability = "virtual_only"
            boundary_evidence_adjustment = virtual_only_score_penalty
        elif virtual_boundary_count == 1:
            boundary_reliability = "mixed_virtual"
            boundary_evidence_adjustment = mixed_virtual_score_penalty
        else:
            boundary_reliability = "non_virtual"
            boundary_evidence_adjustment = 0.0
        if has_physical_lane_line and has_drivable_road_boundary:
            boundary_reliability = (
                "dashed_with_drivable_road_boundary"
                if has_dashed_lane_line
                else "physical_line_with_drivable_road_boundary"
            )
            boundary_evidence_adjustment -= dashed_drivable_boundary_score_bonus
        if lane.geometry_recovered:
            # Validated recovery is preferable to virtual geometry, while a
            # small penalty lets an equally good exact physical polygon win.
            boundary_reliability = f"recovered_{boundary_reliability}"
            boundary_evidence_adjustment += 0.2
        score += boundary_evidence_adjustment
        if lane_id == previous_lane_id:
            score -= 0.75
        if successor_ids and lane_id in successor_ids:
            score -= 0.45
        if (
            preferred_logical_lane_id
            and logical_lane_ids
            and logical_lane_ids.get(lane_id) == preferred_logical_lane_id
        ):
            score -= same_logical_lane_score_bonus
        scored.append(
            (
                score,
                lane_id,
                inside,
                center_distance,
                polygon_distance,
                heading_difference,
                boundary_reliability,
                virtual_boundary_count,
                virtual_curvature_deg,
                boundary_evidence_adjustment,
            )
        )
    scored.sort()
    if not scored:
        return {"lane_id": None, "confidence": "unknown", "method": "no_valid_geometric_candidate", "candidates": []}
    best = scored[0]
    margin = scored[1][0] - best[0] if len(scored) > 1 else None
    confidence = "high" if best[2] and (margin is None or margin >= 1.0) else "medium" if best[2] else "low"
    if best[6] == "virtual_only" and confidence == "high":
        confidence = "medium"
    chosen_lane = lanes[best[1]]
    if chosen_lane.geometry_recovered and confidence == "high":
        confidence = "medium"
    boundary_options = [
        (polyline_distance(point, chosen_lane.left), "left", chosen_lane.left_attributes),
        (polyline_distance(point, chosen_lane.right), "right", chosen_lane.right_attributes),
    ]
    nearest_boundary_distance, nearest_boundary_side, nearest_boundary_attributes = min(
        boundary_options, key=lambda item: item[0]
    )
    return {
        "lane_id": best[1], "confidence": confidence,
        "method": (
            "recovered_physical_boundary_polygon_and_heading"
            if chosen_lane.geometry_recovered
            else "polygon_and_heading"
        ),
        "inside_polygon": best[2], "center_distance_m": round(best[3], 3),
        "polygon_distance_m": round(best[4], 3), "heading_difference_deg": round(best[5], 2),
        "boundary_reliability": best[6],
        "virtual_boundary_count": best[7],
        "virtual_lane_curvature_deg": round(best[8], 2),
        "boundary_evidence_score_adjustment": round(best[9], 3),
        "drivable_status": lanes[best[1]].drivable_status,
        "nearest_boundary_side": nearest_boundary_side,
        "nearest_boundary_distance_m": round(nearest_boundary_distance, 3),
        "nearest_boundary_source_kind": nearest_boundary_attributes.get("source_kind"),
        "nearest_boundary_attribute": nearest_boundary_attributes.get("boundary_attribute"),
        "nearest_boundary_normalized_as_lane_line": bool(
            nearest_boundary_attributes.get("normalized_as_lane_line")
        ),
        "geometry_recovered": chosen_lane.geometry_recovered,
        "recovery_method": chosen_lane.recovery_method,
        "recovery_evidence": chosen_lane.recovery_evidence,
        "runner_up_score_margin": round(margin, 3) if margin is not None else None,
        "candidates": [
            {
                "lane_id": item[1],
                "score": round(item[0], 3),
                "inside_polygon": item[2],
                "boundary_reliability": item[6],
                "virtual_lane_curvature_deg": round(item[8], 2),
            }
            for item in scored[:4]
        ],
    }


def lane_centerline_heading_variation_deg(lane: LaneGeometry) -> float:
    """Return maximum unwrapped segment-heading deviation from the first segment."""
    if len(lane.centerline) < 3:
        return 0.0
    headings = [
        math.atan2(b[1] - a[1], b[0] - a[0])
        for a, b in zip(lane.centerline, lane.centerline[1:])
        if distance(a, b) > 1e-6
    ]
    if len(headings) < 2:
        return 0.0
    unwrapped = [headings[0]]
    for current in headings[1:]:
        unwrapped.append(unwrapped[-1] + wrap_angle(current - unwrapped[-1]))
    return math.degrees(max(unwrapped) - min(unwrapped))


def adjacent_lanes(
    ego_lane_id: str,
    point: tuple[float, float],
    heading: float,
    candidate_ids: Iterable[str],
    lanes: dict[str, LaneGeometry],
    *,
    maximum_virtual_lane_curvature_deg: float = 25.0,
    maximum_same_direction_heading_difference_deg: float = 20.0,
) -> dict[str, Any]:
    """Find locally parallel left/right lanes relative to the ego lane.

    A nearby or shared-boundary lane is not necessarily an adjacent travel
    lane: roundabout connectors, crossing lanes, and oncoming lanes can occupy
    the same local area. Candidate direction therefore uses the local
    centerline tangent at the ego position and must agree with the ego lane's
    local tangent before the candidate can receive a left/right role.
    """
    current = lanes[ego_lane_id]
    output = {"left": {"lane_id": None, "method": "not_found"}, "right": {"lane_id": None, "method": "not_found"}}
    candidates = [
        lanes[lane_id]
        for lane_id in dict.fromkeys(str(v) for v in candidate_ids)
        if lane_id in lanes
        and lane_id != ego_lane_id
        and lanes[lane_id].assignment_valid
        and not (
            any(
                attributes.get("pattern") == "virtual"
                for attributes in (
                    lanes[lane_id].left_attributes,
                    lanes[lane_id].right_attributes,
                )
            )
            and lane_centerline_heading_variation_deg(lanes[lane_id])
            > maximum_virtual_lane_curvature_deg
        )
    ]
    ego_lane_heading = nearest_heading(point, current.centerline)
    if ego_lane_heading is None:
        ego_lane_heading = heading
    cosine, sine = math.cos(heading), math.sin(heading)
    records = []
    for lane in candidates:
        nearest = min(lane.centerline, key=lambda value: distance(point, value))
        dx, dy = nearest[0] - point[0], nearest[1] - point[1]
        longitudinal = cosine * dx + sine * dy
        lateral = -sine * dx + cosine * dy
        side = "left" if lateral > 0 else "right"
        candidate_heading = nearest_heading(point, lane.centerline)
        heading_difference = (
            math.inf
            if candidate_heading is None or ego_lane_heading is None
            else abs(math.degrees(wrap_angle(candidate_heading - ego_lane_heading)))
        )
        if heading_difference <= maximum_same_direction_heading_difference_deg:
            direction_relation = "same_direction"
        elif heading_difference >= 180.0 - maximum_same_direction_heading_difference_deg:
            direction_relation = "opposite_direction"
        else:
            direction_relation = "crossing_or_diverging"
        records.append(
            {
                "lane": lane,
                "side": side,
                "longitudinal": longitudinal,
                "lateral": lateral,
                "heading_difference_deg": heading_difference,
                "candidate_heading": candidate_heading,
                "direction_relation": direction_relation,
                "same_direction": direction_relation == "same_direction",
                "distance": polyline_distance(point, lane.centerline),
            }
        )

    def assignment(record: dict[str, Any], method: str, confidence: str) -> dict[str, Any]:
        return {
            "lane_id": record["lane"].lane_id,
            "method": method,
            "confidence": confidence,
            "lateral_offset_m": round(record["lateral"], 3),
            "same_direction_as_ego": True,
            "direction_relation": "same_direction",
            "heading_difference_deg": round(record["heading_difference_deg"], 2),
            "ego_lane_heading_deg": round(math.degrees(ego_lane_heading), 2),
            "candidate_lane_heading_deg": round(
                math.degrees(record["candidate_heading"]), 2
            ),
        }

    exact_by_side = {
        "left": [
            record
            for record in records
            if current.left_edge_id
            and record["lane"].right_edge_id == current.left_edge_id
        ],
        "right": [
            record
            for record in records
            if current.right_edge_id
            and record["lane"].left_edge_id == current.right_edge_id
        ],
    }
    for side in ("left", "right"):
        exact = [record for record in exact_by_side[side] if record["same_direction"]]
        if exact:
            chosen = min(exact, key=lambda record: record["distance"])
            output[side] = assignment(chosen, "shared_boundary", "high")

    spatial_by_side = {
        side: [
            record
            for record in records
            if record["side"] == side
            and abs(record["longitudinal"]) <= 12.0
            and 1.5 <= abs(record["lateral"]) <= 8.0
        ]
        for side in ("left", "right")
    }
    for side in ("left", "right"):
        if output[side]["lane_id"] is not None:
            continue
        eligible = [
            record for record in spatial_by_side[side] if record["same_direction"]
        ]
        if eligible:
            chosen = min(
                eligible,
                key=lambda record: (
                    abs(record["lateral"]),
                    abs(record["longitudinal"]),
                    record["distance"],
                    record["lane"].lane_id,
                ),
            )
            output[side] = assignment(chosen, "geometric_fallback", "medium")
            continue
        rejected = [
            record
            for record in exact_by_side[side] + spatial_by_side[side]
            if not record["same_direction"]
        ]
        if rejected:
            chosen = min(
                rejected,
                key=lambda record: (
                    record["distance"],
                    record["heading_difference_deg"],
                    record["lane"].lane_id,
                ),
            )
            output[side] = {
                "lane_id": None,
                "method": "direction_mismatch_rejected",
                "confidence": "rejected",
                "rejected_lane_id": chosen["lane"].lane_id,
                "same_direction_as_ego": False,
                "direction_relation": chosen["direction_relation"],
                "heading_difference_deg": round(
                    chosen["heading_difference_deg"], 2
                ),
                "maximum_same_direction_heading_difference_deg": (
                    maximum_same_direction_heading_difference_deg
                ),
            }
    return output


def build_logical_lane_groups(
    lanes: dict[str, LaneGeometry],
    topologies: list[dict[str, Any]],
    *,
    maximum_geometric_gap_m: float = 1.0,
    maximum_topology_gap_m: float = 12.0,
    maximum_heading_difference_deg: float = 35.0,
) -> dict[str, str]:
    """Merge directed, one-to-one LD continuations into logical lanes.

    Lane boundary order defines travel direction, so continuation is evaluated
    only from a source centerline's end to a destination centerline's start.
    Explicit branch/merge relations are deliberately not unioned here: the
    driven branch is resolved later from the observed ego path.  This prevents
    neighboring left/right lanes from acquiring the same logical ID.
    """
    valid = {lane_id: lane for lane_id, lane in lanes.items() if lane.assignment_valid and len(lane.centerline) >= 2}
    def directed_score(source: LaneGeometry, destination: LaneGeometry) -> float | None:
        source_heading = math.atan2(
            source.centerline[-1][1] - source.centerline[-2][1],
            source.centerline[-1][0] - source.centerline[-2][0],
        )
        destination_heading = math.atan2(
            destination.centerline[1][1] - destination.centerline[0][1],
            destination.centerline[1][0] - destination.centerline[0][0],
        )
        heading_difference = abs(math.degrees(wrap_angle(source_heading - destination_heading)))
        if heading_difference > maximum_heading_difference_deg:
            return None
        return distance(source.centerline[-1], destination.centerline[0]) + math.radians(heading_difference) * 2.0

    outgoing: dict[str, list[tuple[float, str]]] = {}
    incoming: dict[str, list[tuple[float, str]]] = {}
    topology_pairs = set()
    for item in topologies:
        source_id, destination_id = str(item.get("source_lane_id")), str(item.get("destination_lane_id"))
        if (
            source_id not in valid or destination_id not in valid
            or not item.get("validity", {}).get("lane_references_resolve", True)
            or item.get("subclass") in {"branch", "merge"}
        ):
            continue
        score = directed_score(valid[source_id], valid[destination_id])
        if score is None or score > maximum_topology_gap_m + math.radians(maximum_heading_difference_deg) * 2.0:
            continue
        topology_pairs.add((source_id, destination_id))
        outgoing.setdefault(source_id, []).append((score, destination_id))
        incoming.setdefault(destination_id, []).append((score, source_id))

    # A strict geometric fallback handles missing topology without joining
    # parallel lanes whose endpoints merely happen to be nearby.
    lane_items = list(valid.items())
    for source_id, source in lane_items:
        for destination_id, destination in lane_items:
            if source_id == destination_id or (source_id, destination_id) in topology_pairs:
                continue
            score = directed_score(source, destination)
            if score is None or distance(source.centerline[-1], destination.centerline[0]) > maximum_geometric_gap_m:
                continue
            outgoing.setdefault(source_id, []).append((score + 1.0, destination_id))
            incoming.setdefault(destination_id, []).append((score + 1.0, source_id))

    best_outgoing = {lane_id: min(items, key=lambda item: (item[0], item[1]))[1] for lane_id, items in outgoing.items()}
    best_incoming = {lane_id: min(items, key=lambda item: (item[0], item[1]))[1] for lane_id, items in incoming.items()}
    parent = {lane_id: lane_id for lane_id in lanes}

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(a: str, b: str) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[max(root_a, root_b)] = min(root_a, root_b)

    for source_id, destination_id in best_outgoing.items():
        if best_incoming.get(destination_id) == source_id:
            union(source_id, destination_id)
    roots = {lane_id: find(lane_id) for lane_id in lanes}
    ordered_roots = {root: index + 1 for index, root in enumerate(sorted(set(roots.values()), key=lambda value: (not value.isdigit(), int(value) if value.isdigit() else value)))}
    return {lane_id: f"logical_lane_{ordered_roots[root]:04d}" for lane_id, root in roots.items()}


def refine_groups_from_observed_ego_path(
    lanes: dict[str, LaneGeometry],
    topologies: list[dict[str, Any]],
    base_groups: dict[str, str],
    ego_lane_frames: list[tuple[int, str | None]],
    *,
    maximum_frame_gap: int = 80,
    maximum_topology_hops: int = 6,
    maximum_direction_difference_deg: float = 25.0,
    maximum_upstream_topology_gap_m: float = 25.0,
) -> dict[str, str]:
    """Keep one recording-local lane ID along the direction actually driven.

    Static maps must preserve branches, but the observed ego path resolves which
    branch was taken. Connected, direction-compatible physical IDs along that
    path are therefore unified even when invalid geometry temporarily leaves a
    gap at an intersection.
    """
    parent = {lane_id: lane_id for lane_id in lanes}

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(a: str, b: str) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[max(root_a, root_b)] = min(root_a, root_b)

    by_group: dict[str, list[str]] = {}
    for lane_id, group_id in base_groups.items():
        by_group.setdefault(group_id, []).append(lane_id)
    for members in by_group.values():
        for lane_id in members[1:]:
            union(members[0], lane_id)

    graph: dict[str, set[str]] = {}
    reverse_graph: dict[str, set[str]] = {}
    for item in topologies:
        if not item.get("validity", {}).get("lane_references_resolve", True):
            continue
        source_id, destination_id = str(item.get("source_lane_id")), str(item.get("destination_lane_id"))
        graph.setdefault(source_id, set()).add(destination_id)
        reverse_graph.setdefault(destination_id, set()).add(source_id)

    def connected(a: str, b: str) -> bool:
        if a == b:
            return True
        frontier, seen = [(a, 0)], {a}
        while frontier:
            current, depth = frontier.pop(0)
            if depth >= maximum_topology_hops:
                continue
            for neighbor in graph.get(current, ()):
                if neighbor == b:
                    return True
                if neighbor not in seen:
                    seen.add(neighbor)
                    frontier.append((neighbor, depth + 1))
        return False

    def direction(lane: LaneGeometry) -> float | None:
        if len(lane.centerline) < 2:
            return None
        return math.atan2(
            lane.centerline[-1][1] - lane.centerline[0][1],
            lane.centerline[-1][0] - lane.centerline[0][0],
        )

    previous: tuple[int, str] | None = None
    first_observed_lane_id = None
    for frame_index, lane_id in ego_lane_frames:
        if lane_id is None or lane_id not in lanes:
            continue
        if first_observed_lane_id is None:
            first_observed_lane_id = lane_id
        if previous and lane_id != previous[1] and frame_index - previous[0] <= maximum_frame_gap:
            previous_lane = lanes[previous[1]]
            current_lane = lanes[lane_id]
            previous_direction, current_direction = direction(previous_lane), direction(current_lane)
            direction_ok = (
                previous_direction is not None
                and current_direction is not None
                and abs(math.degrees(wrap_angle(previous_direction - current_direction))) <= maximum_direction_difference_deg
            )
            direct_gap = (
                distance(previous_lane.centerline[-1], current_lane.centerline[0])
                if previous_lane.centerline and current_lane.centerline
                else math.inf
            )
            if direction_ok and (connected(previous[1], lane_id) or direct_gap <= 12.0):
                union(previous[1], lane_id)
        previous = (frame_index, lane_id)

    # The recording can begin inside an unmapped gap, so its first exact lane
    # may have valid upstream topology that was never directly observed. Walk
    # backward along the single best direction-compatible predecessor chain.
    # At a split this follows only the branch leading to the observed lane; it
    # never unions sibling destinations merely because they share a source.
    current_id = first_observed_lane_id
    visited = {current_id} if current_id else set()
    for _ in range(maximum_topology_hops):
        if current_id is None or current_id not in lanes:
            break
        current_lane = lanes[current_id]
        current_start_direction = (
            math.atan2(
                current_lane.centerline[1][1] - current_lane.centerline[0][1],
                current_lane.centerline[1][0] - current_lane.centerline[0][0],
            )
            if len(current_lane.centerline) >= 2
            else None
        )
        candidates = []
        for predecessor_id in reverse_graph.get(current_id, ()):
            predecessor = lanes.get(predecessor_id)
            if (
                predecessor is None
                or not predecessor.assignment_valid
                or predecessor_id in visited
                or not predecessor.centerline
                or not current_lane.centerline
            ):
                continue
            predecessor_end_direction = (
                math.atan2(
                    predecessor.centerline[-1][1] - predecessor.centerline[-2][1],
                    predecessor.centerline[-1][0] - predecessor.centerline[-2][0],
                )
                if len(predecessor.centerline) >= 2
                else None
            )
            if predecessor_end_direction is None or current_start_direction is None:
                continue
            direction_difference = abs(
                math.degrees(
                    wrap_angle(predecessor_end_direction - current_start_direction)
                )
            )
            endpoint_gap = distance(
                predecessor.centerline[-1], current_lane.centerline[0]
            )
            if (
                direction_difference <= maximum_direction_difference_deg
                and endpoint_gap <= maximum_upstream_topology_gap_m
            ):
                candidates.append(
                    (
                        endpoint_gap + math.radians(direction_difference) * 2.0,
                        predecessor_id,
                    )
                )
        if not candidates:
            break
        _, predecessor_id = min(candidates)
        union(predecessor_id, current_id)
        visited.add(predecessor_id)
        current_id = predecessor_id

    roots = {lane_id: find(lane_id) for lane_id in lanes}
    ordered = {
        root: index + 1
        for index, root in enumerate(
            sorted(set(roots.values()), key=lambda value: (not value.isdigit(), int(value) if value.isdigit() else value))
        )
    }
    return {lane_id: f"route_lane_{ordered[root]:04d}" for lane_id, root in roots.items()}


def assign_point_to_probable_route(
    point: tuple[float, float],
    heading: float | None,
    route_lane_id: str,
    lanes: dict[str, LaneGeometry],
    logical_lane_ids: dict[str, str],
    *,
    maximum_extension_m: float = 60.0,
    lateral_padding_m: float = 0.75,
    maximum_heading_difference_deg: float = 35.0,
) -> dict[str, Any] | None:
    """Assign a point to a lower-confidence corridor extrapolated from LD.

    The corridor uses the recorded lane width and direction. It covers the
    centerline tube plus bounded rays beyond each endpoint; it never changes
    the route ID or treats the extrapolation as exact polygon evidence.
    """
    candidates = []
    for lane_id, lane in lanes.items():
        if logical_lane_ids.get(lane_id) != route_lane_id or not lane.assignment_valid or len(lane.centerline) < 2:
            continue
        sample_count = 8
        left = resample_polyline(list(lane.left), sample_count)
        right = resample_polyline(list(lane.right), sample_count)
        widths = [distance(a, b) for a, b in zip(left, right)]
        width = sorted(widths)[len(widths) // 2] if widths else 3.5
        half_width = max(1.25, min(4.0, width / 2.0))
        allowed_lateral = half_width + lateral_padding_m

        lane_heading = nearest_heading(point, lane.centerline)
        heading_difference = (
            0.0
            if heading is None or lane_heading is None
            else abs(math.degrees(wrap_angle(heading - lane_heading)))
        )
        if heading_difference > maximum_heading_difference_deg:
            continue
        center_distance = polyline_distance(point, lane.centerline)
        if center_distance <= allowed_lateral:
            candidates.append(
                (
                    center_distance + heading_difference * 0.03,
                    lane_id,
                    "probable_route_centerline_tube",
                    center_distance,
                    0.0,
                    width,
                    heading_difference,
                )
            )

        for endpoint_name, endpoint, neighbor, direction_sign in (
            ("after_end", lane.centerline[-1], lane.centerline[-2], 1.0),
            ("before_start", lane.centerline[0], lane.centerline[1], 1.0),
        ):
            dx, dy = endpoint[0] - neighbor[0], endpoint[1] - neighbor[1]
            norm = math.hypot(dx, dy)
            if norm <= 1e-9:
                continue
            dx, dy = dx / norm, dy / norm
            relative_x, relative_y = point[0] - endpoint[0], point[1] - endpoint[1]
            extension = (relative_x * dx + relative_y * dy) * direction_sign
            lateral = abs(-dy * relative_x + dx * relative_y)
            if 0.0 <= extension <= maximum_extension_m and lateral <= allowed_lateral:
                candidates.append(
                    (
                        lateral + extension * 0.03 + heading_difference * 0.03,
                        lane_id,
                        f"probable_route_endpoint_extension_{endpoint_name}",
                        lateral,
                        extension,
                        width,
                        heading_difference,
                    )
                )
    if not candidates:
        return None
    best = min(candidates, key=lambda item: (item[0], item[1]))
    return {
        "lane_id": best[1],
        "logical_lane_id": route_lane_id,
        "confidence": "probable",
        "method": best[2],
        "inside_polygon": False,
        "center_distance_m": round(best[3], 3),
        "extension_distance_m": round(best[4], 3),
        "estimated_lane_width_m": round(best[5], 3),
        "heading_difference_deg": round(best[6], 2),
        "drivable_status": lanes[best[1]].drivable_status,
        "probable_area": True,
    }


def split_adjacent_roles(
    ego_lane_id: str,
    point: tuple[float, float],
    lanes: dict[str, LaneGeometry],
    topologies: list[dict[str, Any]],
    logical_lane_ids: dict[str, str],
    *,
    maximum_split_distance_m: float = 40.0,
) -> dict[str, dict[str, Any]]:
    """Classify non-driven branches as left/right from signed directionality."""
    relations: dict[str, list[dict[str, Any]]] = {}
    for item in topologies:
        if item.get("subclass") not in {"branch", "type_transition"}:
            continue
        relations.setdefault(str(item.get("source_lane_id")), []).append(item)
    source_ids = [ego_lane_id]
    source_ids.extend(
        source_id
        for source_id, items in relations.items()
        if any(str(item.get("destination_lane_id")) == ego_lane_id for item in items)
    )
    result: dict[str, dict[str, Any]] = {}
    ego_group = logical_lane_ids.get(ego_lane_id)
    for source_id in dict.fromkeys(source_ids):
        source = lanes.get(source_id)
        outgoing = relations.get(source_id, [])
        if source is None or len(source.centerline) < 2 or len(outgoing) < 2:
            continue
        if distance(point, source.centerline[-1]) > maximum_split_distance_m:
            continue
        source_heading = math.atan2(
            source.centerline[-1][1] - source.centerline[-2][1],
            source.centerline[-1][0] - source.centerline[-2][0],
        )
        for item in outgoing:
            destination_id = str(item.get("destination_lane_id"))
            destination = lanes.get(destination_id)
            if (
                destination_id == ego_lane_id
                or logical_lane_ids.get(destination_id) == ego_group
                or destination is None
                or len(destination.centerline) < 2
            ):
                continue
            lookahead = destination.centerline[min(3, len(destination.centerline) - 1)]
            dx, dy = lookahead[0] - source.centerline[-1][0], lookahead[1] - source.centerline[-1][1]
            lateral = -math.sin(source_heading) * dx + math.cos(source_heading) * dy
            if abs(lateral) < 0.35:
                destination_heading = math.atan2(
                    destination.centerline[1][1] - destination.centerline[0][1],
                    destination.centerline[1][0] - destination.centerline[0][0],
                )
                lateral = math.degrees(wrap_angle(destination_heading - source_heading))
            side = "left" if lateral > 0 else "right"
            candidate = {
                "lane_id": destination_id,
                "logical_lane_id": logical_lane_ids.get(destination_id),
                "confidence": "high",
                "method": "topology_split_signed_direction",
                "split_source_lane_id": source_id,
                "signed_split_lateral_m": round(lateral, 3),
                "intersection_connector": destination.intersection_connector,
                "drivable_status": destination.drivable_status,
            }
            existing = result.get(side)
            if existing is None or abs(candidate["signed_split_lateral_m"]) < abs(existing["signed_split_lateral_m"]):
                result[side] = candidate
    return result


def build_probable_route_bridges(
    lanes: dict[str, LaneGeometry],
    logical_lane_ids: dict[str, str],
    *,
    maximum_gap_m: float = 65.0,
    maximum_heading_difference_deg: float = 25.0,
) -> list[dict[str, Any]]:
    """Create lane-aligned quadrilaterals that visibly close route polygon gaps."""
    bridges = []
    grouped: dict[str, list[LaneGeometry]] = {}
    for lane_id, lane in lanes.items():
        if lane.assignment_valid and lane.centerline:
            grouped.setdefault(logical_lane_ids[lane_id], []).append(lane)
    for route_id, members in grouped.items():
        for source in members:
            source_heading = math.atan2(
                source.centerline[-1][1] - source.centerline[-2][1],
                source.centerline[-1][0] - source.centerline[-2][0],
            )
            candidates = []
            for destination in members:
                if source.lane_id == destination.lane_id:
                    continue
                dx = destination.centerline[0][0] - source.centerline[-1][0]
                dy = destination.centerline[0][1] - source.centerline[-1][1]
                forward = math.cos(source_heading) * dx + math.sin(source_heading) * dy
                gap = math.hypot(dx, dy)
                if forward <= 0.1 or gap > maximum_gap_m:
                    continue
                destination_heading = math.atan2(
                    destination.centerline[1][1] - destination.centerline[0][1],
                    destination.centerline[1][0] - destination.centerline[0][0],
                )
                heading_difference = abs(math.degrees(wrap_angle(destination_heading - source_heading)))
                if heading_difference > maximum_heading_difference_deg:
                    continue
                candidates.append((gap + heading_difference * 0.1, gap, destination))
            if not candidates:
                continue
            _, gap, destination = min(candidates, key=lambda item: (item[0], item[2].lane_id))
            polygon = [source.left[-1], destination.left[0], destination.right[0], source.right[-1]]
            if len({(round(x, 4), round(y, 4)) for x, y in polygon}) < 3:
                continue
            bridges.append(
                {
                    "logical_lane_id": route_id,
                    "source_lane_id": source.lane_id,
                    "destination_lane_id": destination.lane_id,
                    "gap_m": round(gap, 3),
                    "confidence": "probable",
                    "method": "directed_lane_boundary_bridge",
                    "polygon_lcs_m": [list(point) for point in polygon],
                }
            )
    return bridges


def assign_point_to_probable_bridge(
    point: tuple[float, float],
    heading: float | None,
    bridges: list[dict[str, Any]],
    lanes: dict[str, LaneGeometry],
    *,
    preferred_logical_lane_id: str | None = None,
    maximum_heading_difference_deg: float = 35.0,
) -> dict[str, Any] | None:
    """Assign a point only when it is inside a validated directed route bridge.

    Temporal continuity may select a preferred route, but it never creates the
    assignment: polygon containment and local bridge direction are mandatory.
    """
    candidates = []
    for bridge in bridges:
        if (
            preferred_logical_lane_id
            and bridge.get("logical_lane_id") != preferred_logical_lane_id
        ):
            continue
        polygon = [tuple(value) for value in bridge.get("polygon_lcs_m") or []]
        if not point_in_polygon(point, polygon):
            continue
        source = lanes.get(str(bridge.get("source_lane_id")))
        destination = lanes.get(str(bridge.get("destination_lane_id")))
        if (
            source is None
            or destination is None
            or not source.centerline
            or not destination.centerline
        ):
            continue
        source_endpoint = source.centerline[-1]
        destination_endpoint = destination.centerline[0]
        bridge_heading = math.atan2(
            destination_endpoint[1] - source_endpoint[1],
            destination_endpoint[0] - source_endpoint[0],
        )
        heading_difference = (
            0.0
            if heading is None
            else abs(math.degrees(wrap_angle(heading - bridge_heading)))
        )
        if heading_difference > maximum_heading_difference_deg:
            continue
        center_distance = point_segment_distance(
            point, source_endpoint, destination_endpoint
        )
        assigned_lane = (
            source
            if distance(point, source_endpoint)
            <= distance(point, destination_endpoint)
            else destination
        )
        candidates.append(
            (
                center_distance + heading_difference * 0.04,
                assigned_lane,
                bridge,
                center_distance,
                heading_difference,
            )
        )
    if not candidates:
        return None
    _, lane, bridge, center_distance, heading_difference = min(
        candidates, key=lambda item: (item[0], item[1].lane_id)
    )
    return {
        "lane_id": lane.lane_id,
        "logical_lane_id": bridge["logical_lane_id"],
        "confidence": "probable",
        "method": "inside_directed_lane_boundary_bridge",
        "inside_polygon": False,
        "inside_probable_bridge": True,
        "center_distance_m": round(center_distance, 3),
        "heading_difference_deg": round(heading_difference, 2),
        "drivable_status": lane.drivable_status,
        "intersection_connector": lane.intersection_connector,
        "probable_bridge_source_lane_id": bridge["source_lane_id"],
        "probable_bridge_destination_lane_id": bridge["destination_lane_id"],
        "route_constraint": (
            "geometry_with_temporal_route_tiebreak"
            if preferred_logical_lane_id
            else "geometry_only"
        ),
        "candidates": [],
    }
