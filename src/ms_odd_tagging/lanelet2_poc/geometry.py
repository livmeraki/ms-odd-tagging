"""Boundary pairing and ego matching without assuming valid source topology."""

from __future__ import annotations

import hashlib
import math
from itertools import combinations
from typing import Any, Iterable

from .models import Boundary, LaneCandidate, Point


def finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def wrap_angle(value: float) -> float:
    return math.atan2(math.sin(value), math.cos(value))


def distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def polyline_length(points: Iterable[Point]) -> float:
    values = list(points)
    return sum(distance(a, b) for a, b in zip(values, values[1:]))


def point_segment_distance(point: Point, start: Point, end: Point) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    denominator = dx * dx + dy * dy
    if denominator <= 1e-12:
        return distance(point, start)
    ratio = max(
        0.0,
        min(
            1.0,
            ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy)
            / denominator,
        ),
    )
    return distance(point, (start[0] + ratio * dx, start[1] + ratio * dy))


def polyline_distance(point: Point, points: Iterable[Point]) -> float:
    values = list(points)
    if not values:
        return math.inf
    if len(values) == 1:
        return distance(point, values[0])
    return min(point_segment_distance(point, a, b) for a, b in zip(values, values[1:]))


def point_in_polygon(point: Point, polygon: Iterable[Point]) -> bool:
    values = list(polygon)
    if len(values) < 3:
        return False
    x, y = point
    inside = False
    previous = values[-1]
    for current in values:
        if ((current[1] > y) != (previous[1] > y)) and (
            x
            < (previous[0] - current[0])
            * (y - current[1])
            / (previous[1] - current[1])
            + current[0]
        ):
            inside = not inside
        previous = current
    return inside


def nearest_heading(point: Point, points: Iterable[Point]) -> float | None:
    values = list(points)
    usable = [
        (point_segment_distance(point, a, b), a, b)
        for a, b in zip(values, values[1:])
        if distance(a, b) > 1e-6
    ]
    if not usable:
        return None
    _, start, end = min(usable)
    return math.atan2(end[1] - start[1], end[0] - start[0])


def ego_coordinates(point: Point, ego: tuple[float, float, float]) -> Point:
    dx, dy = point[0] - ego[0], point[1] - ego[1]
    cosine, sine = math.cos(ego[2]), math.sin(ego[2])
    return cosine * dx + sine * dy, -sine * dx + cosine * dy


def _oriented(boundary: Boundary, yaw: float) -> Boundary:
    points = boundary.points
    if len(points) >= 2:
        heading = math.atan2(points[-1][1] - points[0][1], points[-1][0] - points[0][0])
        if abs(wrap_angle(heading - yaw)) > math.pi / 2:
            points = tuple(reversed(points))
    return Boundary(boundary.boundary_id, points, boundary.source_kind, boundary.attributes)


def _projected_samples(
    boundary: Boundary,
    ego: tuple[float, float, float],
) -> list[tuple[float, float, Point]]:
    return [(*ego_coordinates(point, ego), point) for point in boundary.points]


def _interpolate(
    projected: list[tuple[float, float, Point]], stations: list[float]
) -> list[Point] | None:
    ordered = sorted(projected, key=lambda item: item[0])
    compact: list[tuple[float, float, Point]] = []
    for item in ordered:
        if compact and abs(item[0] - compact[-1][0]) < 1e-5:
            compact[-1] = item
        else:
            compact.append(item)
    if len(compact) < 2:
        return None
    output = []
    segment = 0
    for station in stations:
        while segment + 2 < len(compact) and compact[segment + 1][0] < station:
            segment += 1
        a, b = compact[segment], compact[segment + 1]
        ratio = 0.0 if b[0] == a[0] else (station - a[0]) / (b[0] - a[0])
        output.append(
            (
                a[2][0] + ratio * (b[2][0] - a[2][0]),
                a[2][1] + ratio * (b[2][1] - a[2][1]),
            )
        )
    return output


