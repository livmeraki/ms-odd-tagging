"""Traffic-light intersection context for future rule-based TL scenarios."""

from __future__ import annotations

import math
from typing import Any

from ms_odd_tagging.features.ego_motion import EgoMotionFeatures


TRAFFIC_LIGHT_CLASSES = {"traffic_light", "traffic_light_car", "traffic_light_ped"}
INTERSECTION_TOPOLOGY_CLASSES = {
    "x-intersection",
    "t-intersection",
    "y-intersection",
    "intersection_unknown",
}
INTERSECTION_STATES = {"outside", "approaching", "entry", "inside", "exit"}


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _number(value: Any) -> float | None:
    return float(value) if _finite(value) else None


def _confidence_label(value: float) -> str:
    if value >= 0.75:
        return "high"
    if value >= 0.45:
        return "medium"
    if value > 0.0:
        return "low"
    return "none"


def _ego_coordinates(
    point: tuple[float, float],
    position: tuple[float, float],
    heading: float,
) -> tuple[float, float]:
    dx = point[0] - position[0]
    dy = point[1] - position[1]
    cosine = math.cos(heading)
    sine = math.sin(heading)
    return cosine * dx + sine * dy, -sine * dx + cosine * dy


def _raw_traffic_lights(frame: dict[str, Any]) -> list[dict[str, Any]]:
    ego = frame.get("ego") or {}
    position = ego.get("position_lcs_m") or []
    heading = ego.get("heading_lcs_rad")
    valid_ego = (
        len(position) >= 2
        and _finite(position[0])
        and _finite(position[1])
        and _finite(heading)
    )
    ego_position = (float(position[0]), float(position[1])) if valid_ego else None
    result = []
    for raw in frame.get("objects", []):
        class_name = str(raw.get("class") or "")
        subclass = str(raw.get("subclass") or "")
        if (
            class_name.lower() not in TRAFFIC_LIGHT_CLASSES
            and subclass.lower() not in TRAFFIC_LIGHT_CLASSES
        ):
            continue
        object_position = raw.get("position_lcs_m") or []
        if (
            len(object_position) < 2
            or not _finite(object_position[0])
            or not _finite(object_position[1])
        ):
            continue
        point = (float(object_position[0]), float(object_position[1]))
        longitudinal = lateral = None
        if ego_position is not None and _finite(heading):
            longitudinal, lateral = _ego_coordinates(point, ego_position, float(heading))
        confidence = _number(raw.get("confidence"))
        object_id = raw.get("object_id")
        result.append(
            {
                "object_id": str(object_id) if object_id not in (None, "") else None,
                "class_name": class_name,
                "subclass": raw.get("subclass"),
                "position_lcs_m": [round(point[0], 3), round(point[1], 3)],
                "distance_m": (
                    round(math.hypot(point[0] - ego_position[0], point[1] - ego_position[1]), 3)
                    if ego_position is not None
                    else None
                ),
                "signed_longitudinal_m": (
                    round(longitudinal, 3) if longitudinal is not None else None
                ),
                "signed_lateral_m": round(lateral, 3) if lateral is not None else None,
                "confidence": confidence,
            }
        )
    return result


def _topology_evidence(context: dict[str, Any]) -> dict[str, Any]:
    topology_class = context.get("topology_class") or context.get("topology_subtype")
    active_subtype = context.get("active_topology_subtype")
    is_intersection_class = (
        str(topology_class) in INTERSECTION_TOPOLOGY_CLASSES
        or str(active_subtype) in INTERSECTION_TOPOLOGY_CLASSES
        or topology_class == "roundabout"
        or active_subtype == "roundabout"
    )
    active = bool(context.get("active_is_intersection"))
    inside = bool(context.get("ego_inside_topology_polygon"))
    confidence = _number(
        context.get("topology_confidence")
        if context.get("topology_confidence") is not None
        else context.get("component_geometry_confidence")
    )
    if confidence is None:
        confidence = 0.8 if active or inside or is_intersection_class else 0.0
    distance = _number(context.get("distance_to_topology_polygon_m"))
    return {
        "is_intersection": bool(is_intersection_class or active or inside),
        "inside": bool(inside or active),
        "distance_m": distance,
        "confidence": max(0.0, min(1.0, confidence)),
        "topology_class": topology_class,
        "active_topology_subtype": active_subtype,
        "source": "frame_context_topology",
    }


