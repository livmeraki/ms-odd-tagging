"""Configuration, detector registry, orchestration, adapters, and CLI."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Any
from ms_odd_tagging.features.ego_motion import extract_ego_motion_features
from ms_odd_tagging.features.object_relations import (
    build_object_relations,
    summarize_object_relations,
)
from ms_odd_tagging.features.object_path_crossing_relations import (
    build_object_path_crossing_relations,
    summarize_object_path_crossing_relations,
)
from ms_odd_tagging.features.pedestrian_crosswalk_relations import (
    build_pedestrian_crosswalk_relations,
    summarize_pedestrian_crosswalk_relations,
)
from ms_odd_tagging.features.road_feature_relations import (
    build_road_feature_relations,
    summarize_road_feature_relations,
)
from ms_odd_tagging.features.traffic_relations import (
    build_traffic_relations,
    summarize_traffic_relations,
)
from ms_odd_tagging.features.traffic_light_context import (
    build_traffic_light_context,
    summarize_traffic_light_context,
)
from .base import ScenarioDetector
from .crosswalks import CrosswalkRelationDetector
from .dynamics import JerkDetector, LateralAccelerationDetector, SPEED_BAND_ORDER, SpeedBandDetector
from .lane_changes import LaneChangeDetector
from .object_interactions import ObjectInteractionDetector
from .object_path_crossings import (
    ObjectPathCrossingDetector,
    detect_object_path_crossings,
)
from .pedestrian_crosswalks import PedestrianCrosswalkInteractionDetector
from .scenario_event import ScenarioEvent
from .traffic_interactions import TrafficInteractionDetector
from .turns import TurnDetector

PHASE1_SCENARIOS = ("stationary", "low_magnitude_speed", "medium_magnitude_speed", "high_magnitude_speed", "high_lateral_acceleration", "high_magnitude_jerk", "starting_left_turn", "starting_right_turn", "starting_low_speed_turn", "starting_high_speed_turn")
PHASE2_SCENARIOS = ("changing_lane", "changing_lane_to_left", "changing_lane_to_right")
PHASE2B_SCENARIOS = ("traversing_crosswalk", "on_stopline_crosswalk", "stationary_at_crosswalk", "stopping_at_crosswalk", "accelerating_at_crosswalk")
PHASE3A_SCENARIOS = ("near_high_speed_vehicle", "near_long_vehicle", "near_multiple_bikes", "near_multiple_motorcycle", "near_multiple_pedestrians", "near_multiple_vehicles")
PHASE3B_SCENARIOS = ("near_pedestrian_on_crosswalk", "near_pedestrian_on_crosswalk_with_ego")
PHASE3C_SCENARIOS = ("crossed_by_bike", "crossed_by_motorcycle", "crossed_by_vehicle")
PHASE4_SCENARIOS = ("following_lane_with_slow_lead", "changing_lane_with_lead", "changing_lane_with_trail", "stopping_with_lead", "stopping_without_lead", "stationary_in_traffic", "behind_bike", "behind_long_vehicle", "behind_pedestrian_on_driveable", "waiting_for_pedestrian_to_cross", "near_barrier_on_driveable")
EXPLICITLY_EXCLUDED_SCENARIOS = ("pickup_dropoff", "pickup_with_pedestrian", "dropoff_with_pedestrian")
RULE_BASED_SCENARIOS = PHASE1_SCENARIOS + PHASE2_SCENARIOS + PHASE2B_SCENARIOS + PHASE3A_SCENARIOS + PHASE3B_SCENARIOS + PHASE3C_SCENARIOS + PHASE4_SCENARIOS
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[4] / "configs" / "direct_scenarios.yaml"

def validate_config(config: dict[str, Any]) -> None:
    required = {"config_version", "detector_version", "enabled_scenarios", "feature_extraction", "speed_bands", "lateral_acceleration", "jerk", "turn_detection", "turn_speed_classification", "lane_change_detection", "road_feature_relations", "object_relations", "pedestrian_crosswalk_interactions", "object_path_crossing_interactions", "traffic_relations", "traffic_interactions", "traffic_light_context"}
    missing = sorted(required - config.keys())
    if missing: raise ValueError(f"rule configuration missing keys: {', '.join(missing)}")
    unknown = sorted(set(config["enabled_scenarios"]) - set(RULE_BASED_SCENARIOS))
    if unknown: raise ValueError(f"unknown enabled scenarios: {', '.join(unknown)}")
    previous_max: float | None = None
    for index, name in enumerate(SPEED_BAND_ORDER):
        band = config["speed_bands"].get(name)
        if not isinstance(band, dict): raise ValueError(f"speed band {name} is required")
        low, high = band["minimum_mps"], band["maximum_mps"]
        if low < 0 or (high is not None and high <= low): raise ValueError(f"speed band {name} has an impossible range")
        if previous_max is not None and low != previous_max: raise ValueError(f"speed bands are overlapping or contain a gap before {name}")
        if index == 0 and low != 0: raise ValueError("speed bands must begin at 0 m/s")
        if index < len(SPEED_BAND_ORDER) - 1 and band["maximum_inclusive"]: raise ValueError(f"speed band {name} must use an exclusive upper bound")
        if index == len(SPEED_BAND_ORDER) - 1 and high is not None: raise ValueError("high_magnitude_speed must have no upper bound")
        if band["minimum_duration_s"] < 0: raise ValueError(f"speed band {name} minimum duration cannot be negative")
        previous_max = high
    for section, entry, exit_ in (("lateral_acceleration", "entry_abs_mps2", "exit_abs_mps2"), ("jerk", "entry_abs_mps3", "exit_abs_mps3"), ("turn_detection", "entry_abs_yaw_rate_rad_s", "exit_abs_yaw_rate_rad_s")):
        if config[section][exit_] > config[section][entry] or config[section][exit_] < 0: raise ValueError(f"{section}: exit threshold must be non-negative and <= entry threshold")
    turn = config["turn_detection"]
    same_lane_threshold = turn.get(
        "same_logical_lane_minimum_accumulated_heading_change_rad"
    )
    if (
        not isinstance(same_lane_threshold, (int, float))
        or same_lane_threshold < turn["minimum_accumulated_heading_change_rad"]
    ):
        raise ValueError(
            "turn_detection: same-logical-lane heading threshold must be "
            "numeric and >= the base heading threshold"
        )
    lane_change = config["lane_change_detection"]
    for key in (
        "stable_source_duration_s",
        "stable_target_duration_s",
        "maximum_missing_gap_s",
        "maximum_temporary_lane_id_inconsistency_s",
        "minimum_event_duration_s",
        "minimum_topology_confidence",
        "minimum_geometry_confidence",
        "topology_entry_tolerance_m",
        "intersection_turn_minimum_yaw_rate_rad_s",
        "intersection_turn_minimum_accumulated_yaw_deg",
        "intersection_turn_yaw_window_s",
    ):
        value = lane_change.get(key)
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError(
                f"lane_change_detection: {key} must be a non-negative number"
            )
    if (
        lane_change["stable_source_duration_s"] == 0
        or lane_change["stable_target_duration_s"] == 0
        or lane_change["minimum_event_duration_s"] == 0
    ):
        raise ValueError(
            "lane_change_detection: stable durations and minimum event duration "
            "must be greater than zero"
        )
    if not isinstance(
        lane_change.get("suppress_lane_change_inside_intersection"), bool
    ):
        raise ValueError(
            "lane_change_detection: suppress_lane_change_inside_intersection "
            "must be a boolean"
        )
    if not isinstance(
        lane_change.get("suppress_lane_change_during_intersection_turn"), bool
    ):
        raise ValueError(
            "lane_change_detection: suppress_lane_change_during_intersection_turn "
            "must be a boolean"
        )
    if lane_change["minimum_topology_confidence"] > 1:
        raise ValueError(
            "lane_change_detection: minimum_topology_confidence must be <= 1"
        )
    if lane_change["minimum_geometry_confidence"] > 1:
        raise ValueError(
            "lane_change_detection: minimum_geometry_confidence must be <= 1"
        )
    for key in (
        "lane_change_resume_confirmation_frames",
        "intersection_exit_lane_stability_frames",
    ):
        value = lane_change.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(
                f"lane_change_detection: {key} must be a non-negative integer"
            )
    if not lane_change.get("detector_version"):
        raise ValueError("lane_change_detection: detector_version is required")
    road = config["road_feature_relations"]
    positive = (
        "ego_footprint_length_m", "ego_footprint_width_m",
        "approaching_distance_m", "stopping_region_distance_m",
        "maximum_feature_association_distance_m",
        "minimum_spatial_state_duration_s", "minimum_event_duration_s",
        "stationary_confirmation_s", "minimum_crossing_progress_m",
    )
    nonnegative = (
        "crosswalk_entry_tolerance_m", "crosswalk_exit_tolerance_m",
        "stopline_overlap_width_m", "maximum_orientation_difference_deg",
        "crossing_orientation_tolerance_deg", "maximum_missing_detection_gap_s",
        "event_pre_roll_s", "event_post_roll_s", "minimum_speed_change_mps",
        "minimum_feature_confidence", "duplicate_feature_center_distance_m",
        "duplicate_feature_minimum_bbox_iou", "association_ambiguity_margin",
        "acceleration_start_max_speed_mps", "acceleration_target_speed_mps",
    )
    for key in positive:
        if not isinstance(road.get(key), (int, float)) or road[key] <= 0:
            raise ValueError(f"road_feature_relations: {key} must be positive")
    for key in nonnegative:
        if not isinstance(road.get(key), (int, float)) or road[key] < 0:
            raise ValueError(f"road_feature_relations: {key} must be non-negative")
    if road["stopping_region_distance_m"] >= road["approaching_distance_m"]:
        raise ValueError("road_feature_relations: stopping region must be inside approaching distance")
    if road["acceleration_release_mps2"] > road["acceleration_entry_mps2"]:
        raise ValueError("road_feature_relations: acceleration release must be <= entry")
    if road["deceleration_release_mps2"] < road["deceleration_entry_mps2"]:
        raise ValueError("road_feature_relations: deceleration release must be >= entry")
    if not road.get("detector_version"):
        raise ValueError("road_feature_relations: detector_version is required")
    objects = config["object_relations"]
    positive_object_values = (
        "ego_footprint_length_m", "ego_footprint_width_m",
        "generic_proximity_radius_m", "forward_region_limit_m",
        "backward_region_limit_m", "lateral_region_limit_m",
        "long_vehicle_class_minimum_length_m",
        "long_vehicle_dimension_threshold_m", "high_speed_entry_mps",
        "high_speed_release_mps", "minimum_track_age_s",
        "minimum_event_duration_s", "maximum_tracking_association_distance_m",
        "maximum_dimension_ratio_difference", "duplicate_observation_distance_m",
        "maximum_velocity_sample_gap_s",
        "maximum_physically_plausible_object_speed_mps",
    )
    nonnegative_object_values = (
        "maximum_missing_frame_gap_s", "minimum_object_confidence",
        "event_merge_gap_s",
    )
    for key in positive_object_values:
        if not isinstance(objects.get(key), (int, float)) or objects[key] <= 0:
            raise ValueError(f"object_relations: {key} must be positive")
    for key in nonnegative_object_values:
        if not isinstance(objects.get(key), (int, float)) or objects[key] < 0:
            raise ValueError(f"object_relations: {key} must be non-negative")
    if objects["high_speed_release_mps"] > objects["high_speed_entry_mps"]:
        raise ValueError("object_relations: high-speed release must be <= entry")
    required_categories = {"vehicle", "pedestrian", "bicycle", "motorcycle"}
    if set(objects.get("class_mappings", {})) != required_categories:
        raise ValueError("object_relations: class mappings must define all normalized categories")
    for scenario in ("near_multiple_bikes", "near_multiple_motorcycle", "near_multiple_pedestrians", "near_multiple_vehicles"):
        count = objects.get("minimum_counts", {}).get(scenario)
        if not isinstance(count, int) or isinstance(count, bool) or count < 2:
            raise ValueError(f"object_relations: {scenario} minimum count must be an integer >= 2")
    velocity_filter = objects.get("velocity_filter")
    if (
        not isinstance(velocity_filter, dict)
        or velocity_filter.get("method") != "median"
        or not isinstance(velocity_filter.get("window_samples"), int)
        or velocity_filter["window_samples"] < 1
    ):
        raise ValueError("object_relations: invalid optional velocity filter")
    if not objects.get("detector_version"):
        raise ValueError("object_relations: detector_version is required")
    pedestrian_crosswalk = config["pedestrian_crosswalk_interactions"]
    for key in (
        "pedestrian_crosswalk_overlap_threshold",
        "maximum_edge_distance_m",
        "minimum_event_duration_s",
        "association_hysteresis_m",
        "same_crosswalk_association_tolerance_m",
        "overlap_ambiguity_tolerance",
    ):
        value = pedestrian_crosswalk.get(key)
        if not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(
                f"pedestrian_crosswalk_interactions: {key} must be positive"
            )
    for key in ("maximum_missing_gap_s", "event_merge_gap_s"):
        value = pedestrian_crosswalk.get(key)
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError(
                f"pedestrian_crosswalk_interactions: {key} must be non-negative"
            )
    for key in (
        "pedestrian_confidence_threshold",
        "crosswalk_confidence_threshold",
        "minimum_track_age_s",
    ):
        value = pedestrian_crosswalk.get(key)
        if value is not None and (
            not isinstance(value, (int, float)) or value < 0
        ):
            raise ValueError(
                f"pedestrian_crosswalk_interactions: {key} must be null or non-negative"
            )
    if (
        pedestrian_crosswalk["pedestrian_crosswalk_overlap_threshold"] > 1
        or pedestrian_crosswalk["overlap_ambiguity_tolerance"] > 1
    ):
        raise ValueError(
            "pedestrian_crosswalk_interactions: overlap ratios must be <= 1"
        )
    if not pedestrian_crosswalk.get("detector_version"):
        raise ValueError(
            "pedestrian_crosswalk_interactions: detector_version is required"
        )
    crossings = config["object_path_crossing_interactions"]
    positive_crossing_values = (
        "ego_path_look_ahead_s",
        "arc_inner_radius_m",
        "arc_outer_radius_m",
        "arc_half_angle_deg",
        "stationary_ego_speed_threshold_mps",
        "maximum_projected_intersection_horizon_s",
        "minimum_crossing_angle_deg",
        "maximum_heading_motion_difference_deg",
        "minimum_object_ground_speed_mps",
        "minimum_projected_intersection_confirmations",
        "side_stability_duration_s",
        "target_side_stability_duration_s",
        "minimum_crossing_duration_s",
        "minimum_arc_dwell_duration_s",
        "maximum_crossing_duration_s",
        "minimum_lateral_displacement_m",
        "minimum_path_normal_speed_mps",
        "minimum_track_age_s",
    )
    nonnegative_crossing_values = (
        "maximum_missing_frame_gap_s",
        "side_angle_hysteresis_deg",
        "event_pre_roll_s",
        "event_post_roll_s",
        "event_merge_tolerance_s",
    )
    for key in positive_crossing_values:
        value = crossings.get(key)
        if not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(
                f"object_path_crossing_interactions: {key} must be positive"
            )
    for key in nonnegative_crossing_values:
        value = crossings.get(key)
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError(
                f"object_path_crossing_interactions: {key} must be non-negative"
            )
    if (
        crossings["minimum_crossing_duration_s"]
        >= crossings["maximum_crossing_duration_s"]
    ):
        raise ValueError(
            "object_path_crossing_interactions: maximum crossing duration "
            "must exceed minimum"
        )
    if crossings["arc_inner_radius_m"] >= crossings["arc_outer_radius_m"]:
        raise ValueError(
            "object_path_crossing_interactions: arc outer radius must "
            "exceed inner radius"
        )
    if crossings["arc_half_angle_deg"] >= 90:
        raise ValueError(
            "object_path_crossing_interactions: arc half angle must be "
            "below 90 degrees"
        )
    if crossings["minimum_crossing_angle_deg"] >= 90:
        raise ValueError(
            "object_path_crossing_interactions: minimum crossing angle "
            "must be below 90 degrees"
        )
    if crossings["maximum_heading_motion_difference_deg"] > 90:
        raise ValueError(
            "object_path_crossing_interactions: heading-motion difference "
            "must be at most 90 degrees"
        )
    if not isinstance(
        crossings["minimum_projected_intersection_confirmations"], int
    ):
        raise ValueError(
            "object_path_crossing_interactions: projected intersection "
            "confirmations must be an integer"
        )
    directional_fraction = crossings.get(
        "minimum_directional_motion_fraction"
    )
    if (
        not isinstance(directional_fraction, (int, float))
        or not 0 < directional_fraction <= 1
    ):
        raise ValueError(
            "object_path_crossing_interactions: minimum directional motion "
            "fraction must be in (0, 1]"
        )
    expected_crossing_mapping = {
        "bicycle": "crossed_by_bike",
        "motorcycle": "crossed_by_motorcycle",
        "vehicle": "crossed_by_vehicle",
    }
    if crossings.get("category_to_scenario") != expected_crossing_mapping:
        raise ValueError(
            "object_path_crossing_interactions: category mapping must keep "
            "bicycle, motorcycle, and vehicle separate"
        )
    if not crossings.get("detector_version"):
        raise ValueError(
            "object_path_crossing_interactions: detector_version is required"
        )
    traffic_relations = config["traffic_relations"]
    traffic_interactions = config["traffic_interactions"]
    for section_name, section in (
        ("traffic_relations", traffic_relations),
        ("traffic_interactions", traffic_interactions),
    ):
        if not section.get("detector_version"):
            raise ValueError(f"{section_name}: detector_version is required")
        if not section.get("provenance"):
            raise ValueError(f"{section_name}: provenance is required")
    numeric_nonnegative = (
        "stationary_speed_mps", "slow_speed_mps", "same_lane_lateral_entry_m",
        "same_lane_lateral_release_m", "minimum_ahead_longitudinal_m",
        "minimum_trail_longitudinal_m", "minimum_same_lane_confidence",
        "minimum_track_age_s", "driveable_forward_m", "driveable_backward_m",
        "driveable_lateral_m",
    )
    for key in numeric_nonnegative:
        value = traffic_relations.get(key)
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"traffic_relations: {key} must be non-negative")
    if traffic_relations["same_lane_lateral_release_m"] < traffic_relations["same_lane_lateral_entry_m"]:
        raise ValueError("traffic_relations: release lateral threshold must be >= entry")
    if traffic_relations["minimum_same_lane_confidence"] > 1:
        raise ValueError("traffic_relations: minimum_same_lane_confidence must be <= 1")
    if not isinstance(traffic_relations.get("barrier_classes"), list):
        raise ValueError("traffic_relations: barrier_classes must be a list")
    numeric_interaction = (
        "maximum_lead_gap_m", "slow_lead_entry_speed_mps",
        "slow_lead_release_speed_mps", "slow_lead_entry_relative_speed_mps",
        "slow_lead_release_relative_speed_mps", "minimum_duration_s",
        "maximum_inactive_gap_s", "merge_gap_s",
        "lane_change_object_minimum_duration_s", "stopping_moving_speed_mps",
        "stopping_stopped_speed_mps", "stopping_transition_lookback_s",
        "stationary_traffic_radius_m", "stationary_traffic_lateral_m",
        "stationary_traffic_minimum_vehicle_count",
        "stationary_traffic_minimum_duration_s", "behind_bike_maximum_gap_m",
        "behind_pedestrian_maximum_gap_m", "pedestrian_corridor_lateral_m",
        "pedestrian_conflict_lateral_m", "minimum_driveable_confidence",
        "waiting_minimum_duration_s", "barrier_maximum_distance_m",
        "barrier_minimum_intrusion_m", "barrier_minimum_duration_s",
    )
    for key in numeric_interaction:
        value = traffic_interactions.get(key)
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"traffic_interactions: {key} must be non-negative")
    if traffic_interactions["slow_lead_release_speed_mps"] < traffic_interactions["slow_lead_entry_speed_mps"]:
        raise ValueError("traffic_interactions: slow lead release speed must be >= entry speed")
    if traffic_interactions["slow_lead_release_relative_speed_mps"] > traffic_interactions["slow_lead_entry_relative_speed_mps"]:
        raise ValueError("traffic_interactions: slow lead relative release must be <= entry")
    traffic_light = config["traffic_light_context"]
    if not traffic_light.get("detector_version"):
        raise ValueError("traffic_light_context: detector_version is required")
    if not traffic_light.get("provenance"):
        raise ValueError("traffic_light_context: provenance is required")
    for key in (
        "intersection_approach_distance_m",
        "minimum_intersection_topology_confidence",
        "traffic_light_lateral_entry_m",
        "traffic_light_lateral_release_m",
        "traffic_light_backward_tolerance_m",
        "maximum_stopline_traffic_light_longitudinal_gap_m",
        "minimum_relevant_traffic_light_confidence",
        "stationary_speed_mps",
        "minimum_event_duration_s",
        "maximum_missing_gap_s",
        "event_merge_gap_s",
    ):
        value = traffic_light.get(key)
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"traffic_light_context: {key} must be non-negative")
    for key in ("stopping_acceleration_mps2", "accelerating_acceleration_mps2"):
        value = traffic_light.get(key)
        if not isinstance(value, (int, float)):
            raise ValueError(f"traffic_light_context: {key} must be numeric")
    if traffic_light["traffic_light_lateral_release_m"] < traffic_light["traffic_light_lateral_entry_m"]:
        raise ValueError("traffic_light_context: release lateral threshold must be >= entry")
    if traffic_light["minimum_intersection_topology_confidence"] > 1:
        raise ValueError("traffic_light_context: topology confidence threshold must be <= 1")
    if traffic_light["minimum_relevant_traffic_light_confidence"] > 1:
        raise ValueError("traffic_light_context: relevant-light confidence threshold must be <= 1")

def load_config(path: Path | str | None = None) -> dict[str, Any]:
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    try: config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc: raise ValueError(f"{config_path}: configuration must be JSON-compatible YAML: {exc}") from exc
    validate_config(config); return config

def detector_registry() -> tuple[ScenarioDetector, ...]:
    return (
        SpeedBandDetector(),
        LateralAccelerationDetector(),
        JerkDetector(),
        TurnDetector(),
        LaneChangeDetector(),
        CrosswalkRelationDetector(),
        ObjectInteractionDetector(),
        PedestrianCrosswalkInteractionDetector(),
        ObjectPathCrossingDetector(),
        TrafficInteractionDetector(),
    )

def detect_events(
    frames: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
    frame_context: dict[int, dict[str, Any]] | None = None,
    road_feature_relations: dict[str, Any] | None = None,
    object_relations: dict[str, Any] | None = None,
    pedestrian_crosswalk_relations: dict[str, Any] | None = None,
    object_path_crossing_relations: dict[str, Any] | None = None,
    traffic_relations: dict[str, Any] | None = None,
    traffic_light_context: dict[str, Any] | None = None,
) -> tuple[list[ScenarioEvent], dict[str, Any]]:
    resolved = config or load_config(); validate_config(resolved); feature_config = resolved["feature_extraction"]
    features = extract_ego_motion_features(frames, max_sample_gap_s=feature_config["max_sample_gap_s"], heading_change_horizon_s=feature_config["heading_change_horizon_s"], jerk_mode=resolved["jerk"]["calculation_mode"])
    enabled = set(resolved["enabled_scenarios"]); events: list[ScenarioEvent] = []
    detector_debug: dict[str, Any] = {}
    for detector in detector_registry():
        if detector.output_scenarios & enabled:
            if isinstance(detector, CrosswalkRelationDetector):
                detected = detector.detect(
                    frames, features, resolved, road_feature_relations
                )
            elif isinstance(detector, ObjectInteractionDetector):
                detected = detector.detect(
                    frames, features, resolved, object_relations
                )
            elif isinstance(
                detector, PedestrianCrosswalkInteractionDetector
            ):
                detected = detector.detect(
                    frames,
                    features,
                    resolved,
                    pedestrian_crosswalk_relations,
                )
            elif isinstance(detector, ObjectPathCrossingDetector):
                detected = detector.detect(
                    frames,
                    features,
                    resolved,
                    object_path_crossing_relations,
                )
            elif isinstance(detector, TrafficInteractionDetector):
                detected = detector.detect(
                    frames,
                    features,
                    resolved,
                    traffic_relations,
                )
            else:
                detected = (
                    detector.detect(frames, features, resolved, frame_context)
                    if isinstance(detector, (TurnDetector, LaneChangeDetector))
                    else detector.detect(frames, features, resolved)
                )
            events.extend(event for event in detected if event.scenario in enabled)
            if isinstance(detector, LaneChangeDetector):
                detector_debug["lane_change_evaluation"] = getattr(
                    detector, "debug_evaluations", []
                )
    events.sort(key=lambda event: (event.start_timestamp_s, event.scenario, event.end_timestamp_s))
    quality = {"input_frame_count": len(frames), "feature_quality_issues": list(features.quality_issues), "valid_feature_counts": {name: sum(flags) for name, flags in features.validity.items()}}
    quality.update(detector_debug)
    return events, quality

def detect_recording_events(
    recording: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> tuple[list[ScenarioEvent], dict[str, Any]]:
    """Detect events with logical-lane context when ODLD geometry is available."""
    resolved = config or load_config()
    frame_context = None
    if recording.get("ld_feature_store"):
        from ms_odd_tagging.scenarios.following_lane.detector import run_following_lane

        following = run_following_lane(recording)
        frame_context = {
            frame["frame_index"]: {
                "logical_lane_id": (frame.get("ego_lane") or {}).get("logical_lane_id"),
                "left_logical_lane_id": (frame.get("left_lane") or {}).get(
                    "logical_lane_id"
                ),
                "right_logical_lane_id": (frame.get("right_lane") or {}).get(
                    "logical_lane_id"
                ),
            }
            for frame in following.get("frames", [])
        }
    recording_frames_by_index = {
        frame.get("frame_index"): frame
        for frame in recording.get("frames", [])
        if frame.get("frame_index") is not None
    }
    topology_context_found = False
    if recording_frames_by_index:
        frame_context = frame_context or {}
        for frame_index, frame in recording_frames_by_index.items():
            topology = {
                key: frame[key]
                for key in (
                    "topology_class",
                    "ego_inside_topology_polygon",
                    "distance_to_topology_polygon_m",
                    "topology_confidence",
                    "active_is_intersection",
                    "active_topology_subtype",
                    "active_topology_component",
                    "component_geometry_confidence",
                    "subtype_confidence",
                    "intersection_evidence_score",
                    "is_intersection_component",
                    "topology_subtype",
                )
                if key in frame
            }
            if topology:
                topology_context_found = True
                frame_context.setdefault(frame_index, {}).update(topology)
    if recording.get("ld_feature_store") and not topology_context_found:
        from ms_odd_tagging.ld_topology.pipeline import (
            lane_geometry_roundabout_frame_context,
        )

        inferred_topology = lane_geometry_roundabout_frame_context(recording)
        if inferred_topology:
            frame_context = frame_context or {}
            for frame_index, topology in inferred_topology.items():
                frame_context.setdefault(frame_index, {}).update(topology)
    relations = build_road_feature_relations(
        recording, resolved["road_feature_relations"]
    )
    object_relation_payload = build_object_relations(
        recording, resolved["object_relations"]
    )
    pedestrian_crosswalk_payload = build_pedestrian_crosswalk_relations(
        object_relation_payload,
        relations,
        resolved["pedestrian_crosswalk_interactions"],
        resolved["object_relations"],
        resolved["road_feature_relations"],
    )
    crossing_settings = {
        **resolved["object_path_crossing_interactions"],
        "maximum_plausible_object_speed_mps": resolved["object_relations"][
            "maximum_physically_plausible_object_speed_mps"
        ],
    }
    object_path_crossing_payload = build_object_path_crossing_relations(
        recording,
        object_relation_payload,
        crossing_settings,
    )
    events, quality = detect_events(
        recording.get("frames", []),
        resolved,
        frame_context=frame_context,
        road_feature_relations=relations,
        object_relations=object_relation_payload,
        pedestrian_crosswalk_relations=pedestrian_crosswalk_payload,
        object_path_crossing_relations=object_path_crossing_payload,
    )
    quality["logical_lane_context_available"] = frame_context is not None
    quality["road_feature_relations"] = summarize_road_feature_relations(relations)
    quality["object_relations"] = summarize_object_relations(
        object_relation_payload
    )
    quality["pedestrian_crosswalk_relations"] = (
        summarize_pedestrian_crosswalk_relations(
            pedestrian_crosswalk_payload
        )
    )
    crossing_events, crossing_rejections = detect_object_path_crossings(
        recording.get("frames", []),
        resolved,
        object_path_crossing_payload,
    )
    lane_change_events = [
        event for event in events if event.scenario == "changing_lane"
    ]
    traffic_features = extract_ego_motion_features(
        recording.get("frames", []),
        max_sample_gap_s=resolved["feature_extraction"]["max_sample_gap_s"],
        heading_change_horizon_s=resolved["feature_extraction"][
            "heading_change_horizon_s"
        ],
        jerk_mode=resolved["jerk"]["calculation_mode"],
    )
    traffic_relation_payload = build_traffic_relations(
        recording.get("frames", []),
        traffic_features,
        object_relation_payload,
        resolved,
        frame_context=frame_context,
        lane_change_events=lane_change_events,
        pedestrian_crosswalk_relations=pedestrian_crosswalk_payload,
        object_path_crossing_relations=object_path_crossing_payload,
    )
    traffic_events, traffic_quality = detect_events(
        recording.get("frames", []),
        resolved,
        frame_context=frame_context,
        road_feature_relations=relations,
        object_relations=object_relation_payload,
        pedestrian_crosswalk_relations=pedestrian_crosswalk_payload,
        object_path_crossing_relations=object_path_crossing_payload,
        traffic_relations=traffic_relation_payload,
    )
    existing_keys = {
        (event.scenario, event.start_frame, event.end_frame, event.evidence.get("physical_lane_change_event_id"))
        for event in events
    }
    events.extend(
        event
        for event in traffic_events
        if (
            event.scenario,
            event.start_frame,
            event.end_frame,
            event.evidence.get("physical_lane_change_event_id"),
        )
        not in existing_keys
    )
    events.sort(key=lambda event: (event.start_timestamp_s, event.scenario, event.end_timestamp_s))
    quality["object_path_crossing_relations"] = {
        **summarize_object_path_crossing_relations(
            object_path_crossing_payload
        ),
        "confirmed_event_count": len(crossing_events),
        "rejected_candidates": crossing_rejections,
    }
    quality["traffic_relations"] = summarize_traffic_relations(
        traffic_relation_payload
    )
    traffic_light_payload = build_traffic_light_context(
        recording,
        traffic_features,
        relations,
        traffic_relation_payload,
        resolved,
        frame_context=frame_context,
    )
    quality["traffic_light_context"] = summarize_traffic_light_context(
        traffic_light_payload
    )
    events.sort(key=lambda event: (event.start_timestamp_s, event.scenario, event.end_timestamp_s))
    quality["traffic_detector_quality"] = traffic_quality
    return events, quality

def detector_summary(config: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved = config or load_config()
    enabled = set(resolved["enabled_scenarios"])
    supported = set(RULE_BASED_SCENARIOS)
    return {
        "implemented": sorted(supported),
        "enabled": sorted(enabled),
        "unsupported": [],
        "explicitly_excluded": list(EXPLICITLY_EXCLUDED_SCENARIOS),
        "registered_detectors": [
            {
                "name": detector.scenario_name,
                "outputs": sorted(detector.output_scenarios),
            }
            for detector in detector_registry()
        ],
    }

def events_overlapping_window(events: list[ScenarioEvent] | list[dict[str, Any]], start_frame: int, end_frame: int) -> list[dict[str, Any]]:
    result = []
    for event in events:
        item = event.to_dict() if isinstance(event, ScenarioEvent) else event
        if item["end_frame"] >= start_frame and item["start_frame"] <= end_frame: result.append(item)
    return result

def compact_window_summary(events: list[dict[str, Any]], config_version: str) -> dict[str, Any]:
    keys = ("start_speed_mps", "end_speed_mps", "trigger_speed_mps", "peak_abs_lateral_acceleration_mps2", "peak_jerk_mps3", "signed_heading_delta_rad", "peak_signed_yaw_rate_rad_s", "physical_turn_event_id", "physical_lane_change_event_id", "source_logical_lane_id", "target_logical_lane_id", "direction", "transition_frame", "road_feature_event_id", "crosswalk_id", "stopline_id", "entry_frame", "exit_confirmation_frame", "stationary_relation", "final_relation", "association_confidence", "object_interaction_event_id", "object_track_ids", "source_object_ids", "peak_simultaneous_count", "minimum_footprint_distance_m", "representative_frame", "peak_object_speed_mps", "velocity_sources", "object_class", "classification_reason", "pedestrian_crosswalk_event_id", "crosswalk_ids", "pedestrian_track_ids", "pedestrian_ids", "peak_pedestrian_count", "minimum_distance_m", "ego_crosswalk_relation", "pedestrian_crosswalk_relation", "object_path_crossing_event_id", "object_track_id", "original_class", "crossing_direction", "initial_side", "final_side", "approach_start_frame", "arc_entry_frame", "arc_exit_frame", "lateral_displacement_m", "minimum_path_distance_m", "representative_path_normal_speed_mps", "arc_dwell_duration_s", "directional_motion_fraction", "projected_intersection_confirmations", "projected_intersection_lcs_m", "intersection_path_progress_m", "crossing_angle_deg", "object_heading_lcs_rad", "heading_motion_difference_deg", "ego_time_to_intersection_s", "object_time_to_intersection_s", "time_to_intersection_difference_s", "lead_object_id", "lead_source_object_ids", "lead_class", "lead_length_m", "lead_speed_mps", "lead_gap_m", "trail_object_id", "trail_source_object_ids", "trail_class", "trail_gap_m", "bike_object_id", "pedestrian_object_id", "relative_speed_mps", "time_headway_s", "ttc_s", "same_lane_confidence", "same_lane_source", "lane_change_direction", "target_lane_gap_m", "target_lane_association", "lead_persistence_frames", "lead_state", "ego_response", "relevant_vehicle_count", "nearby_vehicle_speed_min_mps", "nearby_vehicle_speed_max_mps", "stationary_duration_s", "driveable_area_confidence", "path_relation", "pedestrian_id", "crosswalk_relation", "path_conflict_geometry", "ego_response_onset_frame", "evidence_frames", "object_id", "object_subclass", "nearest_distance_m", "intrusion_m", "driveable_area_source")
    compact = [{"scenario": event["scenario"], "start_frame": event["start_frame"], "end_frame": event["end_frame"], "start_timestamp_s": event["start_timestamp_s"], "end_timestamp_s": event["end_timestamp_s"], "key_evidence": {key: event.get("evidence", {})[key] for key in keys if key in event.get("evidence", {})}} for event in events]
    return {"active_labels": sorted({event["scenario"] for event in events}), "events": compact, "rule_config_version": config_version}

def merge_scenario_events(events: list[ScenarioEvent], maximum_gap_s: float = 0.0) -> list[ScenarioEvent]:
    merged: list[ScenarioEvent] = []
    identity_keys = (
        "object_path_crossing_event_id",
        "pedestrian_crosswalk_event_id",
        "object_interaction_event_id",
        "physical_lane_change_event_id",
        "physical_turn_event_id",
        "road_feature_event_id",
    )
    def identity(event: ScenarioEvent) -> tuple[str, Any] | None:
        for key in identity_keys:
            if event.evidence.get(key) is not None:
                return key, event.evidence[key]
        return None
    for event in sorted(events, key=lambda item: (item.scenario, item.start_timestamp_s, item.end_timestamp_s)):
        same_identity = (
            identity(merged[-1]) == identity(event)
            if merged and (identity(merged[-1]) is not None or identity(event) is not None)
            else True
        )
        if merged and merged[-1].scenario == event.scenario and same_identity and event.start_timestamp_s - merged[-1].end_timestamp_s <= maximum_gap_s:
            prior = merged.pop(); end_time = max(prior.end_timestamp_s, event.end_timestamp_s)
            merged.append(ScenarioEvent(event.scenario, prior.start_frame, max(prior.end_frame, event.end_frame), prior.start_timestamp_s, end_time, round(end_time - prior.start_timestamp_s, 6), detector_version=event.detector_version, evidence={"merged_event_count": prior.evidence.get("merged_event_count", 1) + 1, "constituent_evidence": [prior.evidence, event.evidence]}))
        else: merged.append(event)
    return sorted(merged, key=lambda item: (item.start_timestamp_s, item.scenario))

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect recording-level rule-based scenario events."
    )
    parser.add_argument("canonical_json", type=Path, nargs="?")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true", help="Print detector support summary and exit.")
    parser.add_argument("--road-feature-debug-output", type=Path)
    parser.add_argument("--object-relation-debug-output", type=Path)
    parser.add_argument("--pedestrian-crosswalk-debug-output", type=Path)
    parser.add_argument("--object-path-crossing-debug-output", type=Path)
    parser.add_argument("--traffic-light-context-debug-output", type=Path)
    args = parser.parse_args()
    config = load_config(args.config)
    if args.summary:
        print(json.dumps(detector_summary(config), ensure_ascii=False, indent=2))
        return 0
    if args.canonical_json is None:
        parser.error("canonical_json is required unless --summary is used")
    canonical = json.loads(args.canonical_json.read_text(encoding="utf-8"))
    events, quality = detect_recording_events(canonical, config)
    road_debug = None
    object_debug = None
    if args.road_feature_debug_output:
        road_debug = build_road_feature_relations(
            canonical, config["road_feature_relations"]
        )
        args.road_feature_debug_output.parent.mkdir(parents=True, exist_ok=True)
        args.road_feature_debug_output.write_text(
            json.dumps(road_debug, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if args.object_relation_debug_output:
        object_debug = build_object_relations(
            canonical, config["object_relations"]
        )
        args.object_relation_debug_output.parent.mkdir(parents=True, exist_ok=True)
        args.object_relation_debug_output.write_text(
            json.dumps(object_debug, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if args.pedestrian_crosswalk_debug_output:
        road_debug = road_debug or build_road_feature_relations(
            canonical, config["road_feature_relations"]
        )
        object_debug = object_debug or build_object_relations(
            canonical, config["object_relations"]
        )
        debug = build_pedestrian_crosswalk_relations(
            object_debug,
            road_debug,
            config["pedestrian_crosswalk_interactions"],
            config["object_relations"],
            config["road_feature_relations"],
        )
        args.pedestrian_crosswalk_debug_output.parent.mkdir(
            parents=True, exist_ok=True
        )
        args.pedestrian_crosswalk_debug_output.write_text(
            json.dumps(debug, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if args.object_path_crossing_debug_output:
        object_debug = object_debug or build_object_relations(
            canonical, config["object_relations"]
        )
        crossing_settings = {
            **config["object_path_crossing_interactions"],
            "maximum_plausible_object_speed_mps": config["object_relations"][
                "maximum_physically_plausible_object_speed_mps"
            ],
        }
        debug = build_object_path_crossing_relations(
            canonical, object_debug, crossing_settings
        )
        _, debug["rejected_candidates"] = detect_object_path_crossings(
            canonical.get("frames", []), config, debug
        )
        args.object_path_crossing_debug_output.parent.mkdir(
            parents=True, exist_ok=True
        )
        args.object_path_crossing_debug_output.write_text(
            json.dumps(debug, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if args.traffic_light_context_debug_output:
        road_debug = road_debug or build_road_feature_relations(
            canonical, config["road_feature_relations"]
        )
        object_debug = object_debug or build_object_relations(
            canonical, config["object_relations"]
        )
        feature_config = config["feature_extraction"]
        features = extract_ego_motion_features(
            canonical.get("frames", []),
            max_sample_gap_s=feature_config["max_sample_gap_s"],
            heading_change_horizon_s=feature_config["heading_change_horizon_s"],
            jerk_mode=config["jerk"]["calculation_mode"],
        )
        traffic_debug = build_traffic_relations(
            canonical.get("frames", []),
            features,
            object_debug,
            config,
        )
        debug = build_traffic_light_context(
            canonical,
            features,
            road_debug,
            traffic_debug,
            config,
        )
        args.traffic_light_context_debug_output.parent.mkdir(
            parents=True, exist_ok=True
        )
        args.traffic_light_context_debug_output.write_text(
            json.dumps(debug, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    payload = {
        "schema_version": "rule-based-scenario-events-v1",
        "recording_id": canonical.get("recording_id"),
        "rule_config_version": config["config_version"],
        "rule_based_events": [event.to_dict() for event in events],
        "data_quality": quality,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(text)
    return 0

if __name__ == "__main__": raise SystemExit(main())
