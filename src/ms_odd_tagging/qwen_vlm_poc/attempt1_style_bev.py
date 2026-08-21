"""Side renderer for attempt-1-style BEVs from real canonical frames.

This module is intentionally not wired into the production Qwen VLM POC path.
It mirrors the existing candidate BEV contract while drawing a higher-contrast
diagnostic visual style inspired by the first pedestrian pseudo-BEV attempt.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from ms_odd_tagging.frame_inputs.model_input import (
    PngCanvas,
    ego_heading,
    hex_to_rgb,
    lcs_to_ego,
    ld_feature_lcs_points,
    ld_feature_lookup,
    ld_point_lookup,
)
from ms_odd_tagging.frame_inputs.revised_bev import centered_extent, metric_viewport

from .config import VlmPocConfig
from .models import CandidateWindow


LANE_STYLES = {
    "solid": ("#3b82f6", 4, 0.92),
    "dashed": ("#60a5fa", 4, 0.86),
    "broken": ("#60a5fa", 4, 0.86),
    "virtual": ("#93c5fd", 2, 0.42),
    "zigzag": ("#8b5cf6", 4, 0.85),
    "unknown": ("#94a3b8", 2, 0.50),
}

BG = "#121821"
ROAD = "#343b45"
GRID = "#263241"
EGO = "#2ac46a"
EGO_OUTLINE = "#ffffff"
PED = "#ff8e2b"
PED_ARROW = "#ffb53d"
VEHICLE = "#4f8df7"
VEHICLE_OUTLINE = "#ffffff"
CROSSWALK = "#dc4242"
STOPLINE = "#8b5cf6"
BOUNDARY_DRIVABLE = "#f59e0b"
BOUNDARY_OTHER = "#b45309"
ACTIVE_OBJECT = "#facc15"


def _clip_segment(a, b, left_m, right_m, back_m, forward_m):
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


def _motion_vector_ego(obj: dict[str, Any], ego_yaw: float) -> tuple[float, float] | None:
    velocity = obj.get("velocity_lcs_mps") or obj.get("velocity_lcs") or []
    if isinstance(velocity, dict):
        longitudinal = velocity.get("longitudinal")
        lateral = velocity.get("lateral")
        if longitudinal is None or lateral is None:
            return None
        return float(longitudinal), float(lateral)
    if not isinstance(velocity, (list, tuple)) or len(velocity) < 2:
        relative = obj.get("relative_velocity_ego_mps") or {}
        longitudinal = relative.get("longitudinal")
        lateral = relative.get("lateral")
        if longitudinal is None or lateral is None:
            return None
        return float(longitudinal), float(lateral)
    return lcs_to_ego((float(velocity[0]), float(velocity[1])), (0.0, 0.0), ego_yaw)


def _draw_arrow(canvas, start, end, color, *, width=4, alpha=0.95) -> None:
    sx, sy = start
    ex, ey = end
    canvas.line(sx, sy, ex, ey, color, width=width, alpha=alpha)
    angle = math.atan2(ey - sy, ex - sx)
    for delta in (2.55, -2.55):
        hx = ex + math.cos(angle + delta) * 10
        hy = ey + math.sin(angle + delta) * 10
        canvas.line(ex, ey, hx, hy, color, width=width, alpha=alpha)


def _draw_pedestrian(canvas, sx: float, sy: float, obj: dict[str, Any], ego_yaw: float, screen, center_ego) -> None:
    ped = hex_to_rgb(PED)
    arrow = hex_to_rgb(PED_ARROW)
    canvas.circle(sx, sy, 11, hex_to_rgb("#ffffff"), alpha=1.0)
    canvas.circle(sx, sy, 8, ped, alpha=1.0)
    canvas.line(sx, sy + 8, sx, sy + 24, ped, width=7, alpha=1.0)
    motion = _motion_vector_ego(obj, ego_yaw)
    if motion:
        ml, mt = motion
        norm = math.hypot(ml, mt)
        if norm > 0.05:
            longitudinal, lateral = center_ego
            end = screen((longitudinal + ml / norm * 5.5, lateral + mt / norm * 5.5))
            _draw_arrow(canvas, (sx, sy - 16), end, arrow, width=5, alpha=0.98)


def render_attempt1_style_bev_png(
    recording: dict[str, Any],
    frame: dict[str, Any],
    output_path: Path,
    extent: tuple[float, float, float, float],
    size: tuple[int, int],
    *,
    proximity_radius_m: float = 30.0,
    highlighted_object_ids: set[str] | None = None,
) -> None:
    """Render real frame geometry in the first pseudo-BEV visual style."""
    width, height = size
    extent = centered_extent(extent)
    left_m, right_m, back_m, forward_m = extent
    scale, origin_x, origin_y, draw_width, draw_height = metric_viewport(extent, size)
    center_x = origin_x + draw_width / 2.0
    center_y = origin_y + draw_height / 2.0
    ego = frame["ego"]
    ego_position = ego["position_lcs_m"]
    ego_yaw = ego_heading(ego)
    highlighted_object_ids = highlighted_object_ids or set()

    def screen(point):
        longitudinal, lateral = point
        return center_x - lateral * scale, center_y - longitudinal * scale

    def visible(point):
        longitudinal, lateral = point
        return -back_m <= longitudinal <= forward_m and -right_m <= lateral <= left_m

    canvas = PngCanvas(width, height, bg=hex_to_rgb(BG))

    road_margin_px = 14
    canvas.polygon(
        [
            (origin_x + road_margin_px, origin_y),
            (origin_x + draw_width - road_margin_px, origin_y),
            (origin_x + draw_width - road_margin_px, origin_y + draw_height),
            (origin_x + road_margin_px, origin_y + draw_height),
        ],
        fill=hex_to_rgb(ROAD),
        outline=hex_to_rgb("#4b5563"),
        alpha=0.82,
        outline_width=2,
    )

    grid = hex_to_rgb(GRID)
    viewport_left = origin_x
    viewport_right = origin_x + draw_width
    viewport_top = origin_y
    viewport_bottom = origin_y + draw_height
    for lateral in range(-int(right_m), int(left_m) + 1, 10):
        x, _ = screen((0, lateral))
        canvas.line(x, viewport_top, x, viewport_bottom, grid, width=1, alpha=0.70)
    for longitudinal in range(-int(back_m), int(forward_m) + 1, 10):
        _, y = screen((longitudinal, 0))
        canvas.line(viewport_left, y, viewport_right, y, grid, width=1, alpha=0.70)

    if proximity_radius_m > 0:
        radius_px = proximity_radius_m * scale
        canvas.circle(center_x, center_y, radius_px, hex_to_rgb("#0891b2"), alpha=0.10)

    nearby = (frame.get("ld") or {}).get("nearby_feature_ids") or {}
    points_by_id = ld_point_lookup(recording)
    lane_lines = ld_feature_lookup(recording, "lane_lines", "line_id")
    road_boundaries = ld_feature_lookup(recording, "road_boundaries", "road_boundary_id")
    roadmarks = ld_feature_lookup(recording, "roadmarks", "roadmark_id")

    for feature_id in nearby.get("road_boundaries", []):
        feature = road_boundaries.get(str(feature_id))
        if feature:
            color = BOUNDARY_DRIVABLE if str(feature.get("boundary_attribute", "")).lower() == "drivable" else BOUNDARY_OTHER
            _draw_feature(canvas, ld_feature_lcs_points(feature, points_by_id), ego_position, ego_yaw, screen, extent, color, 3, 0.88)

    for feature_id in nearby.get("roadmarks", []):
        feature = roadmarks.get(str(feature_id))
        if feature:
            class_name = str(feature.get("class") or "unknown").lower()
            color = CROSSWALK if "crosswalk" in class_name else STOPLINE if "stopline" in class_name else "#94a3b8"
            _draw_feature(
                canvas,
                ld_feature_lcs_points(feature, points_by_id),
                ego_position,
                ego_yaw,
                screen,
                extent,
                color,
                4,
                0.92,
                closed=feature.get("shape_type") == "polygon",
            )

    for feature_id in nearby.get("lane_lines", []):
        feature = lane_lines.get(str(feature_id))
        if feature:
            pattern = str((feature.get("attributes") or {}).get("pattern") or "unknown").lower()
            color, line_width, alpha = LANE_STYLES.get(pattern, LANE_STYLES["unknown"])
            _draw_feature(canvas, ld_feature_lcs_points(feature, points_by_id), ego_position, ego_yaw, screen, extent, color, line_width, alpha)

    for obj in frame.get("objects", []):
        position = obj.get("position_lcs_m")
        if not position:
            continue
        center_ego = lcs_to_ego(position, ego_position, ego_yaw)
        if not visible(center_ego):
            continue
        sx, sy = screen(center_ego)
        class_name = str(obj.get("class") or "").lower()
        object_id = str(obj.get("object_id"))
        if class_name == "pedestrian":
            _draw_pedestrian(canvas, sx, sy, obj, ego_yaw, screen, center_ego)
            continue

        corners_lcs = _object_corners_lcs(obj, ego_yaw)
        color = hex_to_rgb(VEHICLE if class_name in {"car", "vehicle", "truck", "bus", "motorcycle"} else "#64748b")
        outline = hex_to_rgb(ACTIVE_OBJECT if object_id in highlighted_object_ids else VEHICLE_OUTLINE)
        if corners_lcs:
            corners = [screen(lcs_to_ego(point, ego_position, ego_yaw)) for point in corners_lcs]
            canvas.polygon(corners, fill=color, outline=outline, alpha=0.86, outline_width=3)
        canvas.circle(sx, sy, 4, outline, alpha=1.0)

    ego_corners = [(2.4, 1.0), (2.4, -1.0), (-2.4, -1.0), (-2.4, 1.0)]
    canvas.polygon(
        [screen(point) for point in ego_corners],
        fill=hex_to_rgb(EGO),
        outline=hex_to_rgb(EGO_OUTLINE),
        alpha=0.90,
        outline_width=3,
    )
    nose = [(3.1, 0.0), (1.5, 0.7), (1.5, -0.7)]
    canvas.polygon([screen(point) for point in nose], fill=hex_to_rgb(EGO), outline=hex_to_rgb(EGO_OUTLINE), alpha=0.95, outline_width=2)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save_png(output_path)


def render_candidate_bevs_attempt1_style(
    recording: dict[str, Any],
    candidate: CandidateWindow,
    output_root: Path,
    config: VlmPocConfig,
) -> CandidateWindow:
    """Render candidate BEVs in the side attempt-1 visual style."""
    frames_by_index = {
        int(frame["frame_index"]): frame
        for frame in recording.get("frames", [])
        if isinstance(frame.get("frame_index"), int)
    }
    paths = []
    highlighted_ids = set(candidate.primary_object_ids)
    for frame_index in candidate.selected_frame_indices[: config.max_bev_images]:
        frame = frames_by_index.get(frame_index)
        if frame is None:
            continue
        path = (
            output_root
            / "bev_attempt1_style"
            / candidate.scenario
            / candidate.recording_id
            / f"{candidate.candidate_id}_frame_{frame_index:06d}.png"
        )
        render_attempt1_style_bev_png(
            recording,
            frame,
            path,
            config.bev_extent_m,
            config.bev_size_px,
            proximity_radius_m=0.0 if candidate.scenario == "on_intersection" else 30.0,
            highlighted_object_ids=highlighted_ids,
        )
        paths.append(str(path))
    return CandidateWindow(
        **{
            **candidate.to_dict(),
            "evidence": candidate.evidence,
            "bev_paths": paths,
            "metadata": {
                **candidate.metadata,
                "bev_renderer": "side-attempt1-style-v1",
            },
        }
    )