def _best_stopline(
    frame_relation: dict[str, Any] | None,
    traffic_lights: list[dict[str, Any]],
    settings: dict[str, Any],
) -> dict[str, Any]:
    default = {
        "id": None,
        "distance_m": None,
        "relation": "unknown",
        "before_stopline": False,
        "on_stopline": False,
        "passed_stopline": False,
        "associated_traffic_light_ids": [],
        "association_confidence": "none",
        "confidence": "none",
        "evidence": {"reason": "stopline_relations_unavailable"},
    }
    if not frame_relation:
        return default
    candidates = []
    for relation in frame_relation.get("stopline_relations", []):
        if not relation.get("relation_valid") or not relation.get("path_compatible"):
            continue
        distance = relation.get("signed_longitudinal_distance_m")
        if distance is None:
            continue
        linked_lights = []
        linked_gaps = []
        for light in traffic_lights:
            light_long = light.get("signed_longitudinal_m")
            light_lat = light.get("signed_lateral_m")
            if light_long is None or light_lat is None:
                continue
            gap = abs(float(light_long) - float(distance))
            if (
                gap <= settings["maximum_stopline_traffic_light_longitudinal_gap_m"]
                and abs(float(light_lat))
                <= settings["traffic_light_lateral_release_m"]
            ):
                linked_lights.append(light["object_id"])
                linked_gaps.append(gap)
        state = relation.get("state")
        state_score = {
            "overlapping": 0,
            "before": 1,
            "approaching": 2,
            "passed": 3,
            "far": 4,
            "unknown": 5,
        }.get(state, 5)
        candidates.append(
            {
                "relation": relation,
                "linked_lights": sorted(value for value in linked_lights if value),
                "minimum_linked_light_gap_m": min(linked_gaps) if linked_gaps else math.inf,
                "score": (
                    0 if linked_lights else 10,
                    min(linked_gaps) if linked_gaps else math.inf,
                    state_score,
                    abs(float(distance)),
                    relation.get("track_id"),
                ),
            }
        )
    if not candidates:
        return {
            **default,
            "evidence": {"reason": "no_path_compatible_stopline"},
        }
    candidates.sort(key=lambda item: item["score"])
    best = candidates[0]
    relation = best["relation"]
    state = relation.get("state", "unknown")
    association_confidence = (
        "high" if best["linked_lights"] else "medium"
    )
    return {
        "id": relation.get("track_id"),
        "distance_m": relation.get("signed_longitudinal_distance_m"),
        "relation": (
            "on_stopline"
            if state == "overlapping"
            else "before_stopline"
            if state in {"approaching", "before"}
            else "passed_stopline"
            if state == "passed"
            else state
        ),
        "before_stopline": state in {"approaching", "before"},
        "on_stopline": state == "overlapping",
        "passed_stopline": state == "passed",
        "associated_traffic_light_ids": best["linked_lights"],
        "association_confidence": association_confidence,
        "confidence": association_confidence,
        "evidence": {
            "state": state,
            "path_compatible": relation.get("path_compatible"),
            "orientation_compatible": relation.get("orientation_compatible"),
            "corridor_compatible": relation.get("corridor_compatible"),
            "observed_this_frame": relation.get("observed_this_frame"),
            "candidate_count": len(candidates),
        },
    }


