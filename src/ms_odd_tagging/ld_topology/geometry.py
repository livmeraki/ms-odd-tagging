"""Dependency-free planar geometry helpers."""

from __future__ import annotations

import math
from typing import Iterable

from .models import Point


def finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def wrap_degrees(value: float) -> float:
    return value % 360.0


def acute_angle_delta(a: float, b: float) -> float:
    delta = abs((a - b + 180.0) % 360.0 - 180.0)
    return delta


def polyline_length(points: Iterable[Point]) -> float:
    pts = list(points)
    return sum(distance(a, b) for a, b in zip(pts, pts[1:]))


def point_segment_distance(point: Point, start: Point, end: Point) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    denom = dx * dx + dy * dy
    if denom <= 1e-12:
        return distance(point, start)
    ratio = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / denom))
    return distance(point, (start[0] + ratio * dx, start[1] + ratio * dy))


def polyline_distance(point: Point, points: Iterable[Point]) -> float:
    pts = list(points)
    if not pts:
        return math.inf
    if len(pts) == 1:
        return distance(point, pts[0])
    return min(point_segment_distance(point, a, b) for a, b in zip(pts, pts[1:]))


def point_in_polygon(point: Point, polygon: Iterable[Point]) -> bool:
    pts = list(polygon)
    if len(pts) < 3:
        return False
    x, y = point
    inside = False
    prev = pts[-1]
    for cur in pts:
        if point_segment_distance(point, prev, cur) <= 1e-9:
            return True
        if ((cur[1] > y) != (prev[1] > y)) and (
            x < (prev[0] - cur[0]) * (y - cur[1]) / (prev[1] - cur[1]) + cur[0]
        ):
            inside = not inside
        prev = cur
    return inside


def polygon_area(polygon: Iterable[Point]) -> float:
    pts = list(polygon)
    if len(pts) < 3:
        return 0.0
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))) / 2.0


def _orientation(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _between(a: Point, b: Point, c: Point) -> bool:
    return min(a[0], c[0]) - 1e-9 <= b[0] <= max(a[0], c[0]) + 1e-9 and min(a[1], c[1]) - 1e-9 <= b[1] <= max(a[1], c[1]) + 1e-9


def segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    o1, o2, o3, o4 = _orientation(a, b, c), _orientation(a, b, d), _orientation(c, d, a), _orientation(c, d, b)
    eps = 1e-9
    if abs(o1) <= eps and _between(a, c, b):
        return True
    if abs(o2) <= eps and _between(a, d, b):
        return True
    if abs(o3) <= eps and _between(c, a, d):
        return True
    if abs(o4) <= eps and _between(c, b, d):
        return True
    return (o1 > eps) != (o2 > eps) and (o3 > eps) != (o4 > eps)


def polygon_self_intersects(polygon: Iterable[Point]) -> bool:
    pts = list(polygon)
    n = len(pts)
    if n < 4:
        return False
    edges = [(pts[i], pts[(i + 1) % n]) for i in range(n)]
    for i, (a, b) in enumerate(edges):
        for j, (c, d) in enumerate(edges):
            if abs(i - j) <= 1 or {i, j} == {0, n - 1}:
                continue
            if min(distance(a, c), distance(a, d), distance(b, c), distance(b, d)) <= 1e-7:
                continue
            if segments_intersect(a, b, c, d):
                return True
    return False


def resample_polyline(points: Iterable[Point], count: int) -> tuple[Point, ...]:
    pts = list(points)
    if len(pts) < 2:
        return tuple(pts)
    lengths = [0.0]
    for a, b in zip(pts, pts[1:]):
        lengths.append(lengths[-1] + distance(a, b))
    total = lengths[-1]
    if total <= 1e-9:
        return tuple(pts[:1] * count)
    output: list[Point] = []
    segment = 0
    for index in range(count):
        station = total * index / max(1, count - 1)
        while segment + 2 < len(lengths) and lengths[segment + 1] < station:
            segment += 1
        start, end = pts[segment], pts[segment + 1]
        span = lengths[segment + 1] - lengths[segment]
        ratio = 0.0 if span <= 1e-12 else (station - lengths[segment]) / span
        output.append((start[0] + ratio * (end[0] - start[0]), start[1] + ratio * (end[1] - start[1])))
    return tuple(output)


def circle_polygon(center: Point, radius: float, vertices: int = 48) -> tuple[Point, ...]:
    return tuple(
        (
            center[0] + radius * math.cos(2.0 * math.pi * i / vertices),
            center[1] + radius * math.sin(2.0 * math.pi * i / vertices),
        )
        for i in range(vertices)
    )


def segment_circle_intersections(start: Point, end: Point, center: Point, radius: float) -> list[Point]:
    sx, sy = start[0] - center[0], start[1] - center[1]
    ex, ey = end[0] - center[0], end[1] - center[1]
    dx, dy = ex - sx, ey - sy
    a = dx * dx + dy * dy
    b = 2.0 * (sx * dx + sy * dy)
    c = sx * sx + sy * sy - radius * radius
    disc = b * b - 4.0 * a * c
    if a <= 1e-12 or disc < -1e-9:
        return []
    disc = max(0.0, disc)
    roots = [(-b - math.sqrt(disc)) / (2.0 * a), (-b + math.sqrt(disc)) / (2.0 * a)]
    output = []
    for t in roots:
        if -1e-9 <= t <= 1.0 + 1e-9:
            p = (start[0] + t * (end[0] - start[0]), start[1] + t * (end[1] - start[1]))
            if all(distance(p, q) > 1e-6 for q in output):
                output.append(p)
    return output


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    pos = max(0.0, min(1.0, fraction)) * (len(ordered) - 1)
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    ratio = pos - lo
    return ordered[lo] * (1.0 - ratio) + ordered[hi] * ratio
