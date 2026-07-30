"""Explorer-aligned, ego-heading-up BEV renderer for single canonical frames."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .model_input import (
    CLASS_COLORS,
    PngCanvas,
    ego_heading,
    hex_to_rgb,
    lcs_to_ego,
    ld_feature_lcs_points,
    ld_feature_lookup,
    ld_point_lookup,
)


LANE_STYLES = {
    "solid": ("#0ea5e9", 3, 0.82),
    "dashed": ("#2563eb", 3, 0.80),
    "broken": ("#2563eb", 3, 0.80),
    "virtual": ("#94a3b8", 2, 0.60),
    "zigzag": ("#7c3aed", 3, 0.78),
    "unknown": ("#64748b", 2, 0.58),
}


def _feature_points(feature: dict[str, Any], points_by_id: dict[str, Any]) -> list:
    return ld_feature_lcs_points(feature, points_by_id)


def _clip_segment(a, b, left_m, right_m, back_m, forward_m):
    """Liang-Barsky clipping in ego longitudinal/lateral coordinates."""
    x0, y0 = a
    x1, y1 = b
    dx, dy = x1 - x0, y1 - y0
    p = (-dx, dx, -dy, dy)
    q = (x0 + back_m, forward_m - x0, y0 + right_m, left_m - y0)
    u0, u1 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if abs(pi) < 1e-12:
            if qi < 0:
                return None
            continue
        ratio = qi / pi
        if pi < 0:
            u0 = max(u0, ratio)
        else:
            u1 = min(u1, ratio)
        if u0 > u1:
            return None
    return ((x0 + u0 * dx, y0 + u0 * dy), (x0 + u1 * dx, y0 + u1 * dy))


def _draw_feature(
    canvas,
    lcs_points,
    ego_position,
    ego_yaw,
    screen,
    extent,
    color,
    width,
    alpha,
    *,
    closed=False,
):
    if len(lcs_points) < 2:
        return
    points = [lcs_to_ego(point, ego_position, ego_yaw) for point in lcs_points]
    if closed and points[0] != points[-1]:
        points.append(points[0])
    left_m, right_m, back_m, forward_m = extent
    for a, b in zip(points, points[1:]):
        clipped = _clip_segment(a, b, left_m, right_m, back_m, forward_m)
        if clipped is None:
            continue
        start, end = map(screen, clipped)
        canvas.line(*start, *end, hex_to_rgb(color), width=width, alpha=alpha)


def _object_corners_lcs(obj: dict[str, Any], ego_yaw: float):
    center = obj.get("position_lcs_m") or []
    dimensions = obj.get("dimensions_m") or {}
    length, width = dimensions.get("length"), dimensions.get("width")
    if len(center) < 2 or length is None or width is None:
        return None
    yaw = ego_yaw + float(obj.get("heading_relative_rad") or 0.0)
    c, s = math.cos(yaw), math.sin(yaw)
    half_l, half_w = max(float(length), 0.5) / 2, max(float(width), 0.5) / 2
    return [
        (center[0] + f * c - l * s, center[1] + f * s + l * c)
        for f, l in ((half_l, half_w), (half_l, -half_w), (-half_l, -half_w), (-half_l, half_w))
    ]


def _footprint_buffer_points(
    length_m: float,
    width_m: float,
    radius_m: float,
    samples_per_corner: int = 12,
) -> list[tuple[float, float]]:
    """Return the boundary of an ego rectangle buffered by ``radius_m``."""
    half_length, half_width = length_m / 2.0, width_m / 2.0
    corners = (
        (half_length, half_width, 0.0),
        (-half_length, half_width, math.pi / 2.0),
        (-half_length, -half_width, math.pi),
        (half_length, -half_width, 3.0 * math.pi / 2.0),
    )
    points = []
    for longitudinal, lateral, start_angle in corners:
        for index in range(samples_per_corner + 1):
            angle = start_angle + (math.pi / 2.0) * index / samples_per_corner
            points.append(
                (
                    longitudinal + radius_m * math.cos(angle),
                    lateral + radius_m * math.sin(angle),
                )
            )
    return points


def _forward_arc_points(
    inner_radius_m: float,
    outer_radius_m: float,
    half_angle_deg: float,
    samples: int = 28,
) -> list[tuple[float, float]]:
    """Return an ego-heading-up annular sector used by Phase 3C."""
    half_angle = math.radians(half_angle_deg)
    angles = [
        -half_angle + 2.0 * half_angle * index / samples
        for index in range(samples + 1)
    ]
    outer = [
        (outer_radius_m * math.cos(angle), outer_radius_m * math.sin(angle))
        for angle in angles
    ]
    inner = [
        (inner_radius_m * math.cos(angle), inner_radius_m * math.sin(angle))
        for angle in reversed(angles)
    ]
    return outer + inner


def _velocity_text(vector: Any) -> tuple[str, float | None]:
    if (
        not isinstance(vector, (list, tuple))
        or len(vector) < 2
        or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in vector[:2])
    ):
        return "v=n/a", None
    vx, vy = float(vector[0]), float(vector[1])
    speed = math.hypot(vx, vy)
    return f"v={speed:.1f} m/s ({vx:.1f},{vy:.1f})", speed


def _annotate_kinematics(
    output_path: Path,
    frame: dict[str, Any],
    lane_context: dict[str, Any] | None,
    proximity_radius_m: float,
    crossing_arc: tuple[float, float, float] | None,
) -> None:
    image = Image.open(output_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    try:
        bold = ImageFont.truetype("DejaVuSans-Bold.ttf", 14)
    except OSError:
        bold = ImageFont.load_default()

    ego = frame.get("ego") or {}
    ego_velocity, calculated_speed = _velocity_text(ego.get("velocity_lcs_mps"))
    speed = ego.get("speed_mps")
    if not isinstance(speed, (int, float)) or not math.isfinite(speed):
        speed = calculated_speed
    ego_lane = ((lane_context or {}).get("ego_lane") or {}).get("logical_lane_id")
    lead = (lane_context or {}).get("lead")
    lead_summary = (
        f"#{lead.get('object_id')} ({lead.get('class')})"
        if isinstance(lead, dict)
        else "none"
    )
    lines = [
        f"EGO speed={speed:.1f} m/s | {ego_velocity}" if speed is not None else f"EGO speed=n/a | {ego_velocity}",
        f"lane={ego_lane or 'n/a'} | lead={lead_summary}",
        f"footprint proximity radius={proximity_radius_m:.1f} m",
    ]
    if crossing_arc is not None:
        inner, outer, half_angle = crossing_arc
        lines.append(
            f"forward crossing arc={inner:.1f}-{outer:.1f} m, +/-{half_angle:.0f} deg"
        )
    widths = [draw.textbbox((0, 0), line, font=bold)[2] for line in lines]
    panel_width = max(widths) + 22
    panel_height = len(lines) * 21 + 12
    draw.rounded_rectangle(
        (10, 10, 10 + panel_width, 10 + panel_height),
        radius=6,
        fill=(255, 255, 255, 235),
        outline=(14, 116, 144),
        width=2,
    )
    for index, line in enumerate(lines):
        draw.text((20, 18 + index * 21), line, fill=(15, 23, 42), font=bold)
    image.save(output_path)


def render_revised_bev_png(
    recording: dict[str, Any],
    frame: dict[str, Any],
    output_path: Path,
    extent: tuple[float, float, float, float],
    size: tuple[int, int],
    *,
    lane_context: dict[str, Any] | None = None,
    proximity_radius_m: float = 30.0,
    crossing_arc: tuple[float, float, float] | None = None,
    debug_context: dict[str, Any] | None = None,
) -> None:
    """Render source LCS geometry into an asymmetric ego-centered, heading-up view."""
    width, height = size
    left_m, right_m, back_m, forward_m = extent
    scale = min(width / (left_m + right_m), height / (back_m + forward_m))
    center_x = left_m * scale + (width - (left_m + right_m) * scale) / 2
    center_y = forward_m * scale + (height - (back_m + forward_m) * scale) / 2
    ego = frame["ego"]
    ego_position = ego["position_lcs_m"]
    ego_yaw = ego_heading(ego)

    def screen(point):
        longitudinal, lateral = point
        return center_x - lateral * scale, center_y - longitudinal * scale

    def visible(point):
        longitudinal, lateral = point
        return -back_m <= longitudinal <= forward_m and -right_m <= lateral <= left_m

    canvas = PngCanvas(width, height)
    grid = hex_to_rgb("#dbe4ee")
    for lateral in range(-int(right_m), int(left_m) + 1, 10):
        x, _ = screen((0, lateral))
        canvas.line(x, 0, x, height - 1, grid, width=1, alpha=0.65)
    for longitudinal in range(-int(back_m), int(forward_m) + 1, 10):
        _, y = screen((longitudinal, 0))
        canvas.line(0, y, width - 1, y, grid, width=1, alpha=0.65)

    proximity = _footprint_buffer_points(4.8, 2.0, proximity_radius_m)
    proximity_screen = [screen(point) for point in proximity]
    for start, end in zip(
        proximity_screen, proximity_screen[1:] + proximity_screen[:1]
    ):
        canvas.line(
            *start,
            *end,
            hex_to_rgb("#0891b2"),
            width=3,
            alpha=0.82,
        )

    store = recording.get("ld_feature_store") or {}
    nearby = (frame.get("ld") or {}).get("nearby_feature_ids") or {}
    points_by_id = ld_point_lookup(recording)
    lookups = {
        "lane_lines": ld_feature_lookup(recording, "lane_lines", "line_id"),
        "road_boundaries": ld_feature_lookup(recording, "road_boundaries", "road_boundary_id"),
        "roadmarks": ld_feature_lookup(recording, "roadmarks", "roadmark_id"),
    }

    for feature_id in nearby.get("road_boundaries", []):
        feature = lookups["road_boundaries"].get(str(feature_id))
        if feature:
            color = "#f59e0b" if str(feature.get("boundary_attribute", "")).lower() == "drivable" else "#b45309"
            _draw_feature(canvas, _feature_points(feature, points_by_id), ego_position, ego_yaw, screen, extent, color, 3, 0.80)

    for feature_id in nearby.get("roadmarks", []):
        feature = lookups["roadmarks"].get(str(feature_id))
        if feature:
            class_name = str(feature.get("class") or "unknown").lower()
            color = "#e11d48" if "crosswalk" in class_name else "#f97316"
            _draw_feature(canvas, _feature_points(feature, points_by_id), ego_position, ego_yaw, screen, extent, color, 4, 0.88, closed=feature.get("shape_type") == "polygon")

    for feature_id in nearby.get("lane_lines", []):
        feature = lookups["lane_lines"].get(str(feature_id))
        if feature:
            pattern = str((feature.get("attributes") or {}).get("pattern") or "unknown").lower()
            color, line_width, alpha = LANE_STYLES.get(pattern, LANE_STYLES["unknown"])
            _draw_feature(canvas, _feature_points(feature, points_by_id), ego_position, ego_yaw, screen, extent, color, line_width, alpha)

    if crossing_arc is not None:
        arc_points = _forward_arc_points(*crossing_arc)
        arc_screen = [screen(point) for point in arc_points]
        for start, end in zip(arc_screen, arc_screen[1:] + arc_screen[:1]):
            canvas.line(
                *start,
                *end,
                hex_to_rgb("#db2777"),
                width=4,
                alpha=0.95,
            )

    lead_id = str(((lane_context or {}).get("lead") or {}).get("object_id") or "")
    active_object_ids = set()
    for event in (debug_context or {}).get("rule_based_reference", {}).get(
        "active_events", []
    ):
        evidence = event.get("evidence") or {}
        for key in ("object_track_ids", "source_object_ids"):
            active_object_ids.update(str(value) for value in evidence.get(key, []))
        if evidence.get("object_track_id") is not None:
            active_object_ids.add(str(evidence["object_track_id"]))
    for obj in frame.get("objects", []):
        position = obj.get("position_lcs_m")
        if not position:
            continue
        center_ego = lcs_to_ego(position, ego_position, ego_yaw)
        if not visible(center_ego):
            continue
        color = hex_to_rgb(CLASS_COLORS.get(obj.get("class"), "#64748b"))
        corners_lcs = _object_corners_lcs(obj, ego_yaw)
        if corners_lcs:
            corners = [screen(lcs_to_ego(point, ego_position, ego_yaw)) for point in corners_lcs]
            outline = (
                hex_to_rgb("#db2777")
                if str(obj.get("object_id")) in active_object_ids
                else hex_to_rgb("#dc2626")
                if str(obj.get("object_id")) == lead_id
                else color
            )
            canvas.polygon(
                corners,
                fill=color,
                outline=outline,
                alpha=0.18,
                outline_width=4
                if str(obj.get("object_id")) == lead_id
                or str(obj.get("object_id")) in active_object_ids
                else 2,
            )
        sx, sy = screen(center_ego)
        canvas.circle(sx, sy, 5, color, alpha=1.0)

    ego_corners = [(2.4, 1.0), (2.4, -1.0), (-2.4, -1.0), (-2.4, 1.0)]
    canvas.polygon([screen(point) for point in ego_corners], hex_to_rgb("#22c55e"), hex_to_rgb("#166534"), alpha=0.34, outline_width=4)
    nose = [(3.0, 0.0), (1.6, 0.7), (1.6, -0.7)]
    canvas.polygon([screen(point) for point in nose], hex_to_rgb("#166534"), hex_to_rgb("#166534"), alpha=0.9)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save_png(output_path)
    _annotate_kinematics(
        output_path,
        frame,
        lane_context,
        proximity_radius_m,
        crossing_arc,
    )
