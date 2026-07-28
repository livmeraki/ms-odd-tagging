"""Crosswalk/stopline events derived from recording-level spatial relations."""

from __future__ import annotations

from statistics import median
from typing import Any

from ms_odd_tagging.features.ego_motion import EgoMotionFeatures

from .scenario_event import ScenarioEvent


class CrosswalkRelationDetector:
    """Convert shared road-feature relation states into taxonomy events."""

    scenario_name = "crosswalk_relations"
    required_features = frozenset({"speed_mps", "longitudinal_acceleration_mps2"})
    output_scenarios = frozenset(
        {
            "traversing_crosswalk",
            "on_stopline_crosswalk",
            "stationary_at_crosswalk",
            "stopping_at_crosswalk",
            "accelerating_at_crosswalk",
        }
    )

    def detect(
        self,
        frames: list[dict[str, Any]],
        features: EgoMotionFeatures,
        config: dict[str, Any],
        relations: dict[str, Any] | None = None,
    ) -> list[ScenarioEvent]:
        if not frames or not relations or not relations.get("frames"):
            return []
        rule = config["road_feature_relations"]
        timestamps = features.timestamp_s
        frame_indexes = features.frame_index
        relation_frames = {
            item["frame_index"]: item for item in relations.get("frames", [])
        }
        relation_rows = [relation_frames.get(index, {}) for index in frame_indexes]
        steps = [
            b - a for a, b in zip(timestamps, timestamps[1:]) if b > a
        ]
        nominal_step = median(steps) if steps else 0.0

        def observed_duration(start: int, end: int) -> float:
            return timestamps[end] - timestamps[start] + nominal_step

        def make_event(
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

        def relation_series(track_id: str, key: str) -> list[dict[str, Any] | None]:
            return [
                next(
                    (
                        relation
                        for relation in row.get(key, [])
                        if relation.get("track_id") == track_id
                    ),
                    None,
                )
                for row in relation_rows
            ]

        def valid_run_end(
            series: list[dict[str, Any] | None],
            start: int,
            states: set[str],
            minimum_s: float,
        ) -> int | None:
            end = start
            for index in range(start, len(series)):
                relation = series[index]
                if (
                    relation is None
                    or not relation.get("relation_valid")
                    or relation.get("state") not in states
                ):
                    break
                end = index
                if observed_duration(start, end) + 1e-9 >= minimum_s:
                    return end
            return None

        events: list[ScenarioEvent] = []
        crosswalk_tracks = [
            track
            for track in relations.get("tracks", [])
            if track.get("feature_type") == "crosswalk"
        ]
        for track in crosswalk_tracks:
            track_id = track["track_id"]
            series = relation_series(track_id, "crosswalk_relations")

            # Traversal: a sustained footprint overlap, with approach and exit.
            index = 0
            while index < len(series):
                relation = series[index]
                if not relation or relation.get("state") != "on":
                    index += 1
                    continue
                on_start = index
                while (
                    index + 1 < len(series)
                    and series[index + 1]
                    and series[index + 1].get("state") == "on"
                ):
                    index += 1
                on_end = index
                confirmed_on = (
                    observed_duration(on_start, on_end) + 1e-9
                    >= rule["minimum_spatial_state_duration_s"]
                )
                before = next(
                    (
                        i
                        for i in range(on_start - 1, -1, -1)
                        if series[i]
                        and series[i].get("state") in {"approaching", "before"}
                    ),
                    None,
                )
                exit_end = valid_run_end(
                    series,
                    on_end + 1,
                    {"leaving", "passed"},
                    rule["minimum_spatial_state_duration_s"],
                )
                valid_speeds = [
                    value
                    for value in features.speed_mps[on_start : on_end + 1]
                    if value is not None
                ]
                progression = (
                    series[on_start].get("feature_center_longitudinal_m")
                    - series[on_end].get("feature_center_longitudinal_m")
                    if series[on_start]
                    and series[on_end]
                    and series[on_start].get("feature_center_longitudinal_m")
                    is not None
                    and series[on_end].get("feature_center_longitudinal_m")
                    is not None
                    else 0.0
                )
                if (
                    confirmed_on
                    and before is not None
                    and exit_end is not None
                    and valid_speeds
                    and max(valid_speeds) >= config["speed_bands"]["stationary"]["maximum_mps"]
                    and progression >= rule["minimum_crossing_progress_m"]
                ):
                    start = on_start
                    while (
                        start > 0
                        and timestamps[on_start] - timestamps[start - 1]
                        <= rule["event_pre_roll_s"] + 1e-9
                    ):
                        start -= 1
                    end = exit_end
                    while (
                        end + 1 < len(series)
                        and timestamps[end + 1] - timestamps[exit_end]
                        <= rule["event_post_roll_s"] + 1e-9
                    ):
                        end += 1
                    events.append(
                        make_event(
                            "traversing_crosswalk",
                            start,
                            end,
                            {
                                "road_feature_event_id": f"crosswalk-traversal:{track_id}:{frame_indexes[on_start]}",
                                "crosswalk_id": track_id,
                                "source_feature_ids": track.get("source_feature_ids", []),
                                "entry_frame": frame_indexes[on_start],
                                "exit_confirmation_frame": frame_indexes[exit_end],
                                "crossing_progress_m": round(progression, 3),
                                "maximum_speed_mps": max(valid_speeds),
                            },
                        )
                    )
                index += 1

            # Stationary intervals before or on this crosswalk.
            stationary_limit = config["speed_bands"]["stationary"]["maximum_mps"]
            stationary = [
                bool(
                    relation
                    and relation.get("relation_valid")
                    and relation.get("state") in {"before", "on"}
                    and relation.get("signed_longitudinal_distance_m") is not None
                    and relation["signed_longitudinal_distance_m"]
                    <= rule["stopping_region_distance_m"]
                    and speed is not None
                    and 0.0 <= speed < stationary_limit
                )
                for relation, speed in zip(series, features.speed_mps)
            ]
            index = 0
            while index < len(stationary):
                if not stationary[index]:
                    index += 1
                    continue
                start = index
                while index + 1 < len(stationary) and stationary[index + 1]:
                    index += 1
                end = index
                if observed_duration(start, end) + 1e-9 >= rule["stationary_confirmation_s"]:
                    relation = series[end] or {}
                    events.append(
                        make_event(
                            "stationary_at_crosswalk",
                            start,
                            end,
                            {
                                "road_feature_event_id": f"crosswalk-stationary:{track_id}:{frame_indexes[start]}",
                                "crosswalk_id": track_id,
                                "stationary_relation": relation.get("state"),
                                "distance_m": relation.get("signed_longitudinal_distance_m"),
                                "stationary_maximum_mps": stationary_limit,
                            },
                        )
                    )

                    # Find the sustained deceleration that caused this stop.
                    stationary_confirmed_end = next(
                        candidate
                        for candidate in range(start, end + 1)
                        if observed_duration(start, candidate) + 1e-9
                        >= rule["stationary_confirmation_s"]
                    )
                    confirmed_relation = series[stationary_confirmed_end] or {}
                    decel_start = None
                    for candidate in range(start - 1, -1, -1):
                        candidate_relation = series[candidate]
                        if (
                            not candidate_relation
                            or candidate_relation.get("state")
                            not in {"approaching", "before", "on"}
                        ):
                            break
                        acceleration = features.longitudinal_acceleration_mps2[candidate]
                        if acceleration is not None and acceleration <= rule["deceleration_entry_mps2"]:
                            decel_start = candidate
                        elif decel_start is not None and acceleration is not None and acceleration > rule["deceleration_release_mps2"]:
                            break
                    if (
                        decel_start is not None
                        and features.speed_mps[decel_start] is not None
                        and features.speed_mps[stationary_confirmed_end] is not None
                        and features.speed_mps[decel_start] - features.speed_mps[stationary_confirmed_end]
                        >= rule["minimum_speed_change_mps"]
                    ):
                        accelerations = [
                            value
                            for value in features.longitudinal_acceleration_mps2[
                                decel_start : stationary_confirmed_end + 1
                            ]
                            if value is not None
                        ]
                        events.append(
                            make_event(
                                "stopping_at_crosswalk",
                                decel_start,
                                stationary_confirmed_end,
                                {
                                    "road_feature_event_id": f"crosswalk-stopping:{track_id}:{frame_indexes[decel_start]}",
                                    "crosswalk_id": track_id,
                                    "initial_distance_m": (series[decel_start] or {}).get(
                                        "signed_longitudinal_distance_m"
                                    ),
                                    "final_distance_m": confirmed_relation.get(
                                        "signed_longitudinal_distance_m"
                                    ),
                                    "initial_speed_mps": features.speed_mps[decel_start],
                                    "final_speed_mps": features.speed_mps[stationary_confirmed_end],
                                    "peak_deceleration_mps2": min(accelerations),
                                    "final_relation": confirmed_relation.get("state"),
                                },
                            )
                        )
                index += 1

            # Acceleration from stationary/very-low speed in the crosswalk region.
            index = 1
            while index < len(series):
                previous_speed = features.speed_mps[index - 1]
                acceleration = features.longitudinal_acceleration_mps2[index]
                relation = series[index]
                if not (
                    relation
                    and relation.get("relation_valid")
                    and relation.get("state") in {"before", "on", "leaving", "passed"}
                    and abs(relation.get("signed_longitudinal_distance_m", 1e9))
                    <= rule["stopping_region_distance_m"]
                    and previous_speed is not None
                    and previous_speed <= rule["acceleration_start_max_speed_mps"]
                    and acceleration is not None
                    and acceleration >= rule["acceleration_entry_mps2"]
                ):
                    index += 1
                    continue
                start = index
                end = index
                while end + 1 < len(series):
                    next_relation = series[end + 1]
                    next_acceleration = features.longitudinal_acceleration_mps2[end + 1]
                    next_speed = features.speed_mps[end + 1]
                    if (
                        not next_relation
                        or not next_relation.get("relation_valid")
                        or abs(next_relation.get("signed_longitudinal_distance_m", 1e9))
                        > rule["stopping_region_distance_m"]
                        or next_acceleration is None
                        or next_acceleration <= rule["acceleration_release_mps2"]
                        or (
                            next_speed is not None
                            and next_speed >= rule["acceleration_target_speed_mps"]
                        )
                    ):
                        break
                    end += 1
                end_speed = features.speed_mps[end]
                if (
                    end_speed is not None
                    and end_speed - previous_speed >= rule["minimum_speed_change_mps"]
                    and observed_duration(start, end) + 1e-9
                    >= rule["minimum_event_duration_s"]
                ):
                    accelerations = [
                        value
                        for value in features.longitudinal_acceleration_mps2[
                            start : end + 1
                        ]
                        if value is not None
                    ]
                    events.append(
                        make_event(
                            "accelerating_at_crosswalk",
                            start,
                            end,
                            {
                                "road_feature_event_id": f"crosswalk-accelerating:{track_id}:{frame_indexes[start]}",
                                "crosswalk_id": track_id,
                                "acceleration_began_relation": relation.get("state"),
                                "initial_speed_mps": previous_speed,
                                "final_speed_mps": end_speed,
                                "peak_acceleration_mps2": max(accelerations),
                            },
                        )
                    )
                index = end + 1

        association_by_stopline = {
            item["stopline_track_id"]: item
            for item in relations.get("stopline_crosswalk_associations", [])
            if item.get("valid")
        }
        for track in (
            item
            for item in relations.get("tracks", [])
            if item.get("feature_type") == "stopline"
        ):
            association = association_by_stopline.get(track["track_id"])
            if not association:
                continue
            series = relation_series(track["track_id"], "stopline_relations")
            index = 0
            while index < len(series):
                if not series[index] or series[index].get("state") != "overlapping":
                    index += 1
                    continue
                start = index
                while (
                    index + 1 < len(series)
                    and series[index + 1]
                    and series[index + 1].get("state") == "overlapping"
                ):
                    index += 1
                end = index
                if observed_duration(start, end) + 1e-9 >= rule["minimum_spatial_state_duration_s"]:
                    events.append(
                        make_event(
                            "on_stopline_crosswalk",
                            start,
                            end,
                            {
                                "road_feature_event_id": f"crosswalk-stopline:{track['track_id']}:{frame_indexes[start]}",
                                "stopline_id": track["track_id"],
                                "crosswalk_id": association["crosswalk_track_id"],
                                "association_distance_m": association["geometry_distance_m"],
                                "association_orientation_difference_deg": association[
                                    "orientation_difference_deg"
                                ],
                                "association_confidence": association["confidence"],
                                "association_valid": True,
                            },
                        )
                    )
                index += 1

        return sorted(
            events,
            key=lambda event: (
                event.start_timestamp_s,
                event.scenario,
                event.end_timestamp_s,
            ),
        )
