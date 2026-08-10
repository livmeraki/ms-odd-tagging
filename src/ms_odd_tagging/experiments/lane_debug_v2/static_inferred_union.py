"""Area-first reconstruction of static inferred lanes from overlapping ego-corridor boxes.

The green box polygons are the geometry source of truth.  A smooth route seed is
used only to define longitudinal cross-sections.  At each station we intersect
all box polygons with the local lane normal, union the resulting lateral
intervals, and retain the connected interval that contains the route seed.
Smoothing is applied to the left/right union envelopes rather than inventing a
fixed-width corridor through box centers.
"""
from __future__ import annotations

import math
from statistics import median
from typing import Any


def _dist(a: list[float], b: list[float]) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _cross(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _append_unique(target: list[list[float]], points: list[list[float]]) -> None:
    for p in points:
        if len(p) < 2:
            continue
        q = [float(p[0]), float(p[1])]
        if not target or _dist(target[-1], q) > 1e-4:
            target.append(q)


def _smooth_points(points: list[list[float]], passes: int = 2) -> list[list[float]]:
    if len(points) <= 2:
        return [p[:] for p in points]
    out = [p[:] for p in points]
    for _ in range(max(0, passes)):
        nxt = [out[0][:]]
        for i in range(1, len(out) - 1):
            nxt.append([
                0.25 * out[i - 1][0] + 0.50 * out[i][0] + 0.25 * out[i + 1][0],
                0.25 * out[i - 1][1] + 0.50 * out[i][1] + 0.25 * out[i + 1][1],
            ])
        nxt.append(out[-1][:])
        out = nxt
    return out


def _resample_polyline(points: list[list[float]], spacing_m: float) -> list[list[float]]:
    if len(points) < 2:
        return [p[:] for p in points]
    cumulative = [0.0]
    for a, b in zip(points, points[1:]):
        cumulative.append(cumulative[-1] + _dist(a, b))
    total = cumulative[-1]
    if total <= 1e-6:
        return [points[0][:], points[-1][:]]
    count = max(2, int(math.ceil(total / max(spacing_m, 0.2))) + 1)
    out: list[list[float]] = []
    segment = 0
    for i in range(count):
        target = total * i / (count - 1)
        while segment + 2 < len(cumulative) and cumulative[segment + 1] < target:
            segment += 1
        a, b = points[segment], points[segment + 1]
        d0, d1 = cumulative[segment], cumulative[segment + 1]
        ratio = 0.0 if d1 <= d0 else (target - d0) / (d1 - d0)
        out.append([
            a[0] + ratio * (b[0] - a[0]),
            a[1] + ratio * (b[1] - a[1]),
        ])
    return out


def _normal_at(path: list[list[float]], index: int) -> tuple[float, float] | None:
    if len(path) < 2:
        return None
    a = path[max(0, index - 1)]
    b = path[min(len(path) - 1, index + 1)]
    dx, dy = b[0] - a[0], b[1] - a[1]
    norm = math.hypot(dx, dy)
    if norm <= 1e-8:
        return None
    return (-dy / norm, dx / norm)


def _line_polygon_intervals(
    origin: list[float],
    normal: tuple[float, float],
    polygon: list[list[float]],
) -> list[tuple[float, float]]:
    """Return t-intervals where origin + t*normal lies inside polygon."""
    pts = [[float(p[0]), float(p[1])] for p in polygon if len(p) >= 2]
    if len(pts) < 3:
        return []
    hits: list[float] = []
    d = normal
    for a, b in zip(pts, pts[1:] + pts[:1]):
        v = (b[0] - a[0], b[1] - a[1])
        denom = _cross(d, v)
        if abs(denom) <= 1e-9:
            continue
        w = (a[0] - origin[0], a[1] - origin[1])
        t = _cross(w, v) / denom
        u = _cross(w, d) / denom
        if -1e-8 <= u <= 1.0 + 1e-8:
            hits.append(t)
    hits.sort()
    unique: list[float] = []
    for value in hits:
        if not unique or abs(value - unique[-1]) > 1e-5:
            unique.append(value)
    if len(unique) < 2:
        return []
    if len(unique) % 2 == 1:
        # Vertex tangency can leave an odd hit count. Drop the least useful
        # extreme rather than manufacturing an unbounded interval.
        unique = unique[:-1]
    return [(unique[i], unique[i + 1]) for i in range(0, len(unique) - 1, 2)]


def _merge_intervals(intervals: list[tuple[float, float]], tolerance_m: float = 0.08) -> list[tuple[float, float]]:
    if not intervals:
        return []
    ordered = sorted((min(a, b), max(a, b)) for a, b in intervals)
    merged = [ordered[0]]
    for a, b in ordered[1:]:
        pa, pb = merged[-1]
        if a <= pb + tolerance_m:
            merged[-1] = (pa, max(pb, b))
        else:
            merged.append((a, b))
    return merged


def _choose_seed_component(intervals: list[tuple[float, float]]) -> tuple[float, float] | None:
    if not intervals:
        return None
    containing = [item for item in intervals if item[0] - 0.15 <= 0.0 <= item[1] + 0.15]
    if containing:
        return max(containing, key=lambda item: item[1] - item[0])
    return min(intervals, key=lambda item: min(abs(item[0]), abs(item[1])))


def _interpolate_missing(values: list[float | None]) -> list[float] | None:
    valid = [i for i, value in enumerate(values) if value is not None]
    if not valid:
        return None
    out = [None if v is None else float(v) for v in values]
    first, last = valid[0], valid[-1]
    for i in range(0, first):
        out[i] = out[first]
    for i in range(last + 1, len(out)):
        out[i] = out[last]
    previous = first
    for current in valid[1:]:
        if current > previous + 1:
            a, b = float(out[previous]), float(out[current])
            for i in range(previous + 1, current):
                ratio = (i - previous) / (current - previous)
                out[i] = a + ratio * (b - a)
        previous = current
    return [float(v) for v in out]


def _smooth_offsets(values: list[float], raw: list[float], passes: int = 3, max_deviation_m: float = 0.35) -> list[float]:
    out = list(values)
    if len(out) <= 2:
        return out
    for _ in range(max(0, passes)):
        nxt = [out[0]]
        for i in range(1, len(out) - 1):
            value = 0.25 * out[i - 1] + 0.50 * out[i] + 0.25 * out[i + 1]
            lo, hi = raw[i] - max_deviation_m, raw[i] + max_deviation_m
            nxt.append(max(lo, min(hi, value)))
        nxt.append(out[-1])
        out = nxt
    return out


def build_smoothed_box_union_corridor(
    pieces: list[dict[str, Any]],
    *,
    sample_spacing_m: float = 0.5,
    smoothing_passes: int = 3,
    maximum_smoothing_deviation_m: float = 0.35,
) -> dict[str, Any] | None:
    """Create one smooth corridor from the area union of overlapping green boxes."""
    ordered = sorted(pieces, key=lambda p: int(p.get("frame_index", 0)))
    polygons = [p.get("polygon_lcs_m") or [] for p in ordered if len(p.get("polygon_lcs_m") or []) >= 3]
    if not polygons:
        return None

    centers: list[list[float]] = []
    for piece in ordered:
        line = piece.get("centerline_lcs_m") or []
        if line:
            p = line[len(line) // 2]
            centers.append([float(p[0]), float(p[1])])
    if len(centers) < 2:
        return None

    first_line = ordered[0].get("centerline_lcs_m") or []
    last_line = ordered[-1].get("centerline_lcs_m") or []
    seed: list[list[float]] = []
    if first_line:
        _append_unique(seed, [[float(first_line[0][0]), float(first_line[0][1])]])
    _append_unique(seed, centers)
    if last_line:
        _append_unique(seed, [[float(last_line[-1][0]), float(last_line[-1][1])]])
    if len(seed) < 2:
        return None

    seed = _resample_polyline(_smooth_points(seed, passes=2), sample_spacing_m)
    raw_left: list[float | None] = []
    raw_right: list[float | None] = []
    normals: list[tuple[float, float] | None] = []
    component_counts: list[int] = []

    for i, point in enumerate(seed):
        normal = _normal_at(seed, i)
        normals.append(normal)
        if normal is None:
            raw_left.append(None)
            raw_right.append(None)
            component_counts.append(0)
            continue
        intervals: list[tuple[float, float]] = []
        for polygon in polygons:
            intervals.extend(_line_polygon_intervals(point, normal, polygon))
        merged = _merge_intervals(intervals)
        component_counts.append(len(merged))
        chosen = _choose_seed_component(merged)
        if chosen is None:
            raw_left.append(None)
            raw_right.append(None)
        else:
            raw_right.append(chosen[0])
            raw_left.append(chosen[1])

    left_offsets = _interpolate_missing(raw_left)
    right_offsets = _interpolate_missing(raw_right)
    if left_offsets is None or right_offsets is None:
        return None
    left_raw_f = list(left_offsets)
    right_raw_f = list(right_offsets)
    left_offsets = _smooth_offsets(
        left_offsets, left_raw_f,
        passes=smoothing_passes,
        max_deviation_m=maximum_smoothing_deviation_m,
    )
    right_offsets = _smooth_offsets(
        right_offsets, right_raw_f,
        passes=smoothing_passes,
        max_deviation_m=maximum_smoothing_deviation_m,
    )

    left: list[list[float]] = []
    right: list[list[float]] = []
    center: list[list[float]] = []
    widths: list[float] = []
    for point, normal, lo, ro in zip(seed, normals, left_offsets, right_offsets):
        if normal is None:
            continue
        # Enforce a positive corridor width without replacing the union-derived
        # offsets with a fixed width.
        if lo <= ro + 0.5:
            mid = (lo + ro) / 2.0
            lo, ro = mid + 0.5, mid - 0.5
        lp = [point[0] + normal[0] * lo, point[1] + normal[1] * lo]
        rp = [point[0] + normal[0] * ro, point[1] + normal[1] * ro]
        left.append(lp)
        right.append(rp)
        center.append([(lp[0] + rp[0]) / 2.0, (lp[1] + rp[1]) / 2.0])
        widths.append(_dist(lp, rp))

    if len(left) < 2 or len(right) < 2:
        return None
    polygon = left + list(reversed(right))
    return {
        "centerline_lcs_m": center,
        "left_boundary_lcs_m": left,
        "right_boundary_lcs_m": right,
        "polygon_lcs_m": polygon,
        "median_width_m": median(widths) if widths else 3.5,
        "method": "smoothed_cross_sectional_union_of_overlapping_boxes",
        "sample_spacing_m": sample_spacing_m,
        "sample_count": len(center),
        "evidence_polygon_count": len(polygons),
        "maximum_union_component_count_at_station": max(component_counts, default=0),
        "smoothing_passes": smoothing_passes,
        "maximum_smoothing_deviation_m": maximum_smoothing_deviation_m,
    }
