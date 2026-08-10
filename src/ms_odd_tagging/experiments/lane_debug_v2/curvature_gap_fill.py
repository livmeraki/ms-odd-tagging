"""Curvature-aware geometry completion between trusted canonical lane fragments.

The bridge uses a quintic Hermite curve with endpoint position, tangent and
curvature constraints.  It is intentionally local: it only fills a gap after
two existing canonical track endpoints have been selected as a plausible lane
continuation.  It does not discover or create standalone lanes.
"""
from __future__ import annotations

import math
from typing import Any


def _dist(a, b) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _wrap(a: float) -> float:
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def _heading(a, b) -> float:
    return math.atan2(float(b[1]) - float(a[1]), float(b[0]) - float(a[0]))


def endpoint_state(line: list[list[float]], side: str) -> dict[str, float] | None:
    """Return position, outward heading and signed endpoint curvature."""
    if len(line) < 2:
        return None
    pts = [[float(p[0]), float(p[1])] for p in line if len(p) >= 2]
    if len(pts) < 2:
        return None
    if side == "start":
        oriented = list(reversed(pts[: min(5, len(pts))]))
    else:
        oriented = pts[max(0, len(pts) - 5):]
    # oriented always runs from lane interior toward the selected endpoint.
    headings: list[float] = []
    lengths: list[float] = []
    for a, b in zip(oriented, oriented[1:]):
        d = _dist(a, b)
        if d <= 1e-5:
            continue
        headings.append(_heading(a, b))
        lengths.append(d)
    if not headings:
        return None
    curvature = 0.0
    if len(headings) >= 2 and lengths:
        curvature = sum(_wrap(b - a) for a, b in zip(headings, headings[1:])) / max(sum(lengths), 1e-6)
    p = oriented[-1]
    return {"x": p[0], "y": p[1], "heading": headings[-1], "curvature": curvature}


def _solve3(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    a = [row[:] + [float(v)] for row, v in zip(matrix, rhs)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-10:
            raise ValueError("singular quintic bridge system")
        a[col], a[pivot] = a[pivot], a[col]
        scale = a[col][col]
        for j in range(col, 4):
            a[col][j] /= scale
        for r in range(3):
            if r == col:
                continue
            factor = a[r][col]
            for j in range(col, 4):
                a[r][j] -= factor * a[col][j]
    return [a[i][3] for i in range(3)]


def _quintic_coeff(p0: float, d0: float, dd0: float, p1: float, d1: float, dd1: float) -> list[float]:
    # p(t)=a0+a1 t+...+a5 t^5. First three coefficients come from t=0.
    a0, a1, a2 = p0, d0, dd0 / 2.0
    rhs = [
        p1 - (a0 + a1 + a2),
        d1 - (a1 + 2.0 * a2),
        dd1 - 2.0 * a2,
    ]
    # constraints at t=1 for a3,a4,a5: position, first derivative, second derivative.
    a3, a4, a5 = _solve3(
        [[1.0, 1.0, 1.0], [3.0, 4.0, 5.0], [6.0, 12.0, 20.0]], rhs
    )
    return [a0, a1, a2, a3, a4, a5]


def _eval(c: list[float], t: float) -> tuple[float, float, float]:
    p = sum(c[i] * t**i for i in range(6))
    d = sum(i * c[i] * t ** (i - 1) for i in range(1, 6))
    dd = sum(i * (i - 1) * c[i] * t ** (i - 2) for i in range(2, 6))
    return p, d, dd


def build_curvature_gap(
    line_a: list[list[float]], side_a: str,
    line_b: list[list[float]], side_b: str,
    *, width_a_m: float, width_b_m: float,
    sample_spacing_m: float = 0.75,
    tangent_scale_ratio: float = 1.0,
) -> dict[str, Any] | None:
    """Build a smooth C2-ish lane corridor connecting the selected endpoints.

    The outward tangent of B points from B into the gap, so the traversal tangent
    at the end of the bridge is its opposite direction.
    """
    sa = endpoint_state(line_a, side_a)
    sb = endpoint_state(line_b, side_b)
    if sa is None or sb is None:
        return None
    p0 = [sa["x"], sa["y"]]
    p1 = [sb["x"], sb["y"]]
    chord = _dist(p0, p1)
    if chord <= 1e-4:
        return None

    h0 = sa["heading"]
    h1 = _wrap(sb["heading"] + math.pi)
    k0 = sa["curvature"]
    # Reversing B traversal changes signed curvature sign.
    k1 = -sb["curvature"]
    scale = max(chord * tangent_scale_ratio, 1e-3)

    d0 = [math.cos(h0) * scale, math.sin(h0) * scale]
    d1 = [math.cos(h1) * scale, math.sin(h1) * scale]
    # For an arc-length-like parameterization: r'' ~= k * n * |r'|^2.
    dd0 = [-math.sin(h0) * k0 * scale * scale, math.cos(h0) * k0 * scale * scale]
    dd1 = [-math.sin(h1) * k1 * scale * scale, math.cos(h1) * k1 * scale * scale]

    cx = _quintic_coeff(p0[0], d0[0], dd0[0], p1[0], d1[0], dd1[0])
    cy = _quintic_coeff(p0[1], d0[1], dd0[1], p1[1], d1[1], dd1[1])
    count = max(4, int(math.ceil(chord / max(sample_spacing_m, 0.2))) + 1)

    center: list[list[float]] = []
    left: list[list[float]] = []
    right: list[list[float]] = []
    curvatures: list[float] = []
    arc_length = 0.0
    previous = None
    for i in range(count):
        t = i / (count - 1)
        x, dx, ddx = _eval(cx, t)
        y, dy, ddy = _eval(cy, t)
        speed = math.hypot(dx, dy)
        if speed <= 1e-8:
            return None
        nx, ny = -dy / speed, dx / speed
        width = width_a_m + (width_b_m - width_a_m) * t
        center.append([x, y])
        left.append([x + nx * width / 2.0, y + ny * width / 2.0])
        right.append([x - nx * width / 2.0, y - ny * width / 2.0])
        curvature = (dx * ddy - dy * ddx) / max(speed**3, 1e-9)
        curvatures.append(curvature)
        if previous is not None:
            arc_length += _dist(previous, [x, y])
        previous = [x, y]

    polygon = left + list(reversed(right))
    return {
        "centerline_lcs_m": center,
        "left_boundary_lcs_m": left,
        "right_boundary_lcs_m": right,
        "polygon_lcs_m": polygon,
        "endpoint_a_heading_rad": h0,
        "endpoint_b_heading_rad": h1,
        "endpoint_a_curvature_per_m": k0,
        "endpoint_b_curvature_per_m": k1,
        "maximum_abs_bridge_curvature_per_m": max(abs(k) for k in curvatures),
        "mean_abs_bridge_curvature_per_m": sum(abs(k) for k in curvatures) / len(curvatures),
        "chord_length_m": chord,
        "arc_length_m": arc_length,
        "arc_to_chord_ratio": arc_length / chord,
        "sample_count": count,
        "method": "quintic_hermite_position_tangent_curvature",
    }
