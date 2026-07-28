"""Timestamp-aware ego-motion features derived without modifying canonical data."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _number(value: Any) -> float | None:
    return float(value) if _finite(value) else None


@dataclass(frozen=True)
class EgoMotionFeatures:
    """Parallel feature arrays retaining original frame and timestamp identity."""

    frame_index: tuple[int, ...]
    timestamp_s: tuple[float, ...]
    speed_mps: tuple[float | None, ...]
    longitudinal_acceleration_mps2: tuple[float | None, ...]
    lateral_acceleration_mps2: tuple[float | None, ...]
    acceleration_magnitude_mps2: tuple[float | None, ...]
    jerk_mps3: tuple[float | None, ...]
    heading_rad: tuple[float | None, ...]
    unwrapped_heading_rad: tuple[float | None, ...]
    yaw_rate_rad_s: tuple[float | None, ...]
    heading_change_rad: tuple[float | None, ...]
    validity: dict[str, tuple[bool, ...]]
    quality_issues: tuple[str, ...]

    def __len__(self) -> int:
        return len(self.frame_index)


def _unwrap(headings: list[float | None]) -> list[float | None]:
    result: list[float | None] = []
    previous_raw: float | None = None
    previous_unwrapped: float | None = None
    for heading in headings:
        if heading is None:
            result.append(None)
            previous_raw = None
            previous_unwrapped = None
            continue
        if previous_raw is None or previous_unwrapped is None:
            unwrapped = heading
        else:
            delta = math.atan2(math.sin(heading - previous_raw), math.cos(heading - previous_raw))
            unwrapped = previous_unwrapped + delta
        result.append(unwrapped)
        previous_raw, previous_unwrapped = heading, unwrapped
    return result


def extract_ego_motion_features(
    frames: list[dict[str, Any]],
    *,
    max_sample_gap_s: float = 0.5,
    heading_change_horizon_s: float = 1.0,
    jerk_mode: str = "acceleration_vector_magnitude",
) -> EgoMotionFeatures:
    """Extract causal features from ordered canonical frames.

    Canonical speed, scalar acceleration, heading, and yaw rate are preferred.
    Vector acceleration, lateral acceleration, acceleration magnitude, and jerk
    are detection-only derivatives calculated with actual timestamps.
    """
    if max_sample_gap_s <= 0 or heading_change_horizon_s <= 0:
        raise ValueError("feature time horizons must be positive")
    if jerk_mode not in {
        "acceleration_vector_magnitude",
        "acceleration_magnitude",
        "longitudinal_acceleration",
    }:
        raise ValueError(f"unsupported jerk calculation mode: {jerk_mode}")
    if not frames:
        empty: tuple[Any, ...] = ()
        names = (
            "timestamp_s", "speed_mps", "longitudinal_acceleration_mps2",
            "lateral_acceleration_mps2", "acceleration_magnitude_mps2", "jerk_mps3",
            "heading_rad", "unwrapped_heading_rad", "yaw_rate_rad_s", "heading_change_rad",
        )
        return EgoMotionFeatures(empty, empty, empty, empty, empty, empty, empty, empty, empty, empty, empty, {n: empty for n in names}, ())

    indices: list[int] = []
    timestamps: list[float] = []
    speed: list[float | None] = []
    canonical_longitudinal_accel: list[float | None] = []
    heading: list[float | None] = []
    canonical_yaw_rate: list[float | None] = []
    velocity: list[tuple[float, float] | None] = []
    issues: list[str] = []
    for position, frame in enumerate(frames):
        if not isinstance(frame.get("frame_index"), int):
            raise ValueError(f"frame {position}: frame_index must be an integer")
        timestamp = _number(frame.get("time_since_start_s"))
        if timestamp is None:
            raise ValueError(f"frame {frame['frame_index']}: time_since_start_s is required and finite")
        ego = frame.get("ego")
        if not isinstance(ego, dict):
            raise ValueError(f"frame {frame['frame_index']}: ego object is required")
        vector = ego.get("velocity_lcs_mps")
        valid_vector = (
            isinstance(vector, (list, tuple)) and len(vector) >= 2
            and _number(vector[0]) is not None and _number(vector[1]) is not None
        )
        indices.append(frame["frame_index"])
        timestamps.append(timestamp)
        speed.append(_number(ego.get("speed_mps")))
        canonical_longitudinal_accel.append(_number(ego.get("acceleration_mps2")))
        heading.append(_number(ego.get("heading_lcs_rad", ego.get("heading_rad"))))
        canonical_yaw_rate.append(_number(ego.get("yaw_rate_radps")))
        velocity.append((float(vector[0]), float(vector[1])) if valid_vector else None)

    dt_valid = [False] * len(frames)
    for i in range(1, len(frames)):
        dt = timestamps[i] - timestamps[i - 1]
        dt_valid[i] = 0 < dt <= max_sample_gap_s
        if dt <= 0:
            issues.append(f"non_monotonic_timestamp:{indices[i - 1]}->{indices[i]}")
        elif dt > max_sample_gap_s:
            issues.append(f"sample_gap:{indices[i - 1]}->{indices[i]}:{dt:.6f}s")

    unwrapped = _unwrap(heading)
    derived_ax: list[float | None] = [None] * len(frames)
    derived_ay: list[float | None] = [None] * len(frames)
    lateral: list[float | None] = [None] * len(frames)
    longitudinal = list(canonical_longitudinal_accel)
    yaw_rate = list(canonical_yaw_rate)
    for i in range(1, len(frames)):
        if not dt_valid[i]:
            continue
        dt = timestamps[i] - timestamps[i - 1]
        if velocity[i] is not None and velocity[i - 1] is not None and heading[i] is not None:
            ax = (velocity[i][0] - velocity[i - 1][0]) / dt
            ay = (velocity[i][1] - velocity[i - 1][1]) / dt
            derived_ax[i], derived_ay[i] = ax, ay
            c, s = math.cos(heading[i]), math.sin(heading[i])
            if longitudinal[i] is None:
                longitudinal[i] = c * ax + s * ay
            lateral[i] = -s * ax + c * ay
        if yaw_rate[i] is None and unwrapped[i] is not None and unwrapped[i - 1] is not None:
            yaw_rate[i] = (unwrapped[i] - unwrapped[i - 1]) / dt

    magnitude = [
        math.hypot(lon, lat) if lon is not None and lat is not None else None
        for lon, lat in zip(longitudinal, lateral)
    ]
    jerk: list[float | None] = [None] * len(frames)
    for i in range(1, len(frames)):
        if not dt_valid[i]:
            continue
        dt = timestamps[i] - timestamps[i - 1]
        if jerk_mode == "acceleration_vector_magnitude":
            components = (
                longitudinal[i - 1], lateral[i - 1],
                longitudinal[i], lateral[i],
            )
            if all(value is not None for value in components):
                jerk_longitudinal = (longitudinal[i] - longitudinal[i - 1]) / dt
                jerk_lateral = (lateral[i] - lateral[i - 1]) / dt
                jerk[i] = math.hypot(jerk_longitudinal, jerk_lateral)
        else:
            jerk_source = magnitude if jerk_mode == "acceleration_magnitude" else longitudinal
            if jerk_source[i] is not None and jerk_source[i - 1] is not None:
                jerk[i] = abs(jerk_source[i] - jerk_source[i - 1]) / dt

    heading_change: list[float | None] = [None] * len(frames)
    left = 0
    for i in range(len(frames)):
        while left < i and timestamps[i] - timestamps[left + 1] >= heading_change_horizon_s:
            left += 1
        if (
            left < i and timestamps[i] - timestamps[left] >= heading_change_horizon_s * 0.8
            and timestamps[i] - timestamps[left] <= heading_change_horizon_s + max_sample_gap_s
            and all(dt_valid[j] for j in range(left + 1, i + 1))
            and unwrapped[i] is not None and unwrapped[left] is not None
        ):
            heading_change[i] = unwrapped[i] - unwrapped[left]

    arrays = {
        "timestamp_s": [float(v) for v in timestamps],
        "speed_mps": speed,
        "longitudinal_acceleration_mps2": longitudinal,
        "lateral_acceleration_mps2": lateral,
        "acceleration_magnitude_mps2": magnitude,
        "jerk_mps3": jerk,
        "heading_rad": heading,
        "unwrapped_heading_rad": unwrapped,
        "yaw_rate_rad_s": yaw_rate,
        "heading_change_rad": heading_change,
    }
    validity = {name: tuple(value is not None for value in values) for name, values in arrays.items()}
    return EgoMotionFeatures(
        tuple(indices), tuple(timestamps), tuple(speed), tuple(longitudinal), tuple(lateral),
        tuple(magnitude), tuple(jerk), tuple(heading), tuple(unwrapped), tuple(yaw_rate),
        tuple(heading_change), validity, tuple(issues),
    )
