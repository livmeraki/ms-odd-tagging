"""Shared ego-relative traffic relations for advanced motional tags."""

from __future__ import annotations

import math
from typing import Any

from ms_odd_tagging.features.ego_motion import EgoMotionFeatures


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _object_speed_state(speed: float | None, settings: dict[str, Any]) -> str:
    if speed is None:
        return "unknown"
    if speed < settings["stationary_speed_mps"]:
        return "stationary"
    if speed < settings["slow_speed_mps"]:
        return "slow"
    return "moving"


def _ego_motion_state(speed: float | None, acceleration: float | None, settings: dict[str, Any]) -> str:
    if speed is None:
        return "unknown"
    if speed < settings["stationary_speed_mps"]:
        return "stationary"
    if acceleration is not None and acceleration <= settings["yield_deceleration_mps2"]:
        return "decelerating"
    return "moving"


def _relative_velocity(
    relation: dict[str, Any],
    ego_velocity: Any,
    ego_heading: Any,
) -> tuple[float | None, str]:
    object_velocity = relation.get("object_velocity_lcs_mps")
    if (
        not isinstance(object_velocity, (list, tuple))
        or len(object_velocity) < 2
        or not _finite(object_velocity[0])
        or not _finite(object_velocity[1])
    ):
        return None, "object_velocity_unavailable"
    if (
        not isinstance(ego_velocity, (list, tuple))
        or len(ego_velocity) < 2
        or not _finite(ego_velocity[0])
        or not _finite(ego_velocity[1])
        or not _finite(ego_heading)
    ):
        return None, "ego_velocity_unavailable"
    cosine, sine = math.cos(float(ego_heading)), math.sin(float(ego_heading))
    object_longitudinal = cosine * float(object_velocity[0]) + sine * float(object_velocity[1])
    ego_longitudinal = cosine * float(ego_velocity[0]) + sine * float(ego_velocity[1])
    return object_longitudinal - ego_longitudinal, relation.get("velocity_source", "unknown")


def _same_lane_confidence(relation: dict[str, Any], settings: dict[str, Any]) -> tuple[float | None, str]:
    if not relation.get("valid_spatial_relation"):
        return None, "invalid_spatial_relation"
    lateral = relation.get("signed_lateral_m")
    if lateral is None:
        return None, "missing_lateral_position"
    abs_lateral = abs(float(lateral))
    entry = float(settings["same_lane_lateral_entry_m"])
    release = float(settings["same_lane_lateral_release_m"])
    if abs_lateral <= entry:
        return 1.0, "ego_aligned_corridor"
    if abs_lateral <= release:
        return 0.6, "ego_aligned_corridor_release_band"
    return 0.0, "outside_ego_aligned_corridor"


def _time_headway(longitudinal_gap: float | None, ego_speed: float | None) -> float | None:
    if longitudinal_gap is None or ego_speed is None or ego_speed <= 0.1:
        return None
    return round(max(0.0, longitudinal_gap) / ego_speed, 4)


def _ttc(longitudinal_gap: float | None, relative_speed_mps: float | None) -> float | None:
    if longitudinal_gap is None or relative_speed_mps is None:
        return None
    closing_speed = -relative_speed_mps
    if longitudinal_gap <= 0 or closing_speed <= 0.1:
        return None
    return round(longitudinal_gap / closing_speed, 4)


def _driveable_confidence(longitudinal: float | None, lateral: float | None, settings: dict[str, Any]) -> tuple[float | None, str]:
    if longitudinal is None or lateral is None:
        return None, "missing_position"
    if (
        -settings["driveable_backward_m"] <= longitudinal <= settings["driveable_forward_m"]
        and abs(lateral) <= settings["driveable_lateral_m"]
    ):
        return 0.7, "ego_aligned_driveable_corridor_fallback"
    return 0.0, "outside_ego_aligned_driveable_corridor"