def _associate_traffic_lights(
    traffic_lights: list[dict[str, Any]],
    stopline: dict[str, Any],
    topology: dict[str, Any],
    settings: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    associated = []
    relevant_ids = []
    for light in traffic_lights:
        reasons = []
        confidence = 0.0
        longitudinal = light.get("signed_longitudinal_m")
        lateral = light.get("signed_lateral_m")
        if longitudinal is not None and lateral is not None:
            ahead = float(longitudinal) >= -settings["traffic_light_backward_tolerance_m"]
            corridor = abs(float(lateral)) <= settings["traffic_light_lateral_entry_m"]
            release_corridor = abs(float(lateral)) <= settings["traffic_light_lateral_release_m"]
            if ahead and corridor:
                confidence += 0.45
                reasons.append("ego_forward_path_corridor")
            elif ahead and release_corridor:
                confidence += 0.25
                reasons.append("ego_forward_path_release_corridor")
        if topology["is_intersection"]:
            confidence += 0.25 * topology["confidence"]
            reasons.append("intersection_topology_context")
        if light.get("object_id") in set(stopline.get("associated_traffic_light_ids", [])):
            confidence += 0.35
            reasons.append("stopline_longitudinal_alignment")
        if (
            stopline.get("id")
            and longitudinal is not None
            and stopline.get("distance_m") is not None
            and abs(float(longitudinal) - float(stopline["distance_m"]))
            <= settings["maximum_stopline_traffic_light_longitudinal_gap_m"]
        ):
            confidence += 0.15
            reasons.append("near_relevant_stopline")
        confidence = max(0.0, min(1.0, confidence))
        item = {
            **light,
            "association_confidence": round(confidence, 3),
            "association_confidence_label": _confidence_label(confidence),
            "association_reasons": reasons or ["not_path_or_stopline_associated"],
            "relevant": confidence >= settings["minimum_relevant_traffic_light_confidence"],
        }
        associated.append(item)
        if item["relevant"] and item.get("object_id"):
            relevant_ids.append(item["object_id"])
    return associated, sorted(relevant_ids)


def _motion_state(
    index: int,
    features: EgoMotionFeatures,
    settings: dict[str, Any],
) -> dict[str, Any]:
    speed = features.speed_mps[index]
    acceleration = features.longitudinal_acceleration_mps2[index]
    stationary = speed is not None and speed < settings["stationary_speed_mps"]
    stopping = acceleration is not None and acceleration <= settings["stopping_acceleration_mps2"]
    accelerating = (
        acceleration is not None
        and acceleration >= settings["accelerating_acceleration_mps2"]
    )
    onset = None
    if stopping and (
        index == 0
        or features.longitudinal_acceleration_mps2[index - 1] is None
        or features.longitudinal_acceleration_mps2[index - 1]
        > settings["stopping_acceleration_mps2"]
    ):
        onset = "stopping_onset"
    elif accelerating and (
        index == 0
        or features.longitudinal_acceleration_mps2[index - 1] is None
        or features.longitudinal_acceleration_mps2[index - 1]
        < settings["accelerating_acceleration_mps2"]
    ):
        onset = "acceleration_onset"
    return {
        "speed_mps": speed,
        "acceleration_mps2": acceleration,
        "stationary": bool(stationary),
        "stopping": bool(stopping),
        "accelerating": bool(accelerating),
        "temporal_state": onset or (
            "stationary" if stationary else "stopping" if stopping else "accelerating" if accelerating else "moving_or_unknown"
        ),
        "evidence": {
            "source": "ego_motion_features",
            "stationary_speed_mps": settings["stationary_speed_mps"],
            "stopping_acceleration_mps2": settings["stopping_acceleration_mps2"],
            "accelerating_acceleration_mps2": settings["accelerating_acceleration_mps2"],
        },
    }


def _lead_state(traffic_frame: dict[str, Any] | None) -> dict[str, Any]:
    lead = (traffic_frame or {}).get("primary_lead")
    if not lead:
        return {
            "exists": False,
            "object_id": None,
            "longitudinal_distance_m": None,
            "lateral_distance_m": None,
            "same_path_compatible": False,
            "confidence": "none",
            "evidence": {"reason": "traffic_relations_primary_lead_absent"},
        }
    confidence_value = lead.get("same_lane_confidence")
    confidence = _confidence_label(float(confidence_value or 0.0))
    object_id = lead.get("track_id") or lead.get("source_object_id")
    return {
        "exists": True,
        "object_id": object_id,
        "source_object_ids": lead.get("source_object_ids", []),
        "longitudinal_distance_m": lead.get("longitudinal_gap_m"),
        "lateral_distance_m": lead.get("lateral_offset_m"),
        "same_path_compatible": bool(lead.get("same_lane")),
        "confidence": confidence,
        "evidence": {
            "source": "traffic_relations.primary_lead",
            "same_lane_confidence": confidence_value,
            "same_lane_source": lead.get("same_lane_source"),
            "track_age_s": lead.get("track_age_s"),
        },
    }


def _base_intersection_state(
    topology: dict[str, Any],
    stopline: dict[str, Any],
    has_relevant_light: bool,
    settings: dict[str, Any],
) -> str:
    if topology["inside"]:
        return "inside"
    if (
        topology["is_intersection"]
        and topology["distance_m"] is not None
        and topology["distance_m"] <= settings["intersection_approach_distance_m"]
    ):
        return "approaching"
    if (
        has_relevant_light
        and stopline.get("relation") in {"before_stopline", "on_stopline"}
        and (
            stopline.get("distance_m") is None
            or abs(float(stopline["distance_m"]))
            <= settings["intersection_approach_distance_m"]
        )
    ):
        return "approaching"
    return "outside"


def _with_entry_exit(states: list[str]) -> list[str]:
    result = list(states)
    for index, state in enumerate(states):
        previous = states[index - 1] if index > 0 else "outside"
        next_state = states[index + 1] if index + 1 < len(states) else "outside"
        if state == "inside" and previous in {"outside", "approaching", "exit"}:
            result[index] = "entry"
        elif state == "outside" and previous in {"inside", "entry"}:
            result[index] = "exit"
        elif state == "inside" and next_state != "inside":
            result[index] = "exit"
    return result


def build_traffic_light_context(
    recording: dict[str, Any],
    features: EgoMotionFeatures,
    road_feature_relations: dict[str, Any] | None,
    traffic_relations: dict[str, Any] | None,
    config: dict[str, Any],
    *,
    frame_context: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build traffic-light evidence without emitting final scenario tags."""
    settings = config["traffic_light_context"]
    road_by_frame = {
        item["frame_index"]: item for item in (road_feature_relations or {}).get("frames", [])
    }
    traffic_by_frame = {
        item["frame_index"]: item for item in (traffic_relations or {}).get("frames", [])
    }
    rows = []
    base_states = []
    for index, frame in enumerate(recording.get("frames", [])):
        frame_index = features.frame_index[index]
        context = (frame_context or {}).get(frame_index, {})
        topology = _topology_evidence(context)
        raw_lights = _raw_traffic_lights(frame)
        stopline = _best_stopline(
            road_by_frame.get(frame_index), raw_lights, settings
        )
        lights, relevant_ids = _associate_traffic_lights(
            raw_lights, stopline, topology, settings
        )
        has_relevant_light = bool(relevant_ids)
        is_tl_intersection = bool(
            topology["is_intersection"]
            and topology["confidence"]
            >= settings["minimum_intersection_topology_confidence"]
            and has_relevant_light
        )
        confidence = 0.0
        if is_tl_intersection:
            confidence = min(
                1.0,
                0.55 * topology["confidence"]
                + 0.45
                * max(
                    light["association_confidence"]
                    for light in lights
                    if light["object_id"] in relevant_ids
                ),
            )
        base_state = _base_intersection_state(
            topology, stopline, has_relevant_light, settings
        )
        base_states.append(base_state)
        rows.append(
            {
                "frame_index": frame_index,
                "timestamp_s": features.timestamp_s[index],
                "is_traffic_light_intersection": is_tl_intersection,
                "confidence": round(confidence, 3),
                "confidence_label": _confidence_label(confidence),
                "traffic_lights": lights,
                "relevant_traffic_light_ids": relevant_ids,
                "stopline": stopline,
                "ego_motion": _motion_state(index, features, settings),
                "lead": _lead_state(traffic_by_frame.get(frame_index)),
                "intersection_state": base_state,
                "evidence": {
                    "topology": topology,
                    "traffic_light_count": len(raw_lights),
                    "relevant_traffic_light_count": len(relevant_ids),
                    "classification_guard": "requires_intersection_topology_and_path_associated_traffic_light",
                },
            }
        )
    states = _with_entry_exit(base_states)
    for row, state in zip(rows, states):
        row["intersection_state"] = state
    return {
        "schema_version": "traffic-light-context-v1",
        "recording_id": recording.get("recording_id"),
        "coordinate_system": "recording_lcs_m_and_ego_aligned_lcs",
        "frames": rows,
    }


def summarize_traffic_light_context(payload: dict[str, Any]) -> dict[str, Any]:
    frames = payload.get("frames", [])
    state_counts = {
        state: sum(frame.get("intersection_state") == state for frame in frames)
        for state in sorted(INTERSECTION_STATES)
    }
    return {
        "frame_count": len(frames),
        "traffic_light_intersection_frame_count": sum(
            bool(frame.get("is_traffic_light_intersection")) for frame in frames
        ),
        "relevant_traffic_light_frame_count": sum(
            bool(frame.get("relevant_traffic_light_ids")) for frame in frames
        ),
        "stopline_associated_frame_count": sum(
            bool((frame.get("stopline") or {}).get("id")) for frame in frames
        ),
        "lead_frame_count": sum(
            bool((frame.get("lead") or {}).get("exists")) for frame in frames
        ),
        "intersection_state_counts": state_counts,
    }


__all__ = ["build_traffic_light_context", "summarize_traffic_light_context"]
