"""Reusable object-to-forward-ego-arc geometry for crossing scenarios."""

from __future__ import annotations

import math
from collections import Counter
from typing import Any


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def _wrap_angle(value: float) -> float:
    return (value + math.pi) % (2.0 * math.pi) - math.pi


def _axis_angle_difference_degrees(first: float, second: float) -> float:
    difference = abs(math.degrees(_wrap_angle(first - second)))
    return min(difference, 180.0 - difference)


def _ego_samples(recording: dict[str, Any]) -> list[dict[str, Any]]:
    samples = []
    for position, frame in enumerate(recording.get("frames", [])):
        timestamp = frame.get("time_since_start_s")
        ego = frame.get("ego") or {}
        point = ego.get("position_lcs_m") or []
        heading = ego.get("heading_lcs_rad")
        speed = ego.get("speed_mps")
        if (
            _finite(timestamp)
            and len(point) >= 2
            and _finite(point[0])
            and _finite(point[1])
            and _finite(heading)
        ):
            samples.append(
                {
                    "position": position,
                    "frame_index": frame.get("frame_index"),
                    "timestamp_s": float(timestamp),
                    "point": (float(point[0]), float(point[1])),
                    "heading_lcs_rad": float(heading),
                    "speed_mps": float(speed) if _finite(speed) else None,
                }
            )
    return samples


def _future_poses(
    samples: list[dict[str, Any]],
    timestamp_s: float,
    look_ahead_s: float,
) -> list[dict[str, Any]]:
    """Return synchronized future ego poses, including stationary poses."""
    return [
        sample
        for sample in samples
        if timestamp_s - 1e-9
        <= sample["timestamp_s"]
        <= timestamp_s + look_ahead_s + 1e-9
    ]


def _arc_coordinates(
    point: tuple[float, float],
    ego_pose: dict[str, Any],
) -> dict[str, float]:
    dx = point[0] - ego_pose["point"][0]
    dy = point[1] - ego_pose["point"][1]
    cosine = math.cos(ego_pose["heading_lcs_rad"])
    sine = math.sin(ego_pose["heading_lcs_rad"])
    longitudinal = cosine * dx + sine * dy
    lateral = -sine * dx + cosine * dy
    return {
        "longitudinal_m": longitudinal,
        "lateral_m": lateral,
        "range_m": math.hypot(dx, dy),
        "bearing_deg": math.degrees(math.atan2(lateral, longitudinal)),
    }


def _inside_arc(
    coordinates: dict[str, float],
    settings: dict[str, Any],
) -> bool:
    return (
        coordinates["longitudinal_m"] > 0.0
        and float(settings["arc_inner_radius_m"]) - 1e-9
        <= coordinates["range_m"]
        <= float(settings["arc_outer_radius_m"]) + 1e-9
        and abs(coordinates["bearing_deg"])
        <= float(settings["arc_half_angle_deg"]) + 1e-9
    )


def _side(
    coordinates: dict[str, float],
    settings: dict[str, Any],
) -> tuple[str, bool]:
    inside = _inside_arc(coordinates, settings)
    if inside:
        return "INSIDE_ARC", True
    if coordinates["longitudinal_m"] <= 0.0:
        return "BEHIND", False
    boundary = float(settings["arc_half_angle_deg"])
    hysteresis = float(settings["side_angle_hysteresis_deg"])
    if coordinates["bearing_deg"] >= boundary + hysteresis:
        return "LEFT", False
    if coordinates["bearing_deg"] <= -boundary - hysteresis:
        return "RIGHT", False
    return "OUTSIDE_ARC", False


