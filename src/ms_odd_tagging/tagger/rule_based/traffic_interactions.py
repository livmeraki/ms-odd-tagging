"""Advanced traffic-relation scenario detectors."""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from ms_odd_tagging.features.ego_motion import EgoMotionFeatures
from ms_odd_tagging.features.object_relations import _intervals

from .scenario_event import ScenarioEvent


SCENARIOS = frozenset(
    {
        "following_lane_with_slow_lead",
        "changing_lane_with_lead",
        "changing_lane_with_trail",
        "stopping_with_lead",
        "stopping_without_lead",
        "stationary_in_traffic",
        "behind_bike",
        "behind_long_vehicle",
        "behind_pedestrian_on_driveable",
        "waiting_for_pedestrian_to_cross",
        "near_barrier_on_driveable",
    }
)


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _event(
    scenario: str,
    start: int,
    end: int,
    frames: list[dict[str, Any]],
    rule: dict[str, Any],
    evidence: dict[str, Any],
) -> ScenarioEvent:
    return ScenarioEvent(
        scenario=scenario,
        start_frame=frames[start]["frame_index"],
        end_frame=frames[end]["frame_index"],
        start_timestamp_s=frames[start]["timestamp_s"],
        end_timestamp_s=frames[end]["timestamp_s"],
        duration_s=round(frames[end]["timestamp_s"] - frames[start]["timestamp_s"], 6),
        detector_version=rule["detector_version"],
        evidence={
            **evidence,
            "interval_boundary_convention": "inclusive_observed_frames",
            "threshold_provenance": rule["provenance"],
        },
    )


def _observations(series: list[dict[str, Any] | None], start: int, end: int) -> list[dict[str, Any]]:
    return [item for item in series[start : end + 1] if item is not None]


def _representative(items: list[dict[str, Any]], key: str, *, default: float = math.inf) -> dict[str, Any]:
    return min(items, key=lambda item: abs(float(item.get(key, default))))


def _lead_evidence(items: list[dict[str, Any]], prefix: str = "lead") -> dict[str, Any]:
    representative = _representative(items, "longitudinal_gap_m")
    speeds = [item.get("object_speed_mps") for item in items if _finite(item.get("object_speed_mps"))]
    rel_speeds = [item.get("relative_speed_mps") for item in items if _finite(item.get("relative_speed_mps"))]
    gaps = [item.get("longitudinal_gap_m") for item in items if _finite(item.get("longitudinal_gap_m"))]
    return {
        f"{prefix}_object_id": representative.get("track_id"),
        f"{prefix}_source_object_ids": representative.get("source_object_ids", []),
        f"{prefix}_class": representative.get("class_name"),
        f"{prefix}_length_m": (representative.get("dimensions_m") or {}).get("length"),
        f"{prefix}_speed_mps": min(speeds) if speeds else None,
        "relative_speed_mps": min(rel_speeds) if rel_speeds else None,
        f"{prefix}_gap_m": min(gaps) if gaps else None,
        "time_headway_s": representative.get("time_headway_s"),
        "ttc_s": representative.get("ttc_s"),
        "same_lane_confidence": representative.get("same_lane_confidence"),
        "same_lane_source": representative.get("same_lane_source"),
        "data_quality_flags": sorted({flag for item in items for flag in item.get("data_quality_flags", [])}),
    }


