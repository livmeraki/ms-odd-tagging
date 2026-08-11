"""Explorer-aligned, ego-heading-up BEV renderer for single canonical frames."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

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

CROSSWALK_COLOR = "#e11d48"
STOPLINE_COLOR = "#7c3aed"
FORWARD_ARC_COLOR = "#111827"
ACTIVE_OBJECT_COLOR = "#facc15"
PEDESTRIAN_COLOR = "#f97316"
FUTURE_PATH_COLOR = "#0891b2"
FUTURE_PATH_CORRIDOR_COLOR = "#67e8f9"
PEDESTRIAN_TRAIL_COLOR = "#ca8a04"

_DIGIT_GLYPHS = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    "-": ("000", "000", "111", "000", "000"),
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


def _draw_numeric_label(canvas, text: str, x: float, y: float, *, scale: int = 3) -> None:
    """Draw a dependency-free numeric ID label next to a candidate object."""
    glyphs = [(_DIGIT_GLYPHS.get(char), char) for char in str(text)]
    glyphs = [(glyph, char) for glyph, char in glyphs if glyph is not None]
    if not glyphs:
        return
    char_width = 3 * scale
    gap = scale
    width = len(glyphs) * char_width + max(0, len(glyphs) - 1) * gap + 4
    height = 5 * scale + 4
    left = max(1, min(canvas.width - width - 1, int(round(x + 8))))
    top = max(1, min(canvas.height - height - 1, int(round(y - height - 4))))
    background = [(left, top), (left + width, top), (left + width, top + height), (left, top + height)]
    canvas.polygon(background, hex_to_rgb("#ffffff"), hex_to_rgb(ACTIVE_OBJECT_COLOR), alpha=0.88, outline_width=1)
    cursor = left + 2
    color = hex_to_rgb("#854d0e")
    for glyph, _char in glyphs:
        for row_index, row in enumerate(glyph):
            for col_index, bit in enumerate(row):
                if bit != "1":
                    continue
                for dy in range(scale):
                    for dx in range(scale):
                        canvas.set_pixel(
                            cursor + col_index * scale + dx,
                            top + 2 + row_index * scale + dy,
                            color,
                            alpha=1.0,
                        )
        cursor += char_width + gap


def _draw_future_path(canvas, debug_context, screen, scale_x: float, scale_y: float) -> None:
    geometry = (debug_context or {}).get("ego_future_path") or {}
    points = []
    for row in geometry.get("points", []):
        longitudinal = row.get("longitudinal_m")
        lateral = row.get("lateral_m")
        if isinstance(longitudinal, (int, float)) and isinstance(lateral, (int, float)):
            points.append((float(longitudinal), float(lateral)))
    if len(points) < 2:
        return
    screen_points = [screen(point) for point in points]
    half_width_m = float(geometry.get("corridor_half_width_m") or 1.5)
    average_scale = (scale_x + scale_y) / 2.0
    corridor_width_px = max(4, int(round(2.0 * half_width_m * average_scale)))
    canvas.polyline(
        screen_points,
        hex_to_rgb(FUTURE_PATH_CORRIDOR_COLOR),
        width=corridor_width_px,
        alpha=0.25,
    )
    canvas.polyline(
        screen_points,
        hex_to_rgb(FUTURE_PATH_COLOR),
        width=4,
        alpha=0.95,
    )


def _draw_candidate_pedestrian_trails(
    canvas,
    recording: dict[str, Any],
    debug_context: dict[str, Any] | None,
    ego_position,
    ego_yaw: float,
    screen,
    visible,
) -> None:
    """Draw observed candidate-pedestrian motion in the current BEV frame."""
    context = debug_context or {}
    candidate_ids = {str(value) for value in context.get("candidate_object_ids", [])}
    if not candidate_ids:
        return
    start_frame = context.get("candidate_track_start_frame")
    end_frame = context.get("candidate_track_end_frame")
    tracks: dict[str, list[tuple[int, tuple[float, float]]]] = {value: [] for value in candidate_ids}
    for source_frame in recording.get("frames", []):
        source_index = source_frame.get("frame_index")
        if not isinstance(source_index, int):
            continue
        if isinstance(start_frame, int) and source_index < start_frame:
            continue
        if isinstance(end_frame, int) and source_index > end_frame:
            continue
        for obj in source_frame.get("objects", []):
            obj_id = str(obj.get("track_id") or obj.get("object_id") or obj.get("id") or "")
            if obj_id not in candidate_ids:
                continue
            if str(obj.get("class") or "").lower() != "pedestrian":
                continue
            position = obj.get("position_lcs_m") or obj.get("center_lcs_m")
            if not isinstance(position, (list, tuple)) or len(position) < 2:
                continue
            tracks[obj_id].append((source_index, lcs_to_ego(position, ego_position, ego_yaw)))

    trail_color = hex_to_rgb(PEDESTRIAN_TRAIL_COLOR)
    for states in tracks.values():
        if len(states) < 2:
            continue
        for (frame_a, point_a), (frame_b, point_b) in zip(states, states[1:]):
            if frame_b - frame_a > 5:
                continue
            if not (visible(point_a) or visible(point_b)):
                continue
            start = screen(point_a)
            end = screen(point_b)
            canvas.line(*start, *end, trail_color, width=3, alpha=0.72)
        marker_stride = max(1, len(states) // 8)
        for _frame_index, point in states[::marker_stride]:
            if visible(point):
                sx, sy = screen(point)
                canvas.circle(sx, sy, 2.5, trail_color, alpha=0.78)


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


def centered_extent(extent: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """Return symmetric left/right and behind/ahead bounds from configured totals."""
    left_m, right_m, back_m, forward_m = extent
    half_width = (float(left_m) + float(right_m)) / 2.0
    half_length = (float(back_m) + float(forward_m)) / 2.0
    return half_width, half_width, half_length, half_length


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
    """Render source LCS geometry into a centered ego-heading-up view."""
    width, height = size
    extent = centered_extent(extent)
    left_m, right_m, back_m, forward_m = extent
    scale_x = width / (left_m + right_m)
    scale_y = height / (back_m + forward_m)
    center_x = width / 2.0
    center_y = height / 2.0
    ego = frame["ego"]
    ego_position = ego["position_lcs_m"]
    ego_yaw = ego_heading(ego)

    def screen(point):
        longitudinal, lateral = point
        return center_x - lateral * scale_x, center_y - longitudinal * scale_y

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

    if proximity_radius_m > 0.0:
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
            color = (
                CROSSWALK_COLOR
                if "crosswalk" in class_name
                else STOPLINE_COLOR
                if "stopline" in class_name
                else "#64748b"
            )
            _draw_feature(canvas, _feature_points(feature, points_by_id), ego_position, ego_yaw, screen, extent, color, 4, 0.88, closed=feature.get("shape_type") == "polygon")

    for feature_id in nearby.get("lane_lines", []):
        feature = lookups["lane_lines"].get(str(feature_id))
        if feature:
            pattern = str((feature.get("attributes") or {}).get("pattern") or "unknown").lower()
            color, line_width, alpha = LANE_STYLES.get(pattern, LANE_STYLES["unknown"])
            _draw_feature(canvas, _feature_points(feature, points_by_id), ego_position, ego_yaw, screen, extent, color, line_width, alpha)

    _draw_future_path(canvas, debug_context, screen, scale_x, scale_y)
    _draw_candidate_pedestrian_trails(
        canvas,
        recording,
        debug_context,
        ego_position,
        ego_yaw,
        screen,
        visible,
    )

    if crossing_arc is not None:
        arc_points = _forward_arc_points(*crossing_arc)
        arc_screen = [screen(point) for point in arc_points]
        for start, end in zip(arc_screen, arc_screen[1:] + arc_screen[:1]):
            canvas.line(
                *start,
                *end,
                hex_to_rgb(FORWARD_ARC_COLOR),
                width=4,
                alpha=0.95,
            )

    lead_id = str(((lane_context or {}).get("lead") or {}).get("object_id") or "")
    active_object_ids = {str(value) for value in (debug_context or {}).get("candidate_object_ids", [])}
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
        class_name = str(obj.get("class") or "").lower()
        object_id = str(obj.get("track_id") or obj.get("object_id") or obj.get("id") or "")
        color = hex_to_rgb(
            PEDESTRIAN_COLOR
            if class_name == "pedestrian"
            else CLASS_COLORS.get(class_name, "#64748b")
        )
        corners_lcs = _object_corners_lcs(obj, ego_yaw)
        if corners_lcs:
            corners = [screen(lcs_to_ego(point, ego_position, ego_yaw)) for point in corners_lcs]
            outline = (
                hex_to_rgb(ACTIVE_OBJECT_COLOR)
                if object_id in active_object_ids
                else hex_to_rgb("#dc2626")
                if object_id == lead_id
                else color
            )
            canvas.polygon(
                corners,
                fill=color,
                outline=outline,
                alpha=0.18,
                outline_width=4
                if object_id == lead_id or object_id in active_object_ids
                else 2,
            )
        sx, sy = screen(center_ego)
        canvas.circle(sx, sy, 5, color, alpha=1.0)
        if class_name == "pedestrian" and object_id in active_object_ids:
            _draw_numeric_label(canvas, object_id, sx, sy)

    ego_corners = [(2.4, 1.0), (2.4, -1.0), (-2.4, -1.0), (-2.4, 1.0)]
    canvas.polygon([screen(point) for point in ego_corners], hex_to_rgb("#22c55e"), hex_to_rgb("#166534"), alpha=0.34, outline_width=4)
    nose = [(3.0, 0.0), (1.6, 0.7), (1.6, -0.7)]
    canvas.polygon([screen(point) for point in nose], hex_to_rgb("#166534"), hex_to_rgb("#166534"), alpha=0.9)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save_png(output_path)
