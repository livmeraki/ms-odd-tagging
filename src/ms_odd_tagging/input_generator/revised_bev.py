"""Explorer-aligned, ego-heading-up BEV renderer for single canonical frames."""

from __future__ import annotations

import math
import time
from collections import OrderedDict
from dataclasses import dataclass
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
TRAFFIC_LIGHT_MARKER_COLOR = "#0891b2"


@dataclass(frozen=True)
class BevStaticContext:
    """Recording-static LD indexes reused by every rendered frame."""

    points_by_id: dict[str, Any]
    lane_lines: dict[str, Any]
    road_boundaries: dict[str, Any]
    roadmarks: dict[str, Any]


# A generator normally holds one recording dict for the whole frame loop. Keep a
# small bounded identity cache so legacy compatibility wrappers also benefit
# without changing their public call signatures.
_STATIC_CONTEXT_CACHE: "OrderedDict[int, tuple[dict[str, Any], BevStaticContext]]" = OrderedDict()
_STATIC_CONTEXT_CACHE_LIMIT = 8
_RENDER_TIMINGS: "OrderedDict[str, dict[str, float]]" = OrderedDict()
_RENDER_TIMINGS_LIMIT = 256


def _uncached_bev_static_context(recording: dict[str, Any]) -> BevStaticContext:
    return BevStaticContext(
        points_by_id=ld_point_lookup(recording),
        lane_lines=ld_feature_lookup(recording, "lane_lines", "line_id"),
        road_boundaries=ld_feature_lookup(recording, "road_boundaries", "road_boundary_id"),
        roadmarks=ld_feature_lookup(recording, "roadmarks", "roadmark_id"),
    )


def build_bev_static_context(recording: dict[str, Any]) -> BevStaticContext:
    """Return recording-level LD lookup tables, building them at most once per object."""
    key = id(recording)
    cached = _STATIC_CONTEXT_CACHE.get(key)
    if cached is not None and cached[0] is recording:
        _STATIC_CONTEXT_CACHE.move_to_end(key)
        return cached[1]
    context = _uncached_bev_static_context(recording)
    _STATIC_CONTEXT_CACHE[key] = (recording, context)
    _STATIC_CONTEXT_CACHE.move_to_end(key)
    while len(_STATIC_CONTEXT_CACHE) > _STATIC_CONTEXT_CACHE_LIMIT:
        _STATIC_CONTEXT_CACHE.popitem(last=False)
    return context


def pop_render_timings(output_path: Path) -> dict[str, float]:
    """Return and remove the most recent timing breakdown for ``output_path``."""
    return _RENDER_TIMINGS.pop(str(output_path), {})


def _store_render_timings(output_path: Path, timings: dict[str, float]) -> None:
    key = str(output_path)
    _RENDER_TIMINGS[key] = timings
    _RENDER_TIMINGS.move_to_end(key)
    while len(_RENDER_TIMINGS) > _RENDER_TIMINGS_LIMIT:
        _RENDER_TIMINGS.popitem(last=False)


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


def _draw_feature(canvas, lcs_points, ego_position, ego_yaw, screen, extent, color, width, alpha, *, closed=False):
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



def _draw_traffic_light_marker(
    canvas,
    x: float,
    y: float,
    *,
    pedestrian: bool = False,
) -> None:
    """Draw a neutral marker without implying an unobserved signal state."""
    color = hex_to_rgb(TRAFFIC_LIGHT_MARKER_COLOR)
    outline = hex_to_rgb("#111827")
    if pedestrian:
        canvas.circle(x, y, 10, outline, alpha=0.18)
        canvas.circle(x, y, 7, color, alpha=0.95)
        return

    box = [
        (x - 5, y - 8),
        (x + 5, y - 8),
        (x + 5, y + 8),
        (x - 5, y + 8),
    ]
    canvas.polygon(
        box,
        fill=color,
        outline=outline,
        alpha=0.95,
        outline_width=2,
    )


def _footprint_buffer_points(length_m: float, width_m: float, radius_m: float, samples_per_corner: int = 12) -> list[tuple[float, float]]:
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
            points.append((longitudinal + radius_m * math.cos(angle), lateral + radius_m * math.sin(angle)))
    return points


def _forward_arc_points(inner_radius_m: float, outer_radius_m: float, half_angle_deg: float, samples: int = 28) -> list[tuple[float, float]]:
    half_angle = math.radians(half_angle_deg)
    angles = [-half_angle + 2.0 * half_angle * index / samples for index in range(samples + 1)]
    outer = [(outer_radius_m * math.cos(angle), outer_radius_m * math.sin(angle)) for angle in angles]
    inner = [(inner_radius_m * math.cos(angle), inner_radius_m * math.sin(angle)) for angle in reversed(angles)]
    return outer + inner


