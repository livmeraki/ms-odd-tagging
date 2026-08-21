"""Small geometry helpers for VLM candidate evidence."""

from __future__ import annotations

import math
from typing import Any


def finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def ego_heading(frame: dict[str, Any]) -> float:
    ego = frame.get("ego") or {}
    value = ego.get("heading_lcs_rad")
    return float(value) if finite(value) else 0.0


def ego_position(frame: dict[str, Any]) -> tuple[float, float]:
    point = (frame.get("ego") or {}).get("position_lcs_m") or [0.0, 0.0]
    return float(point[0]), float(point[1])


def lcs_to_ego(point: list[float] | tuple[float, ...], frame: dict[str, Any]) -> tuple[float, float]:
    ex, ey = ego_position(frame)
    yaw = ego_heading(frame)
    dx = float(point[0]) - ex
    dy = float(point[1]) - ey
    c = math.cos(yaw)
    s = math.sin(yaw)
    return c * dx + s * dy, -s * dx + c * dy


def object_ego_xy(obj: dict[str, Any], frame: dict[str, Any]) -> tuple[float, float] | None:
    pos_ego = obj.get("position_ego_m") or {}
    if finite(pos_ego.get("longitudinal_m")) and finite(pos_ego.get("lateral_m")):
        return float(pos_ego["longitudinal_m"]), float(pos_ego["lateral_m"])
    if finite(pos_ego.get("longitudinal")) and finite(pos_ego.get("lateral")):
        return float(pos_ego["longitudinal"]), float(pos_ego["lateral"])
    pos = obj.get("position_lcs_m") or obj.get("center_lcs_m")
    if isinstance(pos, (list, tuple)) and len(pos) >= 2 and finite(pos[0]) and finite(pos[1]):
        return lcs_to_ego(pos, frame)
    signed_longitudinal = obj.get("signed_longitudinal_m")
    signed_lateral = obj.get("signed_lateral_m")
    if finite(signed_longitudinal) and finite(signed_lateral):
        return float(signed_longitudinal), float(signed_lateral)
    return None


def ego_speed(frame: dict[str, Any]) -> float | None:
    value = (frame.get("ego") or {}).get("speed_mps")
    return float(value) if finite(value) else None


def ego_acceleration(frame: dict[str, Any]) -> float | None:
    ego = frame.get("ego") or {}
    for key in ("acceleration_mps2", "longitudinal_acceleration_mps2"):
        if finite(ego.get(key)):
            return float(ego[key])
    if finite(frame.get("ego_acceleration_mps2")):
        return float(frame["ego_acceleration_mps2"])
    return None


def motion_state(frame: dict[str, Any]) -> str:
    state = frame.get("ego_motion_state") or (frame.get("ego") or {}).get("motion_state")
    if state:
        return str(state)
    speed = ego_speed(frame)
    accel = ego_acceleration(frame)
    if speed is not None and speed < 0.3:
        return "stationary"
    if speed is not None and speed < 2.0:
        return "slow"
    if accel is not None and accel < -0.4:
        return "decelerating"
    return "moving"


def normalized_class(obj: dict[str, Any]) -> str:
    return str(
        obj.get("normalized_category")
        or obj.get("class")
        or obj.get("class_name")
        or obj.get("category")
        or ""
    ).lower()


def object_id(obj: dict[str, Any]) -> str:
    return str(obj.get("track_id") or obj.get("object_id") or obj.get("id") or "")


def point_distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])

