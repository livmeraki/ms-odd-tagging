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

LANE_FOLLOW_SCENARIOS = {
    # Current rule-based detector output.
    "following_lane_with_slow_lead",
    # Legacy/compatibility labels accepted by older exports.
    "following_lane_with_lead",
    "following_lane_without_lead",
}

LANE_CHANGE_SCENARIOS = {
    "changing_lane",
    "changing_lane_to_left",
    "changing_lane_to_right",
}

TURN_SCENARIOS = {"starting_left_turn", "starting_right_turn"}

DRIVING_EVIDENCE_SCENARIOS = {
    "stationary",
    "low_magnitude_speed",
    "medium_magnitude_speed",
    "high_magnitude_speed",
    "stopping_with_lead",
    "stopping_without_lead",
    *LANE_FOLLOW_SCENARIOS,
}

KNOWN_SCENARIOS = {
    "stationary",
    "low_magnitude_speed",
    "medium_magnitude_speed",
    "high_magnitude_speed",
    *LANE_CHANGE_SCENARIOS,
    "changing_lane_with_lead",
    *TURN_SCENARIOS,
    "starting_u_turn",
    *LANE_FOLLOW_SCENARIOS,
    "stopping_with_lead",
    "stopping_without_lead",
    "on_intersection",
    "on_traffic_light_intersection",
    "on_stopline_crosswalk",
    *INTERACTION_TAGS,
}


def map_scenario_labels(labels: Iterable[str]) -> SimplifiedFrameTags:
    """Map detector labels into the simplified frame taxonomy.

    Maneuver mapping is intentionally closed and priority-based:
    U-turn > turn > lane change > lane keeping. Lane keeping is the normal
    road-driving fallback whenever the ego has motion/driving evidence and no
    explicit lateral maneuver is active.

    The trail relation is intentionally not mapped because no supported trail
    detector is currently part of the simplified evaluation.
    """
    labels = list(dict.fromkeys(labels))
    label_set = set(labels)
    out = SimplifiedFrameTags(source_scenarios=labels)

    # Longitudinal motion.
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

    # Lateral maneuver. Explicit maneuvers always beat lane keeping.
    if "starting_u_turn" in label_set:
        out.ego_maneuver.type = "u_turn"
        out.ego_maneuver.direction = None
    elif "starting_left_turn" in label_set:
        out.ego_maneuver.type = "turn"
        out.ego_maneuver.direction = "left"
    elif "starting_right_turn" in label_set:
        out.ego_maneuver.type = "turn"
        out.ego_maneuver.direction = "right"
    elif label_set & LANE_CHANGE_SCENARIOS:
        out.ego_maneuver.type = "lane_change"
        if "changing_lane_to_left" in label_set:
            out.ego_maneuver.direction = "left"
        elif "changing_lane_to_right" in label_set:
            out.ego_maneuver.direction = "right"
    elif label_set & DRIVING_EVIDENCE_SCENARIOS:
        # Simplified semantics: ordinary road driving with no active lateral
        # maneuver is lane keeping, even when a physical lane ID is unavailable.
        out.ego_maneuver.type = "lane_keeping"
        out.ego_maneuver.direction = "straight"

    # Lead relation. The current detector emits following_lane_with_slow_lead.
    if label_set & {
        "following_lane_with_slow_lead",
        "following_lane_with_lead",
        "changing_lane_with_lead",
        "stopping_with_lead",
    }:
        out.traffic_relation.lead = "present"
    elif label_set & {"following_lane_without_lead", "stopping_without_lead"}:
        out.traffic_relation.lead = "absent"

    # traffic_relation.trail remains unknown and is excluded from F1 scoring.

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