def filter_local_boundaries(
    boundaries: Iterable[Boundary],
    ego: tuple[float, float, float],
    config: dict[str, Any],
) -> tuple[list[Boundary], list[dict[str, Any]]]:
    accepted, rejected = [], []
    for raw in boundaries:
        points = tuple(
            (float(point[0]), float(point[1]))
            for point in raw.points
            if len(point) >= 2 and finite(point[0]) and finite(point[1])
        )
        candidate = _oriented(
            Boundary(raw.boundary_id, points, raw.source_kind, raw.attributes), ego[2]
        )
        reasons = []
        if len(candidate.points) < 2:
            reasons.append("fewer_than_two_finite_points")
        if polyline_length(candidate.points) < config["minimum_boundary_length_m"]:
            reasons.append("boundary_too_short")
        if any(
            distance(a, b) > config["maximum_boundary_segment_gap_m"]
            for a, b in zip(candidate.points, candidate.points[1:])
        ):
            reasons.append("boundary_discontinuity")
        local = [ego_coordinates(point, ego) for point in candidate.points]
        if local and not any(
            -config["local_backward_m"] <= point[0] <= config["local_forward_m"]
            and abs(point[1]) <= config["local_lateral_m"]
            for point in local
        ):
            reasons.append("outside_local_window")
        if reasons:
            rejected.append({"boundary_id": raw.boundary_id, "reasons": reasons})
        else:
            accepted.append(candidate)
    return accepted, rejected


def _lane_id(left_id: str, right_id: str) -> str:
    digest = hashlib.sha1(f"{left_id}|{right_id}".encode("utf-8")).hexdigest()[:12]
    return f"poc_lane_{digest}"


