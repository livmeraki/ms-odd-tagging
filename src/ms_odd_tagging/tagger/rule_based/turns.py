"""Reusable physical turn detection and derived direction/speed labels."""
from __future__ import annotations
import math
from typing import Any
from ms_odd_tagging.features.ego_motion import EgoMotionFeatures
from .event_segmentation import segment_signal
from .scenario_event import ScenarioEvent

class TurnDetector:
    scenario_name = "turns"
    required_features = frozenset({"unwrapped_heading_rad", "yaw_rate_rad_s", "speed_mps"})
    output_scenarios = frozenset({"starting_left_turn", "starting_right_turn", "starting_low_speed_turn", "starting_high_speed_turn"})
    def detect(
        self,
        frames: list[dict[str, Any]],
        features: EgoMotionFeatures,
        config: dict[str, Any],
        frame_context: dict[int, dict[str, Any]] | None = None,
    ) -> list[ScenarioEvent]:
        rule, speed_rule = config["turn_detection"], config["turn_speed_classification"]
        magnitude = [abs(value) if value is not None else None for value in features.yaw_rate_rad_s]
        candidates = segment_signal(magnitude, features.timestamp_s, onset_threshold=rule["entry_abs_yaw_rate_rad_s"], release_threshold=rule["exit_abs_yaw_rate_rad_s"], minimum_duration_s=rule["minimum_duration_s"], maximum_inactive_gap_s=rule["maximum_inactive_gap_s"], pre_roll_s=rule["pre_trigger_context_s"], post_roll_s=rule["post_trigger_context_s"])
        events: list[ScenarioEvent] = []; physical_id = 0
        for interval in candidates:
            trigger_start, trigger_end = interval.trigger_start_index, interval.trigger_end_index
            start_heading, end_heading = features.unwrapped_heading_rad[trigger_start], features.unwrapped_heading_rad[trigger_end]
            if start_heading is None or end_heading is None: continue
            heading_delta = end_heading - start_heading
            trigger_frame_indexes = features.frame_index[trigger_start : trigger_end + 1]
            trigger_contexts = [
                (frame_context or {}).get(frame_index, {})
                for frame_index in trigger_frame_indexes
            ]
            logical_lane_ids = [
                context.get("logical_lane_id") for context in trigger_contexts
            ]
            lane_context_complete = bool(logical_lane_ids) and all(logical_lane_ids)
            same_logical_lane = (
                lane_context_complete and len(set(logical_lane_ids)) == 1
            )
            required_heading_change = float(
                rule[
                    "same_logical_lane_minimum_accumulated_heading_change_rad"
                    if same_logical_lane
                    else "minimum_accumulated_heading_change_rad"
                ]
            )
            if abs(heading_delta) < required_heading_change: continue
            physical_id += 1
            positive_is_left = rule["positive_heading_change_direction"] == "left"
            is_left = heading_delta > 0 if positive_is_left else heading_delta < 0
            direction_label = "starting_left_turn" if is_left else "starting_right_turn"
            trigger_speed = features.speed_mps[trigger_start]
            speed_label = None
            if trigger_speed is not None and math.isfinite(trigger_speed) and trigger_speed >= 0:
                speed_label = "starting_high_speed_turn" if trigger_speed >= speed_rule["high_speed_minimum_mps"] else "starting_low_speed_turn"
            yaw_values = [features.yaw_rate_rad_s[i] for i in interval.active_indices if features.yaw_rate_rad_s[i] is not None]
            topology_classes = sorted(
                set(
                    context.get("topology_class")
                    for context in trigger_contexts
                    if context.get("topology_class")
                )
            )
            topology_confidences = [
                float(context.get("topology_confidence") or 0.0)
                for context in trigger_contexts
            ]
            intersection_active = any(
                bool(context.get("ego_inside_topology_polygon"))
                and context.get("topology_class")
                in {"x-intersection", "t-intersection", "y-intersection", "roundabout"}
                for context in trigger_contexts
            )
            evidence = {"physical_turn_event_id": f"turn-{physical_id:04d}", "trigger_start_frame": features.frame_index[trigger_start], "trigger_end_frame": features.frame_index[trigger_end], "trigger_speed_mps": trigger_speed, "turn_speed_classification_mode": "trigger_frame_speed", "signed_heading_delta_rad": heading_delta, "accumulated_yaw_change_deg": math.degrees(heading_delta), "peak_signed_yaw_rate_rad_s": max(yaw_values, key=abs), "direction_sign_convention": f"positive_heading_change_is_{rule['positive_heading_change_direction']}", "entry_abs_yaw_rate_rad_s": rule["entry_abs_yaw_rate_rad_s"], "exit_abs_yaw_rate_rad_s": rule["exit_abs_yaw_rate_rad_s"], "minimum_accumulated_heading_change_rad": required_heading_change, "base_minimum_accumulated_heading_change_rad": rule["minimum_accumulated_heading_change_rad"], "same_logical_lane_minimum_accumulated_heading_change_rad": rule["same_logical_lane_minimum_accumulated_heading_change_rad"], "logical_lane_context_complete": lane_context_complete, "same_logical_lane": same_logical_lane, "logical_lane_ids": sorted(set(lane_id for lane_id in logical_lane_ids if lane_id)), "topology_class": topology_classes[-1] if len(topology_classes) == 1 else topology_classes, "topology_confidence": max(topology_confidences) if topology_confidences else 0.0, "intersection_active": intersection_active, "turn_candidate": direction_label, "threshold_mode": "same_logical_lane" if same_logical_lane else "base_or_lane_change", "final_decision_reason": "turn_confirmed_from_ego_yaw_and_heading_change", "threshold_provenance": rule["provenance"]}
            start, end = interval.start_index, interval.end_index
            labels = [direction_label]
            if speed_label is not None:
                labels.append(speed_label)
            for label in labels:
                label_evidence = dict(evidence)
                if label == speed_label: label_evidence.update({"turn_speed_cutoff_mps": speed_rule["high_speed_minimum_mps"], "turn_speed_threshold_provenance": speed_rule["provenance"]})
                events.append(ScenarioEvent(label, features.frame_index[start], features.frame_index[end], features.timestamp_s[start], features.timestamp_s[end], round(features.timestamp_s[end] - features.timestamp_s[start], 6), detector_version=config["detector_version"], evidence=label_evidence))
        return events