def _raw_barriers(frame: dict[str, Any], settings: dict[str, Any]) -> list[dict[str, Any]]:
    classes = {str(value).lower() for value in settings["barrier_classes"]}
    subclasses = {str(value).lower() for value in settings["barrier_subclasses"]}
    result = []
    ego = frame.get("ego") or {}
    position = ego.get("position_lcs_m") or []
    heading = ego.get("heading_lcs_rad")
    if len(position) < 2 or not _finite(position[0]) or not _finite(position[1]) or not _finite(heading):
        return result
    cosine, sine = math.cos(float(heading)), math.sin(float(heading))
    for raw in frame.get("objects", []):
        class_name = str(raw.get("class") or "")
        subclass = str(raw.get("subclass") or "")
        if class_name.lower() not in classes and subclass.lower() not in subclasses:
            continue
        object_position = raw.get("position_lcs_m") or []
        if len(object_position) < 2 or not _finite(object_position[0]) or not _finite(object_position[1]):
            continue
        dx = float(object_position[0]) - float(position[0])
        dy = float(object_position[1]) - float(position[1])
        longitudinal = cosine * dx + sine * dy
        lateral = -sine * dx + cosine * dy
        driveable_confidence, driveable_source = _driveable_confidence(longitudinal, lateral, settings)
        result.append(
            {
                "object_id": str(raw.get("object_id")) if raw.get("object_id") not in (None, "") else None,
                "class_name": class_name,
                "subclass": raw.get("subclass"),
                "signed_longitudinal_m": round(longitudinal, 3),
                "signed_lateral_m": round(lateral, 3),
                "center_distance_m": round(math.hypot(dx, dy), 3),
                "driveable_area_confidence": driveable_confidence,
                "driveable_area_source": driveable_source,
                "intrusion_m": max(0.0, settings["driveable_lateral_m"] - abs(lateral)),
            }
        )
    return result


