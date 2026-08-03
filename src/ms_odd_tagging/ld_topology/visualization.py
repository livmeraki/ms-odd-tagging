"""Static debug images for LD topology results."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


def render_debug_image(result: dict[str, Any], frame: dict[str, Any] | None, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lanes = result.get("lanes", [])
    components = result.get("components", [])
    points = []
    for lane in lanes:
        points.extend(tuple(p) for p in lane.get("left_boundary_lcs_m", []))
        points.extend(tuple(p) for p in lane.get("right_boundary_lcs_m", []))
    for comp in components:
        points.extend(tuple(p) for p in comp.get("core_polygon_lcs_m", []))
    if frame:
        ego = _frame_ego(frame)
        if ego:
            points.append(ego[:2])
    if not points:
        points = [(0, 0), (1, 1)]
    min_x, max_x = min(p[0] for p in points), max(p[0] for p in points)
    min_y, max_y = min(p[1] for p in points), max(p[1] for p in points)
    pad = 10.0
    width, height = 1400, 1000
    sx = (width - 80) / max(1.0, max_x - min_x + 2 * pad)
    sy = (height - 80) / max(1.0, max_y - min_y + 2 * pad)
    scale = min(sx, sy)

    def tx(point: tuple[float, float]) -> tuple[float, float]:
        return (40 + (point[0] - min_x + pad) * scale, height - (40 + (point[1] - min_y + pad) * scale))

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image, "RGBA")
    for lane in lanes:
        poly = [tx(tuple(p)) for p in lane.get("polygon_lcs_m", [])]
        if len(poly) >= 3:
            color = (120, 200, 120, 45)
            if lane.get("intersection_evidence") == "strong":
                color = (230, 70, 60, 80)
            elif lane.get("intersection_evidence") == "partial":
                color = (245, 170, 40, 75)
            draw.polygon(poly, fill=color, outline=(60, 60, 60, 60))
        for side, flag in (("left", lane.get("left_boundary_intersection")), ("right", lane.get("right_boundary_intersection"))):
            pts = [tx(tuple(p)) for p in lane.get(f"{side}_boundary_lcs_m", [])]
            if len(pts) >= 2:
                draw.line(pts, fill=(210, 0, 0, 220) if flag else (120, 120, 120, 170), width=2)
        center = [tx(tuple(p)) for p in lane.get("centerline_lcs_m", [])]
        if len(center) >= 2:
            draw.line(center, fill=(20, 80, 180, 120), width=1)
    for comp in components:
        poly = [tx(tuple(p)) for p in comp.get("core_polygon_lcs_m", [])]
        if len(poly) >= 3:
            draw.polygon(poly, outline=(0, 0, 0, 240), fill=(80, 160, 240, 45))
        center = tx(tuple(comp["center_lcs_m"]))
        draw.ellipse((center[0] - 5, center[1] - 5, center[0] + 5, center[1] + 5), fill=(0, 0, 0, 255))
        for arm in comp.get("arms", []):
            crossing = tx(tuple(arm["crossing_point_lcs_m"]))
            draw.ellipse((crossing[0] - 5, crossing[1] - 5, crossing[0] + 5, crossing[1] + 5), fill=(0, 90, 220, 255))
            draw.line([center, crossing], fill=(0, 90, 220, 180), width=2)
            draw.text((crossing[0] + 6, crossing[1] + 3), f'{arm["angle_deg"]:.0f}', fill=(0, 40, 120, 255))
    label = "scene"
    if frame:
        ego = _frame_ego(frame)
        if ego:
            pos = tx(ego[:2])
            yaw = ego[2]
            tip = tx((ego[0] + 6 * math.cos(yaw), ego[1] + 6 * math.sin(yaw)))
            draw.ellipse((pos[0] - 6, pos[1] - 6, pos[0] + 6, pos[1] + 6), fill=(20, 20, 20, 255))
            draw.line([pos, tip], fill=(20, 20, 20, 255), width=3)
        label = f'frame {frame.get("frame_index")}'
    cls = ""
    if result.get("frames"):
        match = next((row for row in result["frames"] if frame and row.get("frame_index") == frame.get("frame_index")), None)
        if match:
            cls = f'  {match["topology_class"]}  conf={match["topology_confidence"]}'
    draw.rectangle((0, 0, width, 34), fill=(255, 255, 255, 230))
    draw.text((12, 10), f"{result.get('recording_id') or ''} {label}{cls}", fill=(0, 0, 0, 255), font=ImageFont.load_default())
    image.save(output_path)


def _frame_ego(frame: dict[str, Any]) -> tuple[float, float, float] | None:
    ego = frame.get("ego") or {}
    pos = ego.get("position_lcs_m") or []
    yaw = ego.get("heading_lcs_rad")
    if len(pos) < 2 or yaw is None:
        return None
    return (float(pos[0]), float(pos[1]), float(yaw))