def _projected_arc_intersection(
    point: tuple[float, float],
    velocity: tuple[float, float],
    heading_lcs_rad: float,
    future_poses: list[dict[str, Any]],
    timestamp_s: float,
    settings: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Find a same-time intersection with the future ego-centered arc."""
    speed = math.hypot(*velocity)
    if speed < float(settings["minimum_object_ground_speed_mps"]):
        return None, "static_or_slow_object"
    motion_heading = math.atan2(velocity[1], velocity[0])
    heading_difference = _axis_angle_difference_degrees(
        heading_lcs_rad, motion_heading
    )
    if heading_difference > float(settings["maximum_heading_motion_difference_deg"]):
        return None, "object_heading_motion_disagreement"

    horizon = float(settings["maximum_projected_intersection_horizon_s"])
    candidates = []
    angle_rejected = False
    for pose in future_poses:
        delta_time = float(pose["timestamp_s"]) - timestamp_s
        if delta_time < -1e-9 or delta_time > horizon + 1e-9:
            continue
        projected = (
            point[0] + velocity[0] * delta_time,
            point[1] + velocity[1] * delta_time,
        )
        coordinates = _arc_coordinates(projected, pose)
        if not _inside_arc(coordinates, settings):
            continue
        crossing_angle = math.degrees(
            math.acos(
                max(
                    -1.0,
                    min(
                        1.0,
                        abs(
                            math.cos(
                                motion_heading - pose["heading_lcs_rad"]
                            )
                        ),
                    ),
                )
            )
        )
        if crossing_angle < float(settings["minimum_crossing_angle_deg"]):
            angle_rejected = True
            continue
        candidates.append(
            {
                "projected_intersection_lcs_m": projected,
                "intersection_path_progress_m": coordinates["longitudinal_m"],
                "object_distance_to_intersection_m": speed * delta_time,
                "ego_time_to_intersection_s": delta_time,
                "object_time_to_intersection_s": delta_time,
                "time_to_intersection_difference_s": 0.0,
                "crossing_angle_deg": crossing_angle,
                "object_motion_heading_lcs_rad": motion_heading,
                "heading_motion_difference_deg": heading_difference,
                "projected_bearing_deg": coordinates["bearing_deg"],
                "projected_range_m": coordinates["range_m"],
                "projection_frame": pose["frame_index"],
            }
        )
    if candidates:
        return min(
            candidates,
            key=lambda item: (
                item["object_time_to_intersection_s"],
                abs(item["projected_bearing_deg"]),
            ),
        ), None
    if angle_rejected:
        return None, "parallel_or_shallow_motion"
    return None, "projected_path_does_not_intersect_forward_arc"


def build_object_path_crossing_relations(
    recording: dict[str, Any],
    object_relations: dict[str, Any],
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Relate reconciled OD tracks to a yaw-centered forward arc."""
    frames = recording.get("frames", [])
    object_frames = object_relations.get("frames", [])
    ego_samples = _ego_samples(recording)
    output_frames = []
    previous_by_track: dict[str, dict[str, Any]] = {}
    invalid_counts: Counter[str] = Counter()

    for position, frame in enumerate(frames):
        timestamp = frame.get("time_since_start_s")
        source_frame = object_frames[position] if position < len(object_frames) else {}
        poses = (
            _future_poses(
                ego_samples,
                float(timestamp),
                float(settings["ego_path_look_ahead_s"]),
            )
            if _finite(timestamp)
            else []
        )
        current_pose = poses[0] if poses else None
        relations = []
        for obj in source_frame.get("objects", []):
            center = obj.get("center_lcs_m") or []
            valid = (
                len(center) >= 2
                and _finite(center[0])
                and _finite(center[1])
                and _finite(timestamp)
                and current_pose is not None
                and obj.get("coordinate_frame") == "recording_lcs_m"
                and obj.get("coordinate_frame_valid") is True
            )
            point = (
                (float(center[0]), float(center[1])) if valid else (0.0, 0.0)
            )
            coordinates = (
                _arc_coordinates(point, current_pose) if valid else None
            )
            track_id = str(obj.get("track_id"))
            invalid_reason = None
            if not valid:
                invalid_reason = "invalid_object_ego_pose_or_coordinate_frame"

            side, inside = (
                _side(coordinates, settings)
                if coordinates is not None
                else ("UNKNOWN", False)
            )
            velocity_value = obj.get("object_velocity_lcs_mps")
            velocity = (
                (float(velocity_value[0]), float(velocity_value[1]))
                if isinstance(velocity_value, (list, tuple))
                and len(velocity_value) >= 2
                and _finite(velocity_value[0])
                and _finite(velocity_value[1])
                else None
            )
            heading = obj.get("heading_lcs_rad")
            heading_valid = (
                obj.get("heading_available") is True and _finite(heading)
            )
            intersection = None
            projection_rejection = None
            if valid and velocity is None:
                projection_rejection = "object_motion_unavailable"
            elif valid and not heading_valid:
                projection_rejection = "object_heading_unavailable"
            elif valid:
                intersection, projection_rejection = (
                    _projected_arc_intersection(
                        point,
                        velocity,
                        float(heading),
                        poses,
                        float(timestamp),
                        settings,
                    )
                )

            lateral_speed = None
            if velocity is not None and current_pose is not None:
                lateral_speed = (
                    -math.sin(current_pose["heading_lcs_rad"]) * velocity[0]
                    + math.cos(current_pose["heading_lcs_rad"]) * velocity[1]
                )

            previous = previous_by_track.get(track_id)
            observed_speed = None
            position_jump = False
            if previous is not None and _finite(timestamp):
                delta_time = float(timestamp) - previous["timestamp_s"]
                if (
                    0
                    < delta_time
                    <= float(settings["maximum_missing_frame_gap_s"]) + 0.25
                ):
                    observed_speed = (
                        math.dist(point, previous["center_lcs_m"]) / delta_time
                    )
                    position_jump = observed_speed > float(
                        settings["maximum_plausible_object_speed_mps"]
                    )
            if position_jump:
                invalid_reason = "impossible_position_jump"

            relation_valid = coordinates is not None and invalid_reason is None
            state = side
            if relation_valid and previous is not None and side in {"LEFT", "RIGHT"}:
                previous_bearing = previous.get("bearing_deg")
                if _finite(previous_bearing) and lateral_speed is not None:
                    approaching = abs(coordinates["bearing_deg"]) < abs(
                        float(previous_bearing)
                    )
                    fast_enough = abs(lateral_speed) >= float(
                        settings["minimum_path_normal_speed_mps"]
                    )
                    if approaching and fast_enough:
                        state = "APPROACHING_ARC"
                    elif not approaching and fast_enough:
                        state = "LEAVING_ARC"
            if side == "INSIDE_ARC":
                state = "INSIDE_ARC"
            if not relation_valid:
                state = "UNKNOWN"
                invalid_counts[invalid_reason or "unknown"] += 1

            relation = {
                "track_id": track_id,
                "source_object_ids": obj.get("source_object_ids", []),
                "source_object_id": obj.get("source_object_id"),
                "class_name": obj.get("class_name"),
                "normalized_category": obj.get("normalized_category"),
                "frame_index": frame.get("frame_index"),
                "timestamp_s": timestamp,
                "center_lcs_m": center[:2],
                "signed_lateral_distance_m": (
                    round(coordinates["lateral_m"], 4)
                    if coordinates is not None
                    else None
                ),
                "nearest_path_distance_m": (
                    round(abs(coordinates["lateral_m"]), 4)
                    if coordinates is not None
                    else None
                ),
                "longitudinal_progress_m": (
                    round(coordinates["longitudinal_m"], 4)
                    if coordinates is not None
                    else None
                ),
                "arc_range_m": (
                    round(coordinates["range_m"], 4)
                    if coordinates is not None
                    else None
                ),
                "arc_bearing_deg": (
                    round(coordinates["bearing_deg"], 4)
                    if coordinates is not None
                    else None
                ),
                "inside_path_corridor": inside,
                "inside_forward_arc": inside,
                "side": side,
                "state": state,
                "relation_valid": relation_valid,
                "invalid_reason": invalid_reason,
                "object_speed_mps": obj.get("object_speed_mps"),
                "object_velocity_lcs_mps": (
                    [round(value, 4) for value in velocity]
                    if velocity is not None
                    else None
                ),
                "velocity_source": obj.get("velocity_source"),
                "object_heading_lcs_rad": (
                    round(float(heading), 6) if heading_valid else None
                ),
                "heading_source": obj.get("heading_source"),
                "path_normal_speed_mps": (
                    round(lateral_speed, 4)
                    if lateral_speed is not None
                    else None
                ),
                "observed_ground_speed_mps": (
                    round(observed_speed, 4)
                    if observed_speed is not None
                    else None
                ),
                "projected_intersection_valid": (
                    intersection is not None and projection_rejection is None
                ),
                "projection_rejection_reason": projection_rejection,
                "projected_intersection_lcs_m": (
                    [
                        round(value, 4)
                        for value in intersection[
                            "projected_intersection_lcs_m"
                        ]
                    ]
                    if intersection is not None
                    else None
                ),
                "intersection_path_progress_m": (
                    round(intersection["intersection_path_progress_m"], 4)
                    if intersection is not None
                    else None
                ),
                "crossing_angle_deg": (
                    round(intersection["crossing_angle_deg"], 3)
                    if intersection is not None
                    else None
                ),
                "heading_motion_difference_deg": (
                    round(intersection["heading_motion_difference_deg"], 3)
                    if intersection is not None
                    else None
                ),
                "ego_time_to_intersection_s": (
                    round(intersection["ego_time_to_intersection_s"], 4)
                    if intersection is not None
                    else None
                ),
                "object_time_to_intersection_s": (
                    round(intersection["object_time_to_intersection_s"], 4)
                    if intersection is not None
                    else None
                ),
                "time_to_intersection_difference_s": (
                    round(intersection["time_to_intersection_difference_s"], 4)
                    if intersection is not None
                    else None
                ),
                "projection_frame": (
                    intersection["projection_frame"]
                    if intersection is not None
                    else None
                ),
                "ego_motion_mode": (
                    "stationary"
                    if current_pose["speed_mps"] is not None
                    and current_pose["speed_mps"]
                    < float(settings["stationary_ego_speed_threshold_mps"])
                    else "moving_or_following"
                ),
                "id_switch_associated": obj.get("id_switch_associated") is True,
            }
            relations.append(relation)
            if valid:
                previous_by_track[track_id] = {
                    "timestamp_s": float(timestamp),
                    "center_lcs_m": point,
                    "bearing_deg": coordinates["bearing_deg"],
                }
        output_frames.append(
            {
                "frame_index": frame.get("frame_index"),
                "time_since_start_s": timestamp,
                "path_start_frame": poses[0]["frame_index"] if poses else None,
                "path_end_frame": poses[-1]["frame_index"] if poses else None,
                "objects": sorted(relations, key=lambda item: item["track_id"]),
            }
        )

    return {
        "schema_version": "object-ego-forward-arc-crossing-relations-v3",
        "recording_id": recording.get("recording_id"),
        "coordinate_system": "recording_lcs_m",
        "side_sign_convention": (
            "positive bearing/lateral position is left of ego yaw"
        ),
        "event_interval_convention": "inclusive observed start/end frames",
        "arc": {
            "inner_radius_m": float(settings["arc_inner_radius_m"]),
            "outer_radius_m": float(settings["arc_outer_radius_m"]),
            "half_angle_deg": float(settings["arc_half_angle_deg"]),
            "stationary_supported": True,
            "future_pose_synchronized": True,
        },
        # Keep this alias temporarily so existing explorer consumers fail
        # gracefully while transitioning from the legacy corridor payload.
        "corridor": {
            "geometry": "forward_arc",
            "inner_radius_m": float(settings["arc_inner_radius_m"]),
            "outer_radius_m": float(settings["arc_outer_radius_m"]),
            "half_angle_deg": float(settings["arc_half_angle_deg"]),
        },
        "ego_path": [
            {
                "frame_index": sample["frame_index"],
                "timestamp_s": sample["timestamp_s"],
                "x": sample["point"][0],
                "y": sample["point"][1],
            }
            for sample in ego_samples
        ],
        "frames": output_frames,
        "invalid_relation_counts": dict(sorted(invalid_counts.items())),
    }


def summarize_object_path_crossing_relations(payload: dict[str, Any]) -> dict[str, Any]:
    valid = [
        relation
        for frame in payload.get("frames", [])
        for relation in frame.get("objects", [])
        if relation.get("relation_valid")
    ]
    candidate_tracks = {
        relation["track_id"]
        for relation in valid
        if relation.get("projected_intersection_valid")
    }
    return {
        "candidate_track_count": len(candidate_tracks),
        "valid_relation_count": len(valid),
        "inside_path_relation_count": sum(
            relation.get("inside_forward_arc") is True for relation in valid
        ),
        "projected_intersection_count": sum(
            relation.get("projected_intersection_valid") is True
            for relation in valid
        ),
        "invalid_relation_counts": payload.get("invalid_relation_counts", {}),
    }


__all__ = [
    "build_object_path_crossing_relations",
    "summarize_object_path_crossing_relations",
]
