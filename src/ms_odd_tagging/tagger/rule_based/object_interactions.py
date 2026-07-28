"""Phase 3A proximity and multi-object events from shared object relations."""

from __future__ import annotations

import math
from typing import Any

from ms_odd_tagging.features.ego_motion import EgoMotionFeatures
from ms_odd_tagging.features.object_relations import _intervals

from .scenario_event import ScenarioEvent


MULTIPLE_SCENARIOS = {
    "near_multiple_bikes": "bicycle",
    "near_multiple_motorcycle": "motorcycle",
    "near_multiple_pedestrians": "pedestrian",
    "near_multiple_vehicles": "vehicle",
}


class ObjectInteractionDetector:
    """Detect temporal object-proximity states without recalculating geometry."""

    scenario_name = "object_interactions"
    required_features = frozenset()
    output_scenarios = frozenset(
        {
            "near_high_speed_vehicle",
            "near_long_vehicle",
            *MULTIPLE_SCENARIOS,
        }
    )

    def detect(
        self,
        frames: list[dict[str, Any]],
        features: EgoMotionFeatures,
        config: dict[str, Any],
        relations: dict[str, Any] | None = None,
    ) -> list[ScenarioEvent]:
        if not frames or not relations:
            return []
        rule = config["object_relations"]
        relation_by_frame = {
            frame["frame_index"]: frame for frame in relations.get("frames", [])
        }
        relation_frames = [
            relation_by_frame.get(frame_index, {"objects": []})
            for frame_index in features.frame_index
        ]
        timestamps = list(features.timestamp_s)
        frame_indexes = list(features.frame_index)
        track_by_id = {
            track["track_id"]: track for track in relations.get("tracks", [])
        }

        def event(
            scenario: str,
            start: int,
            end: int,
            evidence: dict[str, Any],
        ) -> ScenarioEvent:
            return ScenarioEvent(
                scenario=scenario,
                start_frame=frame_indexes[start],
                end_frame=frame_indexes[end],
                start_timestamp_s=timestamps[start],
                end_timestamp_s=timestamps[end],
                duration_s=round(timestamps[end] - timestamps[start], 6),
                detector_version=rule["detector_version"],
                evidence={
                    **evidence,
                    "interval_boundary_convention": "inclusive_observed_frames",
                    "threshold_provenance": rule["provenance"],
                },
            )

        def qualified(relation: dict[str, Any]) -> bool:
            return bool(
                relation.get("valid_spatial_relation")
                and relation.get("inside_proximity_region")
                and relation.get("track_age_s", 0.0)
                + 1e-9
                >= rule["minimum_track_age_s"]
            )

        def evidence_for(
            object_sets: list[list[dict[str, Any]]],
            start: int,
            end: int,
            *,
            representative_selector,
        ) -> dict[str, Any]:
            participants = {
                item["track_id"]
                for objects in object_sets[start : end + 1]
                for item in objects
            }
            representative_index = max(
                range(start, end + 1),
                key=lambda index: representative_selector(object_sets[index]),
            )
            distances = [
                item["nearest_footprint_distance_m"]
                for objects in object_sets[start : end + 1]
                for item in objects
                if item.get("nearest_footprint_distance_m") is not None
            ]
            source_ids = sorted(
                {
                    source_id
                    for track_id in participants
                    for source_id in track_by_id.get(track_id, {}).get(
                        "source_object_ids", []
                    )
                }
            )
            return {
                "object_interaction_event_id": (
                    f"object-interaction:{frame_indexes[start]}:"
                    f"{'-'.join(sorted(participants))}"
                ),
                "object_track_ids": sorted(participants),
                "source_object_ids": source_ids,
                "representative_frame": frame_indexes[representative_index],
                "minimum_footprint_distance_m": min(distances) if distances else None,
            }

        events: list[ScenarioEvent] = []
        maximum_gap = rule["maximum_missing_frame_gap_s"]
        merge_gap = rule["event_merge_gap_s"]
        minimum_duration = rule["minimum_event_duration_s"]

        # One event per nearby high-speed physical vehicle track.
        vehicle_track_ids = {
            item["track_id"]
            for frame in relation_frames
            for item in frame.get("objects", [])
            if item.get("normalized_category") == "vehicle"
        }
        for track_id in sorted(vehicle_track_ids):
            active = False
            signal = []
            series = []
            for frame in relation_frames:
                relation = next(
                    (
                        item
                        for item in frame.get("objects", [])
                        if item["track_id"] == track_id
                    ),
                    None,
                )
                series.append(relation)
                speed = relation.get("object_speed_mps") if relation else None
                if relation and qualified(relation) and speed is not None:
                    if not active and speed >= rule["high_speed_entry_mps"]:
                        active = True
                    elif active and speed < rule["high_speed_release_mps"]:
                        active = False
                elif relation is not None:
                    active = False
                signal.append(active and relation is not None and qualified(relation))
            for start, end in _intervals(
                signal,
                timestamps,
                minimum_duration_s=minimum_duration,
                maximum_missing_gap_s=maximum_gap,
                merge_gap_s=merge_gap,
            ):
                observations = [
                    relation
                    for relation in series[start : end + 1]
                    if relation is not None
                    and relation.get("object_speed_mps") is not None
                    and qualified(relation)
                ]
                speeds = [item["object_speed_mps"] for item in observations]
                distances = [
                    item["nearest_footprint_distance_m"]
                    for item in observations
                    if item.get("nearest_footprint_distance_m") is not None
                ]
                representative = sorted(speeds)[len(speeds) // 2]
                sources = sorted(
                    {item.get("velocity_source", "unavailable") for item in observations}
                )
                first = observations[0]
                events.append(
                    event(
                        "near_high_speed_vehicle",
                        start,
                        end,
                        {
                            "object_interaction_event_id": f"high-speed:{track_id}:{frame_indexes[start]}",
                            "object_track_ids": [track_id],
                            "source_object_ids": track_by_id.get(track_id, {}).get(
                                "source_object_ids", []
                            ),
                            "object_classes": sorted(
                                {item["class_name"] for item in observations}
                            ),
                            "minimum_footprint_distance_m": min(distances),
                            "peak_object_speed_mps": max(speeds),
                            "representative_object_speed_mps": representative,
                            "speed_definition": "absolute_ground_relative_lcs",
                            "velocity_sources": sources,
                            "representative_signed_longitudinal_m": first.get(
                                "signed_longitudinal_m"
                            ),
                            "representative_signed_lateral_m": first.get(
                                "signed_lateral_m"
                            ),
                            "entry_threshold_mps": rule["high_speed_entry_mps"],
                            "release_threshold_mps": rule[
                                "high_speed_release_mps"
                            ],
                        },
                    )
                )

        # One event per nearby long-vehicle physical track.
        for track_id in sorted(vehicle_track_ids):
            series = [
                next(
                    (
                        item
                        for item in frame.get("objects", [])
                        if item["track_id"] == track_id
                    ),
                    None,
                )
                for frame in relation_frames
            ]
            signal = [
                bool(relation and qualified(relation) and relation.get("long_vehicle"))
                for relation in series
            ]
            for start, end in _intervals(
                signal,
                timestamps,
                minimum_duration_s=minimum_duration,
                maximum_missing_gap_s=maximum_gap,
                merge_gap_s=merge_gap,
            ):
                observations = [
                    relation
                    for relation in series[start : end + 1]
                    if relation and qualified(relation) and relation.get("long_vehicle")
                ]
                representative = max(
                    observations, key=lambda item: item["dimensions_m"]["length"]
                )
                events.append(
                    event(
                        "near_long_vehicle",
                        start,
                        end,
                        {
                            "object_interaction_event_id": f"long-vehicle:{track_id}:{frame_indexes[start]}",
                            "object_track_ids": [track_id],
                            "source_object_ids": track_by_id.get(track_id, {}).get(
                                "source_object_ids", []
                            ),
                            "object_class": representative["class_name"],
                            "bbox_dimensions_m": representative["dimensions_m"],
                            "classification_reason": representative[
                                "long_vehicle_reason"
                            ],
                            "minimum_footprint_distance_m": min(
                                item["nearest_footprint_distance_m"]
                                for item in observations
                            ),
                        },
                    )
                )

        for scenario, category in MULTIPLE_SCENARIOS.items():
            minimum_count = rule["minimum_counts"][scenario]
            object_sets = []
            for frame in relation_frames:
                # Track identity, not raw box count, is the counting unit.
                by_track: dict[str, dict[str, Any]] = {}
                for item in frame.get("objects", []):
                    if (
                        item.get("normalized_category") != category
                        or not qualified(item)
                    ):
                        continue
                    track_id = str(item.get("track_id"))
                    incumbent = by_track.get(track_id)
                    if incumbent is None or float(
                        item.get("nearest_footprint_distance_m", math.inf)
                    ) < float(
                        incumbent.get("nearest_footprint_distance_m", math.inf)
                    ):
                        by_track[track_id] = item
                object_sets.append(list(by_track.values()))
            signal = [len(objects) >= minimum_count for objects in object_sets]
            for start, end in _intervals(
                signal,
                timestamps,
                minimum_duration_s=minimum_duration,
                maximum_missing_gap_s=maximum_gap,
                merge_gap_s=merge_gap,
            ):
                base_evidence = evidence_for(
                    object_sets,
                    start,
                    end,
                    representative_selector=len,
                )
                base_evidence.update(
                    {
                        "object_interaction_event_id": (
                            f"{scenario}:"
                            f"{base_evidence['object_interaction_event_id']}"
                        ),
                        "normalized_category": category,
                        "minimum_required_count": minimum_count,
                        "peak_simultaneous_count": max(
                            len(objects) for objects in object_sets[start : end + 1]
                        ),
                        "vehicle_category_definition": (
                            "configured_motorized_road_vehicles_excluding_bicycle_and_motorcycle"
                            if category == "vehicle"
                            else None
                        ),
                    }
                )
                events.append(event(scenario, start, end, base_evidence))

        return sorted(
            events,
            key=lambda item: (
                item.start_timestamp_s,
                item.scenario,
                item.end_timestamp_s,
            ),
        )