def build_traffic_relations(
    frames: list[dict[str, Any]],
    features: EgoMotionFeatures,
    object_relations: dict[str, Any] | None,
    config: dict[str, Any],
    *,
    frame_context: dict[int, dict[str, Any]] | None = None,
    lane_change_events: list[Any] | None = None,
    pedestrian_crosswalk_relations: dict[str, Any] | None = None,
    object_path_crossing_relations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build reusable per-frame traffic state without taxonomy decisions."""
    settings = config["traffic_relations"]
    object_by_frame = {
        item["frame_index"]: item for item in (object_relations or {}).get("frames", [])
    }
    pedestrian_by_frame = {
        item["frame_index"]: item for item in (pedestrian_crosswalk_relations or {}).get("frames", [])
    }
    crossing_by_frame = {
        item["frame_index"]: item for item in (object_path_crossing_relations or {}).get("frames", [])
    }
    lane_change_by_frame: dict[int, list[dict[str, Any]]] = {}
    for event in lane_change_events or []:
        if getattr(event, "scenario", None) != "changing_lane":
            continue
        for frame_index in features.frame_index:
            if event.start_frame <= frame_index <= event.end_frame:
                lane_change_by_frame.setdefault(frame_index, []).append(event.to_dict())

    rows = []
    for position, frame in enumerate(frames):
        frame_index = features.frame_index[position]
        ego = frame.get("ego") or {}
        ego_speed = features.speed_mps[position]
        ego_accel = features.longitudinal_acceleration_mps2[position]
        context = (frame_context or {}).get(frame_index, {})
        objects = []
        primary_lead = None
        primary_trail = None
        for relation in object_by_frame.get(frame_index, {}).get("objects", []):
            same_lane_confidence, same_lane_source = _same_lane_confidence(relation, settings)
            longitudinal = relation.get("signed_longitudinal_m")
            lateral = relation.get("signed_lateral_m")
            relative_speed, velocity_source = _relative_velocity(
                relation, ego.get("velocity_lcs_mps"), ego.get("heading_lcs_rad")
            )
            driveable_confidence, driveable_source = _driveable_confidence(
                longitudinal, lateral, settings
            )
            is_same_lane = (
                same_lane_confidence is not None
                and same_lane_confidence + 1e-9 >= settings["minimum_same_lane_confidence"]
            )
            item = {
                "track_id": relation["track_id"],
                "source_object_ids": relation.get("source_object_ids", []),
                "source_object_id": relation.get("source_object_id"),
                "class_name": relation.get("class_name"),
                "subclass": relation.get("subclass"),
                "normalized_category": relation.get("normalized_category"),
                "normalized_categories": relation.get("normalized_categories", []),
                "dimensions_m": relation.get("dimensions_m"),
                "object_speed_mps": relation.get("object_speed_mps"),
                "object_motion_state": _object_speed_state(relation.get("object_speed_mps"), settings),
                "signed_longitudinal_m": longitudinal,
                "signed_lateral_m": lateral,
                "longitudinal_gap_m": longitudinal,
                "lateral_offset_m": lateral,
                "relative_speed_mps": round(relative_speed, 4) if relative_speed is not None else None,
                "closing_speed_mps": round(-relative_speed, 4) if relative_speed is not None else None,
                "time_headway_s": _time_headway(longitudinal, ego_speed),
                "ttc_s": _ttc(longitudinal, relative_speed),
                "same_lane_confidence": same_lane_confidence,
                "same_lane_source": same_lane_source,
                "same_lane": is_same_lane,
                "ahead": longitudinal is not None and float(longitudinal) > settings["minimum_ahead_longitudinal_m"],
                "behind": longitudinal is not None and float(longitudinal) < -settings["minimum_trail_longitudinal_m"],
                "driveable_area_confidence": driveable_confidence,
                "driveable_area_source": driveable_source,
                "track_age_s": relation.get("track_age_s"),
                "long_vehicle": relation.get("long_vehicle"),
                "long_vehicle_reason": relation.get("long_vehicle_reason"),
                "velocity_source": velocity_source,
                "data_quality_flags": [
                    flag
                    for flag, active in (
                        ("low_same_lane_confidence", not is_same_lane),
                        ("object_velocity_unavailable", relative_speed is None),
                        ("insufficient_track_history", (relation.get("track_age_s") or 0.0) < settings["minimum_track_age_s"]),
                    )
                    if active
                ],
            }
            objects.append(item)
            if item["ahead"] and is_same_lane and relation.get("normalized_category") in {"vehicle", "bicycle", "motorcycle"}:
                if primary_lead is None or float(item["longitudinal_gap_m"]) < float(primary_lead["longitudinal_gap_m"]):
                    primary_lead = item
            if item["behind"] and is_same_lane and relation.get("normalized_category") in {"vehicle", "bicycle", "motorcycle"}:
                if primary_trail is None or abs(float(item["longitudinal_gap_m"])) < abs(float(primary_trail["longitudinal_gap_m"])):
                    primary_trail = item

        rows.append(
            {
                "frame_index": frame_index,
                "timestamp_s": features.timestamp_s[position],
                "ego_lane": context.get("logical_lane_id"),
                "left_lane": context.get("left_logical_lane_id"),
                "right_lane": context.get("right_logical_lane_id"),
                "ego_speed_mps": ego_speed,
                "ego_acceleration_mps2": ego_accel,
                "ego_motion_state": _ego_motion_state(ego_speed, ego_accel, settings),
                "lane_change_events": lane_change_by_frame.get(frame_index, []),
                "lane_change_state": "changing_lane" if lane_change_by_frame.get(frame_index) else "not_changing_lane",
                "lane_change_direction": (
                    lane_change_by_frame[frame_index][0]["evidence"].get("direction")
                    if lane_change_by_frame.get(frame_index)
                    else None
                ),
                "primary_lead": primary_lead,
                "primary_trail": primary_trail,
                "objects": objects,
                "pedestrian_crosswalk_interactions": pedestrian_by_frame.get(frame_index, {}).get("interactions", []),
                "path_conflict_objects": crossing_by_frame.get(frame_index, {}).get("objects", []),
                "barriers": _raw_barriers(frame, settings),
            }
        )
    return {
        "schema_version": "traffic-relations-v1",
        "coordinate_system": "ego_aligned_lcs_with_lane_context_when_available",
        "frames": rows,
    }


def summarize_traffic_relations(payload: dict[str, Any]) -> dict[str, Any]:
    frames = payload.get("frames", [])
    return {
        "frame_count": len(frames),
        "primary_lead_frame_count": sum(bool(frame.get("primary_lead")) for frame in frames),
        "primary_trail_frame_count": sum(bool(frame.get("primary_trail")) for frame in frames),
        "lane_change_frame_count": sum(frame.get("lane_change_state") == "changing_lane" for frame in frames),
        "barrier_candidate_frame_count": sum(bool(frame.get("barriers")) for frame in frames),
    }


__all__ = ["build_traffic_relations", "summarize_traffic_relations"]
