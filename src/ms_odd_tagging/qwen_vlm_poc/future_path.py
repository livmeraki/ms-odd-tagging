"""Neutral future-ego-path geometry for VLM evidence and frame selection."""

from __future__ import annotations

import math
from typing import Any

from .geometry import ego_position, lcs_to_ego, object_ego_xy, object_id


DEFAULT_HORIZON_S = 12.0
DEFAULT_TARGET_DISTANCE_M = 40.0
DEFAULT_CORRIDOR_HALF_WIDTH_M = 1.5
DEFAULT_MAX_POINTS = 16


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _uniform_rows(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count <= 0 or not rows:
        return []
    if len(rows) <= count:
        return rows
    if count == 1:
        return [rows[0]]
    positions = [round(i * (len(rows) - 1) / (count - 1)) for i in range(count)]
    return [rows[pos] for pos in positions]


def future_ego_path(
    frames_by_index: dict[int, dict[str, Any]],
    frame_index: int,
    *,
    horizon_s: float = DEFAULT_HORIZON_S,
    target_distance_m: float = DEFAULT_TARGET_DISTANCE_M,
    corridor_half_width_m: float = DEFAULT_CORRIDOR_HALF_WIDTH_M,
    max_points: int = DEFAULT_MAX_POINTS,
) -> dict[str, Any]:
    """Return a spatially useful future ego path in the selected frame's axes.

    The path uses actual future canonical ego poses. Collection continues until
    either ``target_distance_m`` of traveled trajectory has been covered,
    ``horizon_s`` has elapsed, or the recording ends. This keeps the path useful
    when ego is slow/stopped while preventing an unbounded trajectory payload.
    It is raw trajectory geometry, not a prediction/classification heuristic.
    """
    anchor = frames_by_index.get(frame_index)
    if anchor is None:
        return {
            "frame": frame_index,
            "coordinate_frame": "selected_frame_ego_centered_heading_aligned",
            "horizon_s": 0.0,
            "target_distance_m": round(float(target_distance_m), 3),
            "path_length_m": 0.0,
            "corridor_half_width_m": corridor_half_width_m,
            "points": [],
        }

    anchor_time = anchor.get("time_since_start_s")
    if not _finite_number(anchor_time):
        anchor_time = 0.0
    anchor_time = float(anchor_time)

    rows: list[dict[str, Any]] = []
    traveled_m = 0.0
    previous_lcs: tuple[float, float] | None = None

    for index in sorted(frames_by_index):
        if index < frame_index:
            continue
        frame = frames_by_index[index]
        timestamp = frame.get("time_since_start_s")
        if not _finite_number(timestamp):
            continue
        offset_s = float(timestamp) - anchor_time
        if offset_s < -1e-9:
            continue
        if offset_s > horizon_s + 1e-9:
            break

        position = ego_position(frame)
        current_lcs = (float(position[0]), float(position[1]))
        if previous_lcs is not None:
            traveled_m += math.hypot(
                current_lcs[0] - previous_lcs[0],
                current_lcs[1] - previous_lcs[1],
            )
        previous_lcs = current_lcs

        longitudinal_m, lateral_m = lcs_to_ego(position, anchor)
        rows.append(
            {
                "frame": index,
                "time_offset_s": round(offset_s, 3),
                "longitudinal_m": round(float(longitudinal_m), 3),
                "lateral_m": round(float(lateral_m), 3),
                "path_distance_m": round(float(traveled_m), 3),
            }
        )

        if traveled_m >= target_distance_m - 1e-9:
            break

    sampled = _uniform_rows(rows, max_points)
    actual_horizon = rows[-1]["time_offset_s"] if rows else 0.0
    actual_path_length = rows[-1]["path_distance_m"] if rows else 0.0
    return {
        "frame": frame_index,
        "coordinate_frame": "selected_frame_ego_centered_heading_aligned",
        "horizon_s": actual_horizon,
        "target_distance_m": round(float(target_distance_m), 3),
        "path_length_m": round(float(actual_path_length), 3),
        "corridor_half_width_m": round(float(corridor_half_width_m), 3),
        "points": sampled,
    }


def distance_to_polyline(
    point: tuple[float, float],
    polyline: list[tuple[float, float]],
) -> float | None:
    """Euclidean distance from a point to a polyline in ego coordinates."""
    if not polyline:
        return None
    if len(polyline) == 1:
        return math.hypot(point[0] - polyline[0][0], point[1] - polyline[0][1])
    best = math.inf
    px, py = point
    for (ax, ay), (bx, by) in zip(polyline, polyline[1:]):
        dx = bx - ax
        dy = by - ay
        denom = dx * dx + dy * dy
        if denom <= 1e-12:
            distance = math.hypot(px - ax, py - ay)
        else:
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / denom))
            qx = ax + t * dx
            qy = ay + t * dy
            distance = math.hypot(px - qx, py - qy)
        best = min(best, distance)
    return best if math.isfinite(best) else None


def pedestrian_path_distance(
    frame: dict[str, Any],
    pedestrian_ids: set[str],
    path_geometry: dict[str, Any],
) -> float | None:
    """Return nearest candidate-pedestrian distance to the neutral future path.

    Only pedestrians at/forward of the ego are considered for landmark selection;
    this value is never serialized as a scenario truth label.
    """
    points = [
        (float(row["longitudinal_m"]), float(row["lateral_m"]))
        for row in path_geometry.get("points", [])
        if _finite_number(row.get("longitudinal_m")) and _finite_number(row.get("lateral_m"))
    ]
    if not points:
        return None
    best = math.inf
    for obj in frame.get("objects", []):
        if object_id(obj) not in pedestrian_ids:
            continue
        position = object_ego_xy(obj, frame)
        if position is None or position[0] < -1.0:
            continue
        distance = distance_to_polyline(position, points)
        if distance is not None:
            best = min(best, distance)
    return best if math.isfinite(best) else None