def pair_boundaries(
    boundaries: Iterable[Boundary],
    ego: tuple[float, float, float],
    config: dict[str, Any],
) -> tuple[list[LaneCandidate], list[dict[str, Any]]]:
    lanes, rejected = [], []
    count = max(6, int(config["resample_count"]))
    for first, second in combinations(boundaries, 2):
        first_projected = _projected_samples(first, ego)
        second_projected = _projected_samples(second, ego)
        reasons = []
        overlap_start = max(min(p[0] for p in first_projected), min(p[0] for p in second_projected))
        overlap_end = min(max(p[0] for p in first_projected), max(p[0] for p in second_projected))
        overlap = overlap_end - overlap_start
        first_heading = nearest_heading((ego[0], ego[1]), first.points)
        second_heading = nearest_heading((ego[0], ego[1]), second.points)
        heading_difference = (
            math.inf
            if first_heading is None or second_heading is None
            else abs(math.degrees(wrap_angle(first_heading - second_heading)))
        )
        if overlap < config["minimum_longitudinal_overlap_m"]:
            reasons.append("insufficient_longitudinal_overlap")
        if heading_difference > config["maximum_pair_heading_difference_deg"]:
            reasons.append("heading_mismatch")
        if reasons:
            rejected.append(
                {
                    "boundary_ids": [first.boundary_id, second.boundary_id],
                    "reasons": reasons,
                    "metrics": {
                        "longitudinal_overlap_m": round(overlap, 3),
                        "heading_difference_deg": round(heading_difference, 3),
                    },
                }
            )
            continue
        stations = [
            overlap_start + (overlap_end - overlap_start) * index / (count - 1)
            for index in range(count)
        ]
        first_points = _interpolate(first_projected, stations)
        second_points = _interpolate(second_projected, stations)
        if first_points is None or second_points is None:
            rejected.append(
                {
                    "boundary_ids": [first.boundary_id, second.boundary_id],
                    "reasons": ["resampling_failed"],
                }
            )
            continue
        first_lateral = sum(ego_coordinates(point, ego)[1] for point in first_points) / count
        second_lateral = sum(ego_coordinates(point, ego)[1] for point in second_points) / count
        if first_lateral >= second_lateral:
            left_boundary, right_boundary = first, second
            left, right = first_points, second_points
        else:
            left_boundary, right_boundary = second, first
            left, right = second_points, first_points
        signed_widths = [
            ego_coordinates(a, ego)[1] - ego_coordinates(b, ego)[1]
            for a, b in zip(left, right)
        ]
        widths = [distance(a, b) for a, b in zip(left, right)]
        median_width = sorted(widths)[len(widths) // 2]
        width_range = max(widths) - min(widths)
        reasons = []
        if min(signed_widths) <= 0:
            reasons.append("boundaries_cross_or_swap_sides")
        if median_width < config["minimum_lane_width_m"]:
            reasons.append("lane_too_narrow")
        if median_width > config["maximum_lane_width_m"]:
            reasons.append("lane_too_wide")
        if width_range > config["maximum_lane_width_range_m"]:
            reasons.append("unstable_lane_width")
        width_center = (
            config["minimum_lane_width_m"] + config["maximum_lane_width_m"]
        ) / 2
        width_half_range = (
            config["maximum_lane_width_m"] - config["minimum_lane_width_m"]
        ) / 2
        # Hard constraints above establish plausibility. These bounded soft
        # factors rank valid pairs without eliminating short recorded fragments
        # a second time merely because they are not near an ideal value.
        score = 0.5 + 0.5 * max(
            0.0, 1.0 - abs(median_width - width_center) / width_half_range
        )
        score *= 0.5 + 0.5 * max(
            0.0,
            1.0
            - heading_difference / config["maximum_pair_heading_difference_deg"],
        )
        score *= 0.5 + 0.5 * min(
            1.0, overlap / max(20.0, config["minimum_longitudinal_overlap_m"])
        )
        score *= max(0.0, 1.0 - width_range / config["maximum_lane_width_range_m"])
        if score < config["minimum_pair_score"]:
            reasons.append("pair_score_below_threshold")
        metrics = {
            "longitudinal_overlap_m": round(overlap, 3),
            "heading_difference_deg": round(heading_difference, 3),
            "minimum_width_m": round(min(widths), 3),
            "median_width_m": round(median_width, 3),
            "maximum_width_m": round(max(widths), 3),
            "width_range_m": round(width_range, 3),
        }
        if reasons:
            rejected.append(
                {
                    "boundary_ids": [first.boundary_id, second.boundary_id],
                    "reasons": reasons,
                    "metrics": metrics,
                }
            )
            continue
        centerline = tuple(
            ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in zip(left, right)
        )
        lanes.append(
            LaneCandidate(
                _lane_id(left_boundary.boundary_id, right_boundary.boundary_id),
                left_boundary.boundary_id,
                right_boundary.boundary_id,
                tuple(left),
                tuple(right),
                centerline,
                tuple(left + list(reversed(right))),
                score,
                metrics,
            )
        )
    lanes.sort(key=lambda lane: (-lane.pair_score, lane.lane_id))
    return lanes, rejected


def match_ego(
    lanes: Iterable[LaneCandidate],
    ego: tuple[float, float, float],
    config: dict[str, Any],
) -> dict[str, Any]:
    point = (ego[0], ego[1])
    scored, rejected = [], []
    for lane in lanes:
        center_distance = polyline_distance(point, lane.centerline)
        heading = nearest_heading(point, lane.centerline)
        heading_difference = (
            math.inf
            if heading is None
            else abs(math.degrees(wrap_angle(heading - ego[2])))
        )
        inside = point_in_polygon(point, lane.polygon)
        boundary_distance = min(
            polyline_distance(point, lane.left), polyline_distance(point, lane.right)
        )
        reasons = []
        if not inside and boundary_distance > config["outside_polygon_tolerance_m"]:
            reasons.append("ego_outside_polygon_tolerance")
        if heading_difference > config["maximum_ego_heading_difference_deg"]:
            reasons.append("ego_heading_mismatch")
        if center_distance > config["maximum_centerline_distance_m"]:
            reasons.append("centerline_too_far")
        score = lane.pair_score
        score *= max(
            0.0,
            1.0 - heading_difference / config["maximum_ego_heading_difference_deg"],
        )
        score *= max(
            0.0,
            1.0 - center_distance / config["maximum_centerline_distance_m"],
        )
        score += 0.15 if inside else 0.0
        item = {
            "lane_id": lane.lane_id,
            "score": round(score, 4),
            "inside_polygon": inside,
            "centerline_distance_m": round(center_distance, 3),
            "nearest_boundary_distance_m": round(boundary_distance, 3),
            "heading_difference_deg": round(heading_difference, 3),
            "rejection_reasons": reasons,
        }
        (rejected if reasons else scored).append(item)
    scored.sort(key=lambda item: (-item["score"], item["lane_id"]))
    if not scored:
        return {
            "lane_id": None,
            "confidence": 0.0,
            "ambiguous": False,
            "method": "no_acceptable_candidate",
            "candidates": [],
            "rejected_candidates": rejected,
        }
    best = scored[0]
    margin = best["score"] - (scored[1]["score"] if len(scored) > 1 else 0.0)
    ambiguous = len(scored) > 1 and margin < config["ambiguity_score_margin"]
    confidence = max(0.0, min(1.0, best["score"] * min(1.0, margin / config["ambiguity_score_margin"])))
    return {
        "lane_id": best["lane_id"],
        "confidence": round(confidence, 4),
        "ambiguous": ambiguous,
        "method": "polygon_heading_centerline_score",
        "score_margin": round(margin, 4),
        "candidates": scored,
        "rejected_candidates": rejected,
    }
