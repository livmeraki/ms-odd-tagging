from __future__ import annotations

from collections.abc import Iterable

from .schema import SimplifiedFrameTags

INTERACTION_TAGS = {
    "waiting_for_pedestrian_to_cross",
    "crossed_by_vehicle",
    "near_multiple_vehicles",
    "accelerating_at_crosswalk",
    "stationary_at_crosswalk",
    "stopping_at_crosswalk",
    "near_long_vehicle",
    "near_multiple_pedestrians",
    "near_pedestrian_on_crosswalk",
}

KNOWN_SCENARIOS = {
    "stationary",
    "low_magnitude_speed",
    "medium_magnitude_speed",
    "high_magnitude_speed",
    "changing_lane",
    "changing_lane_to_left",
    "changing_lane_to_right",
    "changing_lane_with_lead",
    "changing_lane_with_trail",
    "starting_left_turn",
    "starting_right_turn",
    "starting_u_turn",
    "following_lane_with_lead",
    "following_lane_without_lead",
    "stopping_with_lead",
    "stopping_without_lead",
    "on_intersection",
    "on_traffic_light_intersection",
    "on_stopline_crosswalk",
    *INTERACTION_TAGS,
}


def map_scenario_labels(labels: Iterable[str]) -> SimplifiedFrameTags:
    """Map existing scenario labels into the experimental simplified frame taxonomy.

    The motion dimensions are related rather than fully independent:
    ``speed_band`` is not applicable while stationary, while a non-zero speed-band
    label is sufficient evidence that an otherwise-unclassified ego is moving.
    """
    labels = list(dict.fromkeys(labels))
    label_set = set(labels)
    out = SimplifiedFrameTags(source_scenarios=labels)

    if "stationary" in label_set:
        out.ego_motion.state = "stationary"
    elif label_set & {"stopping_with_lead", "stopping_without_lead"}:
        out.ego_motion.state = "stopping"
    elif label_set & {"starting_left_turn", "starting_right_turn", "starting_u_turn"}:
        out.ego_motion.state = "starting"

    speed_band: str | None = None
    if "low_magnitude_speed" in label_set:
        speed_band = "low"
    elif "medium_magnitude_speed" in label_set:
        speed_band = "medium"
    elif "high_magnitude_speed" in label_set:
        speed_band = "high"

    if out.ego_motion.state == "stationary":
        out.ego_motion.speed_band = None
    elif speed_band is not None:
        out.ego_motion.speed_band = speed_band
        if out.ego_motion.state == "unknown":
            out.ego_motion.state = "moving"

    if label_set & {"changing_lane", "changing_lane_to_left", "changing_lane_to_right"}:
        out.ego_maneuver.type = "lane_change"
    if "changing_lane_to_left" in label_set:
        out.ego_maneuver.direction = "left"
    elif "changing_lane_to_right" in label_set:
        out.ego_maneuver.direction = "right"

    if "starting_left_turn" in label_set:
        out.ego_maneuver.type = "turn"
        out.ego_maneuver.direction = "left"
    elif "starting_right_turn" in label_set:
        out.ego_maneuver.type = "turn"
        out.ego_maneuver.direction = "right"
    elif "starting_u_turn" in label_set:
        out.ego_maneuver.type = "u_turn"

    if label_set & {"following_lane_with_lead", "following_lane_without_lead"}:
        out.ego_maneuver.type = "lane_keeping"

    if label_set & {"following_lane_with_lead", "changing_lane_with_lead", "stopping_with_lead"}:
        out.traffic_relation.lead = "present"
    elif label_set & {"following_lane_without_lead", "stopping_without_lead"}:
        out.traffic_relation.lead = "absent"

    if "changing_lane_with_trail" in label_set:
        out.traffic_relation.trail = "present"

    if "on_intersection" in label_set:
        out.road_context.intersection = "yes"
    if "on_traffic_light_intersection" in label_set:
        out.road_context.intersection = "yes"
        out.road_context.traffic_light_intersection = "yes"
        out.road_context.traffic_light_relevant = "yes"
    if "on_stopline_crosswalk" in label_set:
        out.road_context.on_stopline_crosswalk = "yes"

    out.interaction_tags = sorted(label_set & INTERACTION_TAGS)
    out.unmapped_scenarios = sorted(label_set - KNOWN_SCENARIOS)
    return out