def centered_extent(extent: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    left_m, right_m, back_m, forward_m = extent
    half_width = (float(left_m) + float(right_m)) / 2.0
    half_length = (float(back_m) + float(forward_m)) / 2.0
    return half_width, half_width, half_length, half_length


def metric_viewport(extent: tuple[float, float, float, float], size: tuple[int, int]) -> tuple[float, float, float, float, float]:
    left_m, right_m, back_m, forward_m = extent
    width, height = size
    physical_width = left_m + right_m
    physical_height = back_m + forward_m
    if physical_width <= 0 or physical_height <= 0:
        raise ValueError("BEV extent dimensions must be positive")
    if width <= 0 or height <= 0:
        raise ValueError("BEV image dimensions must be positive")
    scale = min(width / physical_width, height / physical_height)
    draw_width = physical_width * scale
    draw_height = physical_height * scale
    origin_x = (width - draw_width) / 2.0
    origin_y = (height - draw_height) / 2.0
    return scale, origin_x, origin_y, draw_width, draw_height


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
    static_context: BevStaticContext | None = None,
) -> None:
    """Render source LCS geometry into a centered ego-heading-up view."""
    render_start = time.perf_counter()
    context_start = time.perf_counter()
    context = static_context or build_bev_static_context(recording)
    context_time = time.perf_counter() - context_start
    draw_start = time.perf_counter()

    width, height = size
    extent = centered_extent(extent)
    left_m, right_m, back_m, forward_m = extent
    scale, origin_x, origin_y, draw_width, draw_height = metric_viewport(extent, size)
    center_x = origin_x + draw_width / 2.0
    center_y = origin_y + draw_height / 2.0
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
    viewport_left = origin_x
    viewport_right = origin_x + draw_width
    viewport_top = origin_y
    viewport_bottom = origin_y + draw_height
    for lateral in range(-int(right_m), int(left_m) + 1, 10):
        x, _ = screen((0, lateral))
        canvas.line(x, viewport_top, x, viewport_bottom, grid, width=1, alpha=0.65)
    for longitudinal in range(-int(back_m), int(forward_m) + 1, 10):
        _, y = screen((longitudinal, 0))
        canvas.line(viewport_left, y, viewport_right, y, grid, width=1, alpha=0.65)

    proximity = _footprint_buffer_points(4.8, 2.0, proximity_radius_m)
    proximity_screen = [screen(point) for point in proximity]
    for start, end in zip(proximity_screen, proximity_screen[1:] + proximity_screen[:1]):
        canvas.line(*start, *end, hex_to_rgb("#0891b2"), width=3, alpha=0.82)

    nearby = (frame.get("ld") or {}).get("nearby_feature_ids") or {}
    points_by_id = context.points_by_id

    for feature_id in nearby.get("road_boundaries", []):
        feature = context.road_boundaries.get(str(feature_id))
        if feature:
            color = "#f59e0b" if str(feature.get("boundary_attribute", "")).lower() == "drivable" else "#b45309"
            _draw_feature(canvas, _feature_points(feature, points_by_id), ego_position, ego_yaw, screen, extent, color, 3, 0.80)

    for feature_id in nearby.get("roadmarks", []):
        feature = context.roadmarks.get(str(feature_id))
        if feature:
            class_name = str(feature.get("class") or "unknown").lower()
            color = CROSSWALK_COLOR if "crosswalk" in class_name else STOPLINE_COLOR if "stopline" in class_name else "#64748b"
            _draw_feature(canvas, _feature_points(feature, points_by_id), ego_position, ego_yaw, screen, extent, color, 4, 0.88, closed=feature.get("shape_type") == "polygon")

    for feature_id in nearby.get("lane_lines", []):
        feature = context.lane_lines.get(str(feature_id))
        if feature:
            pattern = str((feature.get("attributes") or {}).get("pattern") or "unknown").lower()
            color, line_width, alpha = LANE_STYLES.get(pattern, LANE_STYLES["unknown"])
            _draw_feature(canvas, _feature_points(feature, points_by_id), ego_position, ego_yaw, screen, extent, color, line_width, alpha)

    if crossing_arc is not None:
        arc_points = _forward_arc_points(*crossing_arc)
        arc_screen = [screen(point) for point in arc_points]
        for start, end in zip(arc_screen, arc_screen[1:] + arc_screen[:1]):
            canvas.line(*start, *end, hex_to_rgb(FORWARD_ARC_COLOR), width=4, alpha=0.95)

    lead_id = str(((lane_context or {}).get("lead") or {}).get("object_id") or "")
    active_object_ids = set()
    for event in (debug_context or {}).get("rule_based_reference", {}).get("active_events", []):
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
        color = hex_to_rgb(PEDESTRIAN_COLOR if class_name == "pedestrian" else CLASS_COLORS.get(class_name, "#64748b"))
        corners_lcs = _object_corners_lcs(obj, ego_yaw)
        if corners_lcs:
            corners = [screen(lcs_to_ego(point, ego_position, ego_yaw)) for point in corners_lcs]
            outline = hex_to_rgb(ACTIVE_OBJECT_COLOR) if str(obj.get("object_id")) in active_object_ids else hex_to_rgb("#dc2626") if str(obj.get("object_id")) == lead_id else color
            canvas.polygon(
                corners,
                fill=color,
                outline=outline,
                alpha=0.18,
                outline_width=4 if str(obj.get("object_id")) == lead_id or str(obj.get("object_id")) in active_object_ids else 2,
            )
        sx, sy = screen(center_ego)
        canvas.circle(sx, sy, 5, color, alpha=1.0)

        if class_name in {"traffic_light_car", "traffic_light_ped"}:
            _draw_traffic_light_marker(
                canvas,
                sx,
                sy,
                pedestrian=class_name == "traffic_light_ped",
            )

    ego_corners = [(2.4, 1.0), (2.4, -1.0), (-2.4, -1.0), (-2.4, 1.0)]
    canvas.polygon([screen(point) for point in ego_corners], hex_to_rgb("#22c55e"), hex_to_rgb("#166534"), alpha=0.34, outline_width=4)
    nose = [(3.0, 0.0), (1.6, 0.7), (1.6, -0.7)]
    canvas.polygon([screen(point) for point in nose], hex_to_rgb("#166534"), hex_to_rgb("#166534"), alpha=0.9)
    draw_time = time.perf_counter() - draw_start

    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_start = time.perf_counter()
    canvas.save_png(output_path)
    png_time = time.perf_counter() - save_start
    total = time.perf_counter() - render_start
    _store_render_timings(
        output_path,
        {
            "bev_render_time_s": total,
            "bev_static_context_time_s": context_time,
            "bev_draw_time_s": draw_time,
            "png_encode_write_time_s": png_time,
        },
    )