class TrafficInteractionDetector:
    """Detect advanced tags from shared traffic relation features."""

    scenario_name = "traffic_interactions"
    required_features = frozenset()
    output_scenarios = SCENARIOS

    def detect(
        self,
        frames: list[dict[str, Any]],
        features: EgoMotionFeatures,
        config: dict[str, Any],
        traffic_relations: dict[str, Any] | None = None,
    ) -> list[ScenarioEvent]:
        if not frames or not traffic_relations:
            return []
        rule = config["traffic_interactions"]
        relation_frames = [
            frame
            for frame in traffic_relations.get("frames", [])
            if frame.get("frame_index") in set(features.frame_index)
        ]
        if len(relation_frames) != len(features.frame_index):
            by_index = {frame["frame_index"]: frame for frame in traffic_relations.get("frames", [])}
            relation_frames = [by_index.get(index, {"frame_index": index, "timestamp_s": timestamp, "objects": []}) for index, timestamp in zip(features.frame_index, features.timestamp_s)]
        timestamps = [frame["timestamp_s"] for frame in relation_frames]
        events: list[ScenarioEvent] = []

        events.extend(self._following_slow_lead(relation_frames, timestamps, rule))
        events.extend(self._lane_change_related(relation_frames, timestamps, rule))
        events.extend(self._stopping(relation_frames, timestamps, rule))
        events.extend(self._stationary_in_traffic(relation_frames, timestamps, rule))
        events.extend(self._behind_bike(relation_frames, timestamps, rule))
        events.extend(self._behind_long_vehicle(relation_frames, timestamps, rule))
        events.extend(self._behind_pedestrian(relation_frames, timestamps, rule))
        events.extend(self._waiting_for_pedestrian(relation_frames, timestamps, rule))
        events.extend(self._barriers(relation_frames, timestamps, rule))
        return sorted(events, key=lambda item: (item.start_timestamp_s, item.scenario, item.end_timestamp_s))

    def _following_slow_lead(self, frames, timestamps, rule):
        signal = []
        series = []
        active = False
        for frame in frames:
            lead = frame.get("primary_lead")
            series.append(lead)
            qualifies = bool(
                lead
                and lead.get("normalized_category") == "vehicle"
                and _finite(lead.get("object_speed_mps"))
                and _finite(frame.get("ego_speed_mps"))
                and lead.get("velocity_source") in rule["slow_lead_allowed_velocity_sources"]
                and lead.get("longitudinal_gap_m") <= rule["maximum_lead_gap_m"]
            )
            score = False
            if qualifies:
                slow_absolute = lead["object_speed_mps"] <= rule["slow_lead_entry_speed_mps"]
                slow_relative = frame["ego_speed_mps"] - lead["object_speed_mps"] >= rule["slow_lead_entry_relative_speed_mps"]
                release_absolute = lead["object_speed_mps"] <= rule["slow_lead_release_speed_mps"]
                release_relative = frame["ego_speed_mps"] - lead["object_speed_mps"] >= rule["slow_lead_release_relative_speed_mps"]
                if not active and (slow_absolute or slow_relative):
                    active = True
                elif active and not (release_absolute or release_relative):
                    active = False
                score = active
            else:
                active = False
            signal.append(score)
        result = []
        for start, end in _intervals(signal, timestamps, minimum_duration_s=rule["minimum_duration_s"], maximum_missing_gap_s=rule["maximum_inactive_gap_s"], merge_gap_s=rule["merge_gap_s"]):
            observations = _observations(series, start, end)
            result.append(_event("following_lane_with_slow_lead", start, end, frames, rule, {**_lead_evidence(observations), "slow_lead_entry_speed_mps": rule["slow_lead_entry_speed_mps"], "slow_lead_entry_relative_speed_mps": rule["slow_lead_entry_relative_speed_mps"]}))
        return result

    def _target_lane_objects(self, frame, direction: str, *, ahead: bool):
        sign = 1.0 if direction == "left" else -1.0
        result = []
        for item in frame.get("objects", []):
            lateral = item.get("signed_lateral_m")
            longitudinal = item.get("signed_longitudinal_m")
            if not _finite(lateral) or not _finite(longitudinal):
                continue
            if sign * float(lateral) < 1.2 or abs(float(lateral)) > 5.5:
                continue
            if ahead and longitudinal > 0:
                result.append(item)
            if not ahead and longitudinal < 0:
                result.append(item)
        return result

    def _lane_change_related(self, frames, timestamps, rule):
        result = []
        for scenario, ahead in (("changing_lane_with_lead", True), ("changing_lane_with_trail", False)):
            seen: set[str] = set()
            by_event: dict[str, list[bool]] = {}
            series_by_event: dict[str, list[dict[str, Any] | None]] = {}
            for index, frame in enumerate(frames):
                change = (frame.get("lane_change_events") or [None])[0]
                event_id = None
                if change:
                    evidence = change.get("evidence", {})
                    event_id = evidence.get("physical_lane_change_event_id")
                    direction = evidence.get("direction")
                    objects = self._target_lane_objects(frame, direction, ahead=ahead) if direction in {"left", "right"} else []
                    objects = [item for item in objects if item.get("normalized_category") in {"vehicle", "bicycle", "motorcycle"}]
                    selected = min(objects, key=lambda item: abs(float(item["signed_longitudinal_m"])), default=None)
                else:
                    selected = None
                if event_id is not None and event_id not in seen:
                    seen.add(event_id)
                    by_event[event_id] = [False] * len(frames)
                    series_by_event[event_id] = [None] * len(frames)
                for known in seen:
                    if known == event_id:
                        by_event[known][index] = selected is not None
                        series_by_event[known][index] = selected
            for event_id, signal in by_event.items():
                for start, end in _intervals(signal, timestamps, minimum_duration_s=rule["lane_change_object_minimum_duration_s"], maximum_missing_gap_s=rule["maximum_inactive_gap_s"], merge_gap_s=0.0):
                    observations = _observations(series_by_event[event_id], start, end)
                    change = frames[start]["lane_change_events"][0]
                    evidence = change["evidence"]
                    selected = _representative(observations, "signed_longitudinal_m")
                    key = "lead" if ahead else "trail"
                    result.append(_event(scenario, start, end, frames, rule, {f"{key}_object_id": selected["track_id"], f"{key}_source_object_ids": selected.get("source_object_ids", []), "physical_lane_change_event_id": event_id, "lane_change_direction": evidence.get("direction"), "source_logical_lane_id": evidence.get("source_logical_lane_id"), "target_logical_lane_id": evidence.get("target_logical_lane_id"), "target_lane_gap_m": abs(float(selected["signed_longitudinal_m"])), "relative_speed_mps": selected.get("relative_speed_mps"), "target_lane_association": "ego_lateral_target_corridor"}))
        return result

    def _stopping(self, frames, timestamps, rule):
        moving = [frame.get("ego_speed_mps") is not None and frame["ego_speed_mps"] >= rule["stopping_moving_speed_mps"] for frame in frames]
        stopped = [frame.get("ego_speed_mps") is not None and frame["ego_speed_mps"] <= rule["stopping_stopped_speed_mps"] for frame in frames]
        reliable_lead = [bool(frame.get("primary_lead")) for frame in frames]
        result = []
        index = 1
        while index < len(frames):
            if not stopped[index]:
                index += 1
                continue
            stop_start = index
            while index + 1 < len(frames) and stopped[index + 1]:
                index += 1
            stop_end = index
            lookback = [i for i in range(0, stop_start) if timestamps[stop_start] - timestamps[i] <= rule["stopping_transition_lookback_s"]]
            if not any(moving[i] for i in lookback):
                index += 1
                continue
            transition = lookback + list(range(stop_start, stop_end + 1))
            lead_count = sum(reliable_lead[i] for i in transition)
            unknown_count = sum(any("low_same_lane_confidence" in obj.get("data_quality_flags", []) for obj in frames[i].get("objects", [])) for i in transition)
            if lead_count:
                observations = [frames[i]["primary_lead"] for i in transition if frames[i].get("primary_lead")]
                result.append(_event("stopping_with_lead", max(lookback), stop_end, frames, rule, {**_lead_evidence(observations), "lead_persistence_frames": lead_count, "ego_response": "moving_to_stopped"}))
            elif unknown_count == 0:
                result.append(_event("stopping_without_lead", max(lookback), stop_end, frames, rule, {"lead_state": "reliably_absent", "ego_response": "moving_to_stopped"}))
            index += 1
        return result

    def _stationary_in_traffic(self, frames, timestamps, rule):
        signal = []
        vehicle_sets = []
        for frame in frames:
            vehicles = [item for item in frame.get("objects", []) if item.get("normalized_category") in {"vehicle", "bicycle", "motorcycle"} and abs(float(item.get("signed_longitudinal_m") or 999.0)) <= rule["stationary_traffic_radius_m"] and abs(float(item.get("signed_lateral_m") or 999.0)) <= rule["stationary_traffic_lateral_m"] and item.get("object_motion_state") in {"stationary", "slow"}]
            vehicle_sets.append(vehicles)
            signal.append(frame.get("ego_motion_state") == "stationary" and (bool(frame.get("primary_lead")) or len(vehicles) >= rule["stationary_traffic_minimum_vehicle_count"]))
        result = []
        for start, end in _intervals(signal, timestamps, minimum_duration_s=rule["stationary_traffic_minimum_duration_s"], maximum_missing_gap_s=rule["maximum_inactive_gap_s"], merge_gap_s=rule["merge_gap_s"]):
            vehicles = [item for row in vehicle_sets[start : end + 1] for item in row]
            lead = next((frames[i].get("primary_lead") for i in range(start, end + 1) if frames[i].get("primary_lead")), None)
            speeds = [item.get("object_speed_mps") for item in vehicles if _finite(item.get("object_speed_mps"))]
            result.append(_event("stationary_in_traffic", start, end, frames, rule, {"relevant_vehicle_count": len({item["track_id"] for item in vehicles}), "lead_gap_m": lead.get("longitudinal_gap_m") if lead else None, "nearby_vehicle_speed_min_mps": min(speeds) if speeds else None, "nearby_vehicle_speed_max_mps": max(speeds) if speeds else None, "stationary_duration_s": round(timestamps[end] - timestamps[start], 6)}))
        return result

    def _behind_bike(self, frames, timestamps, rule):
        series = []
        signal = []
        for frame in frames:
            candidates = [item for item in frame.get("objects", []) if item.get("normalized_category") == "bicycle" and item.get("ahead") and item.get("same_lane") and item.get("object_motion_state") != "unknown" and item.get("longitudinal_gap_m") <= rule["behind_bike_maximum_gap_m"]]
            selected = min(candidates, key=lambda item: item["longitudinal_gap_m"], default=None)
            series.append(selected)
            signal.append(selected is not None)
        return [_event("behind_bike", start, end, frames, rule, {**_lead_evidence(_observations(series, start, end), "bike"), "directional_compatibility": "same_ego_aligned_corridor"}) for start, end in _intervals(signal, timestamps, minimum_duration_s=rule["minimum_duration_s"], maximum_missing_gap_s=rule["maximum_inactive_gap_s"], merge_gap_s=rule["merge_gap_s"])]

    def _behind_long_vehicle(self, frames, timestamps, rule):
        series = []
        signal = []
        for frame in frames:
            candidates = [item for item in frame.get("objects", []) if item.get("long_vehicle") and item.get("ahead") and item.get("same_lane") and item.get("longitudinal_gap_m") <= rule["maximum_lead_gap_m"]]
            selected = min(candidates, key=lambda item: item["longitudinal_gap_m"], default=None)
            series.append(selected)
            signal.append(selected is not None)
        return [_event("behind_long_vehicle", start, end, frames, rule, {**_lead_evidence(_observations(series, start, end)), "semantic_class_or_length_threshold": True}) for start, end in _intervals(signal, timestamps, minimum_duration_s=rule["minimum_duration_s"], maximum_missing_gap_s=rule["maximum_inactive_gap_s"], merge_gap_s=rule["merge_gap_s"])]

    def _behind_pedestrian(self, frames, timestamps, rule):
        series = []
        signal = []
        for frame in frames:
            on_crosswalk_ids = {interaction.get("pedestrian_track_id") for interaction in frame.get("pedestrian_crosswalk_interactions", []) if interaction.get("state") == "on_crosswalk"}
            candidates = [item for item in frame.get("objects", []) if item.get("normalized_category") == "pedestrian" and item.get("ahead") and item.get("driveable_area_confidence") is not None and item["driveable_area_confidence"] >= rule["minimum_driveable_confidence"] and item["track_id"] not in on_crosswalk_ids and abs(float(item.get("signed_lateral_m") or 999)) <= rule["pedestrian_corridor_lateral_m"] and item.get("longitudinal_gap_m") <= rule["behind_pedestrian_maximum_gap_m"]]
            selected = min(candidates, key=lambda item: item["longitudinal_gap_m"], default=None)
            series.append(selected)
            signal.append(selected is not None)
        return [_event("behind_pedestrian_on_driveable", start, end, frames, rule, {**_lead_evidence(_observations(series, start, end), "pedestrian"), "driveable_area_confidence": _observations(series, start, end)[0].get("driveable_area_confidence"), "path_relation": "ahead_in_driveable_corridor"}) for start, end in _intervals(signal, timestamps, minimum_duration_s=rule["minimum_duration_s"], maximum_missing_gap_s=rule["maximum_inactive_gap_s"], merge_gap_s=rule["merge_gap_s"])]

    def _waiting_for_pedestrian(self, frames, timestamps, rule):
        signal = []
        pedestrian_sets = []
        for frame in frames:
            peds = [item for item in frame.get("objects", []) if item.get("normalized_category") == "pedestrian" and (item.get("ahead") or abs(float(item.get("signed_lateral_m") or 999)) <= rule["pedestrian_conflict_lateral_m"]) and item.get("driveable_area_confidence") is not None and item["driveable_area_confidence"] >= rule["minimum_driveable_confidence"]]
            crosswalk_conflict = any(interaction.get("state") == "on_crosswalk" and interaction.get("near_ego") for interaction in frame.get("pedestrian_crosswalk_interactions", []))
            pedestrian_sets.append(peds)
            signal.append(bool(peds) and (crosswalk_conflict or peds) and frame.get("ego_motion_state") in {"stationary", "decelerating"})
        result = []
        for start, end in _intervals(signal, timestamps, minimum_duration_s=rule["waiting_minimum_duration_s"], maximum_missing_gap_s=rule["maximum_inactive_gap_s"], merge_gap_s=rule["merge_gap_s"]):
            prior_stationary = start > 0 and frames[start - 1].get("ego_motion_state") == "stationary"
            has_yield_response = any(
                frames[i].get("ego_motion_state") == "decelerating"
                for i in range(max(0, start - 3), end + 1)
            )
            if (start == 0 or prior_stationary) and not has_yield_response:
                continue
            peds = [item for row in pedestrian_sets[start : end + 1] for item in row]
            selected = min(peds, key=lambda item: abs(float(item.get("longitudinal_gap_m") or 999)), default={})
            result.append(_event("waiting_for_pedestrian_to_cross", start, end, frames, rule, {"pedestrian_id": selected.get("track_id"), "pedestrian_source_object_ids": selected.get("source_object_ids", []), "crosswalk_relation": "conflict_or_driveable_corridor", "path_conflict_geometry": "ego_aligned_future_path_corridor", "ego_response_onset_frame": frames[start]["frame_index"], "minimum_distance_m": min((abs(float(item.get("longitudinal_gap_m") or 999)) for item in peds), default=None), "evidence_frames": [frames[start]["frame_index"], frames[end]["frame_index"]]}))
        return result

    def _barriers(self, frames, timestamps, rule):
        barrier_sets = []
        signal = []
        for frame in frames:
            barriers = [item for item in frame.get("barriers", []) if item.get("center_distance_m") <= rule["barrier_maximum_distance_m"] and item.get("driveable_area_confidence") is not None and item["driveable_area_confidence"] >= rule["minimum_driveable_confidence"] and item.get("intrusion_m", 0.0) >= rule["barrier_minimum_intrusion_m"]]
            barrier_sets.append(barriers)
            signal.append(bool(barriers))
        result = []
        for start, end in _intervals(signal, timestamps, minimum_duration_s=rule["barrier_minimum_duration_s"], maximum_missing_gap_s=rule["maximum_inactive_gap_s"], merge_gap_s=rule["merge_gap_s"]):
            barriers = [item for row in barrier_sets[start : end + 1] for item in row]
            selected = min(barriers, key=lambda item: item["center_distance_m"])
            result.append(_event("near_barrier_on_driveable", start, end, frames, rule, {"object_id": selected.get("object_id"), "object_class": selected.get("class_name"), "object_subclass": selected.get("subclass"), "nearest_distance_m": selected.get("center_distance_m"), "intrusion_m": selected.get("intrusion_m"), "driveable_area_confidence": selected.get("driveable_area_confidence"), "driveable_area_source": selected.get("driveable_area_source"), "candidate_classes": sorted(dict(Counter(item.get("class_name") for item in barriers)).keys())}))
        return result


__all__ = ["TrafficInteractionDetector", "SCENARIOS"]
