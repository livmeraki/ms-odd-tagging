"""Direct traffic-light behavior tags from shared TL context."""

from __future__ import annotations

from collections import Counter
from typing import Any

from ms_odd_tagging.features.object_relations import _intervals

from .scenario_event import ScenarioEvent


SCENARIOS = frozenset(
    {
        "accelerating_at_traffic_light_with_lead",
        "accelerating_at_traffic_light_without_lead",
        "stationary_at_traffic_light_with_lead",
        "stationary_at_traffic_light_without_lead",
        "stopping_at_traffic_light_with_lead",
        "stopping_at_traffic_light_without_lead",
    }
)


MOTION_TO_SCENARIO_PREFIX = {
    "accelerating": "accelerating_at_traffic_light",
    "stationary": "stationary_at_traffic_light",
    "stopping": "stopping_at_traffic_light",
}


VALID_INTERSECTION_STATES = {"approaching", "entry", "inside"}
VALID_STOPLINE_RELATIONS = {"before_stopline", "on_stopline"}


def _confidence_value(frame: dict[str, Any]) -> float:
    value = frame.get("confidence")
    return float(value) if isinstance(value, (int, float)) else 0.0


def _event(
    scenario: str,
    start: int,
    end: int,
    frames: list[dict[str, Any]],
    rule: dict[str, Any],
    observations: list[dict[str, Any]],
) -> ScenarioEvent:
    representative = max(observations, key=_confidence_value)
    lead = representative.get("lead") or {}
    stopline = representative.get("stopline") or {}
    motion = representative.get("ego_motion") or {}
    light_ids = sorted(
        {
            light_id
            for item in observations
            for light_id in item.get("relevant_traffic_light_ids", [])
        }
    )
    states = Counter(item.get("intersection_state") for item in observations)
    relations = Counter((item.get("stopline") or {}).get("relation") for item in observations)
    confidences = [_confidence_value(item) for item in observations]
    return ScenarioEvent(
        scenario=scenario,
        start_frame=frames[start]["frame_index"],
        end_frame=frames[end]["frame_index"],
        start_timestamp_s=frames[start]["timestamp_s"],
        end_timestamp_s=frames[end]["timestamp_s"],
        duration_s=round(frames[end]["timestamp_s"] - frames[start]["timestamp_s"], 6),
        confidence=round(min(confidences), 3) if confidences else 0.0,
        detector_version=rule["detector_version"],
        evidence={
            "traffic_light_context": True,
            "traffic_light_context_schema_version": rule.get("context_schema_version"),
            "relevant_traffic_light_ids": light_ids,
            "traffic_light_context_confidence": representative.get("confidence"),
            "intersection_state": representative.get("intersection_state"),
            "intersection_state_counts": dict(states),
            "stopline_id": stopline.get("id"),
            "stopline_distance_m": stopline.get("distance_m"),
            "stopline_relation": stopline.get("relation"),
            "stopline_relation_counts": dict(relations),
            "ego_state": (
                "accelerating"
                if motion.get("accelerating")
                else "stopping"
                if motion.get("stopping")
                else "stationary"
                if motion.get("stationary")
                else "unknown"
            ),
            "ego_speed_mps": motion.get("speed_mps"),
            "ego_acceleration_mps2": motion.get("acceleration_mps2"),
            "lead_exists": lead.get("exists") is True,
            "lead_object_id": lead.get("object_id"),
            "lead_source_object_ids": lead.get("source_object_ids", []),
            "lead_longitudinal_distance_m": lead.get("longitudinal_distance_m"),
            "lead_lateral_distance_m": lead.get("lateral_distance_m"),
            "lead_confidence": lead.get("confidence"),
            "lead_same_path_compatible": lead.get("same_path_compatible"),
            "representative_frame": representative.get("frame_index"),
            "interval_boundary_convention": "inclusive_observed_frames",
            "threshold_provenance": rule["provenance"],
            "phase1_dependency": "traffic_light_context",
        },
    )


class TrafficLightBehaviorDetector:
    """Compose direct TL behavior tags from Phase 1 per-frame context."""

    scenario_name = "traffic_light_behaviors"
    required_features = frozenset({"traffic_light_context"})
    output_scenarios = SCENARIOS

    def detect(
        self,
        frames: list[dict[str, Any]],
        config: dict[str, Any],
        traffic_light_context: dict[str, Any] | None,
    ) -> list[ScenarioEvent]:
        if not frames or not traffic_light_context:
            return []
        rule = config["traffic_light_context"]
        context_by_frame = {
            item.get("frame_index"): item
            for item in traffic_light_context.get("frames", [])
        }
        context_frames = [
            context_by_frame.get(frame.get("frame_index"))
            for frame in frames
        ]
        timestamps = [
            float(frame.get("time_since_start_s", frame.get("timestamp_s", 0.0)))
            for frame in frames
        ]
        normalized_frames = [
            {
                "frame_index": frame.get("frame_index"),
                "timestamp_s": timestamps[index],
            }
            for index, frame in enumerate(frames)
        ]
        events: list[ScenarioEvent] = []
        for motion_key, prefix in MOTION_TO_SCENARIO_PREFIX.items():
            for has_lead, suffix in ((True, "with_lead"), (False, "without_lead")):
                scenario = f"{prefix}_{suffix}"
                signal = [
                    self._qualifies(frame, motion_key, has_lead)
                    for frame in context_frames
                ]
                for start, end in _intervals(
                    signal,
                    timestamps,
                    minimum_duration_s=rule["minimum_event_duration_s"],
                    maximum_missing_gap_s=rule["maximum_missing_gap_s"],
                    merge_gap_s=rule["event_merge_gap_s"],
                ):
                    observations = [
                        item for item in context_frames[start : end + 1] if item
                    ]
                    events.append(
                        _event(
                            scenario,
                            start,
                            end,
                            normalized_frames,
                            {
                                **rule,
                                "context_schema_version": traffic_light_context.get(
                                    "schema_version"
                                ),
                            },
                            observations,
                        )
                    )
        return sorted(
            events,
            key=lambda item: (
                item.start_timestamp_s,
                item.scenario,
                item.end_timestamp_s,
            ),
        )

    @staticmethod
    def _valid_context(frame: dict[str, Any] | None) -> bool:
        if not frame:
            return False
        stopline = frame.get("stopline") or {}
        return bool(
            frame.get("is_traffic_light_intersection")
            and frame.get("relevant_traffic_light_ids")
            and frame.get("intersection_state") in VALID_INTERSECTION_STATES
            and stopline.get("relation") in VALID_STOPLINE_RELATIONS
        )

    def _qualifies(
        self,
        frame: dict[str, Any] | None,
        motion_key: str,
        has_lead: bool,
    ) -> bool:
        if not self._valid_context(frame):
            return False
        motion = (frame or {}).get("ego_motion") or {}
        lead = (frame or {}).get("lead") or {}
        return bool(motion.get(motion_key) and (lead.get("exists") is True) == has_lead)


__all__ = ["SCENARIOS", "TrafficLightBehaviorDetector"]
