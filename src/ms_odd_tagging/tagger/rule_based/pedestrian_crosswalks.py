"""Phase 3B pedestrian-crosswalk interaction event detector."""

from __future__ import annotations

from typing import Any

from ms_odd_tagging.features.ego_motion import EgoMotionFeatures
from ms_odd_tagging.features.object_relations import _intervals

from .scenario_event import ScenarioEvent


class PedestrianCrosswalkInteractionDetector:
    """Derive both labels from one shared per-frame interaction state."""

    scenario_name = "pedestrian_crosswalk_interactions"
    required_features = frozenset()
    output_scenarios = frozenset(
        {
            "near_pedestrian_on_crosswalk",
            "near_pedestrian_on_crosswalk_with_ego",
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
        rule = config["pedestrian_crosswalk_interactions"]
        frame_by_index = {
            frame["frame_index"]: frame
            for frame in relations.get("frames", [])
        }
        relation_frames = [
            frame_by_index.get(frame_index, {"interactions": []})
            for frame_index in features.frame_index
        ]
        timestamps = list(features.timestamp_s)
        frame_indexes = list(features.frame_index)

        def qualifying(frame: dict[str, Any], with_ego: bool):
            by_pedestrian: dict[str, dict[str, Any]] = {}
            for relation in frame.get("interactions", []):
                if (
                    not relation.get("association_valid")
                    or relation.get("state") != "on_crosswalk"
                    or not relation.get("near_ego")
                    or (
                        with_ego
                        and not relation.get("ego_on_same_crosswalk")
                    )
                ):
                    continue
                pedestrian_id = str(relation["pedestrian_track_id"])
                incumbent = by_pedestrian.get(pedestrian_id)
                if incumbent is None or float(
                    relation.get("pedestrian_ego_distance_m", float("inf"))
                ) < float(
                    incumbent.get(
                        "pedestrian_ego_distance_m", float("inf")
                    )
                ):
                    by_pedestrian[pedestrian_id] = relation
            return list(by_pedestrian.values())

        events = []
        for scenario, with_ego in (
            ("near_pedestrian_on_crosswalk", False),
            ("near_pedestrian_on_crosswalk_with_ego", True),
        ):
            object_sets = [
                qualifying(frame, with_ego) for frame in relation_frames
            ]
            signal = [bool(objects) for objects in object_sets]
            for start, end in _intervals(
                signal,
                timestamps,
                minimum_duration_s=rule["minimum_event_duration_s"],
                maximum_missing_gap_s=rule["maximum_missing_gap_s"],
                merge_gap_s=rule["event_merge_gap_s"],
            ):
                interval_relations = [
                    relation
                    for objects in object_sets[start : end + 1]
                    for relation in objects
                ]
                pedestrian_track_ids = sorted(
                    {
                        relation["pedestrian_track_id"]
                        for relation in interval_relations
                    }
                )
                source_ids = sorted(
                    {
                        source_id
                        for relation in interval_relations
                        for source_id in relation.get(
                            "source_pedestrian_ids", []
                        )
                    }
                )
                crosswalk_ids = sorted(
                    {
                        relation["crosswalk_track_id"]
                        for relation in interval_relations
                    }
                )
                representative_index = max(
                    range(start, end + 1),
                    key=lambda index: len(object_sets[index]),
                )
                distances = [
                    relation["pedestrian_ego_distance_m"]
                    for relation in interval_relations
                    if relation.get("pedestrian_ego_distance_m") is not None
                ]
                overlaps = [
                    relation["crosswalk_overlap_ratio"]
                    for relation in interval_relations
                ]
                events.append(
                    ScenarioEvent(
                        scenario=scenario,
                        start_frame=frame_indexes[start],
                        end_frame=frame_indexes[end],
                        start_timestamp_s=timestamps[start],
                        end_timestamp_s=timestamps[end],
                        duration_s=round(
                            timestamps[end] - timestamps[start], 6
                        ),
                        detector_version=rule["detector_version"],
                        evidence={
                            "pedestrian_crosswalk_event_id": (
                                f"{scenario}:{frame_indexes[start]}:"
                                f"{'-'.join(crosswalk_ids)}"
                            ),
                            "crosswalk_ids": crosswalk_ids,
                            "crosswalk_id": (
                                crosswalk_ids[0]
                                if len(crosswalk_ids) == 1
                                else None
                            ),
                            "pedestrian_track_ids": pedestrian_track_ids,
                            "pedestrian_ids": source_ids,
                            "peak_pedestrian_count": max(
                                len(objects)
                                for objects in object_sets[start : end + 1]
                            ),
                            "minimum_distance_m": (
                                min(distances) if distances else None
                            ),
                            "maximum_crosswalk_overlap_ratio": max(overlaps),
                            "ego_crosswalk_relation": (
                                "on"
                                if with_ego
                                else "path_related_nearby_or_on"
                            ),
                            "pedestrian_crosswalk_relation": "on_crosswalk",
                            "same_crosswalk_required": with_ego,
                            "representative_frame": frame_indexes[
                                representative_index
                            ],
                            "interval_boundary_convention": (
                                "inclusive_observed_frames"
                            ),
                            "threshold_provenance": rule["provenance"],
                        },
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


__all__ = ["PedestrianCrosswalkInteractionDetector"]
