"""Basic recording-level lane-change detection from existing lane assignments."""

from __future__ import annotations

from statistics import median
from typing import Any

from ms_odd_tagging.features.ego_motion import EgoMotionFeatures

from .scenario_event import ScenarioEvent


class LaneChangeDetector:
    """Confirm stable transitions between adjacent logical route lanes."""

    scenario_name = "lane_changes"
    required_features = frozenset()
    output_scenarios = frozenset(
        {
            "changing_lane",
            "changing_lane_to_left",
            "changing_lane_to_right",
        }
    )

    def detect(
        self,
        frames: list[dict[str, Any]],
        features: EgoMotionFeatures,
        config: dict[str, Any],
        frame_context: dict[int, dict[str, Any]] | None = None,
    ) -> list[ScenarioEvent]:
        if not frames or not frame_context:
            return []

        rule = config["lane_change_detection"]
        timestamps = features.timestamp_s
        frame_indexes = features.frame_index
        contexts = [frame_context.get(frame_index, {}) for frame_index in frame_indexes]
        lanes = [context.get("logical_lane_id") for context in contexts]
        positive_steps = [
            current - previous
            for previous, current in zip(timestamps, timestamps[1:])
            if current > previous
        ]
        nominal_step_s = median(positive_steps) if positive_steps else 0.0

        def observed_duration(start: int, end: int) -> float:
            return timestamps[end] - timestamps[start] + nominal_step_s

        def stable_source_start(source_end: int, source_lane: str) -> int | None:
            start = source_end
            missing_end = inconsistency_end = None
            for index in range(source_end - 1, -1, -1):
                lane = lanes[index]
                if lane == source_lane:
                    start = index
                    missing_end = inconsistency_end = None
                elif lane is None:
                    missing_end = index if missing_end is None else missing_end
                    if (
                        observed_duration(index, missing_end)
                        > rule["maximum_missing_gap_s"] + 1e-9
                    ):
                        break
                else:
                    inconsistency_end = (
                        index if inconsistency_end is None else inconsistency_end
                    )
                    if (
                        observed_duration(index, inconsistency_end)
                        > rule["maximum_temporary_lane_id_inconsistency_s"] + 1e-9
                    ):
                        break
                if (
                    observed_duration(start, source_end) + 1e-9
                    >= rule["stable_source_duration_s"]
                ):
                    return start
            return (
                start
                if observed_duration(start, source_end) + 1e-9
                >= rule["stable_source_duration_s"]
                else None
            )

        def adjacency_direction(
            source_start: int,
            source_end: int,
            source_lane: str,
            target_lane: str,
        ) -> str | None:
            sides = set()
            for index in range(source_end, source_start - 1, -1):
                if (
                    timestamps[source_end] - timestamps[index]
                    > rule["maximum_missing_gap_s"] + 1e-9
                ):
                    break
                context = contexts[index]
                if context.get("logical_lane_id") != source_lane:
                    continue
                if context.get("left_logical_lane_id") == target_lane:
                    sides.add("left")
                if context.get("right_logical_lane_id") == target_lane:
                    sides.add("right")
            return next(iter(sides)) if len(sides) == 1 else None

        def confirm_target(
            target_start: int,
            source_lane: str,
            target_lane: str,
            source_end: int,
        ) -> int | None:
            missing_start = inconsistency_start = None
            for index in range(target_start, len(lanes)):
                lane = lanes[index]
                if lane == target_lane:
                    missing_start = inconsistency_start = None
                elif lane == source_lane:
                    return None
                elif lane is None:
                    missing_start = index if missing_start is None else missing_start
                    if (
                        observed_duration(missing_start, index)
                        > rule["maximum_missing_gap_s"] + 1e-9
                    ):
                        return None
                else:
                    inconsistency_start = (
                        index if inconsistency_start is None else inconsistency_start
                    )
                    if (
                        observed_duration(inconsistency_start, index)
                        > rule["maximum_temporary_lane_id_inconsistency_s"] + 1e-9
                    ):
                        return None
                if (
                    observed_duration(target_start, index) + 1e-9
                    >= rule["stable_target_duration_s"]
                    and timestamps[index] - timestamps[source_end] + 1e-9
                    >= rule["minimum_event_duration_s"]
                ):
                    return index
            return None

        events: list[ScenarioEvent] = []
        physical_id = 0
        last_confirmed_end = -1
        for target_start in range(1, len(lanes)):
            if target_start <= last_confirmed_end:
                continue
            target_lane = lanes[target_start]
            if target_lane is None:
                continue

            source_end = target_start - 1
            while source_end >= 0 and lanes[source_end] is None:
                if (
                    timestamps[target_start] - timestamps[source_end]
                    > rule["maximum_missing_gap_s"]
                ):
                    source_end = -1
                    break
                source_end -= 1
            if source_end < 0:
                continue
            source_lane = lanes[source_end]
            if source_lane is None or source_lane == target_lane:
                continue

            source_start = stable_source_start(source_end, source_lane)
            if source_start is None:
                continue
            direction = adjacency_direction(
                source_start, source_end, source_lane, target_lane
            )
            if direction is None:
                continue
            target_end = confirm_target(
                target_start, source_lane, target_lane, source_end
            )
            if target_end is None:
                continue

            physical_id += 1
            last_confirmed_end = target_end
            physical_event_id = f"lane-change-{physical_id:04d}"
            evidence = {
                "physical_lane_change_event_id": physical_event_id,
                "source_logical_lane_id": source_lane,
                "target_logical_lane_id": target_lane,
                "direction": direction,
                "direction_evidence": f"target_is_source_{direction}_adjacent_lane",
                "transition_frame": frame_indexes[target_start],
                "source_stable_start_frame": frame_indexes[source_start],
                "target_stable_end_frame": frame_indexes[target_end],
                "stable_source_duration_s": rule["stable_source_duration_s"],
                "stable_target_duration_s": rule["stable_target_duration_s"],
                "maximum_missing_gap_s": rule["maximum_missing_gap_s"],
                "maximum_temporary_lane_id_inconsistency_s": rule[
                    "maximum_temporary_lane_id_inconsistency_s"
                ],
                "minimum_event_duration_s": rule["minimum_event_duration_s"],
                "boundary_convention": "inclusive_observed_frames",
                "threshold_provenance": rule["provenance"],
            }
            direction_label = f"changing_lane_to_{direction}"
            for label in ("changing_lane", direction_label):
                events.append(
                    ScenarioEvent(
                        scenario=label,
                        start_frame=frame_indexes[source_end],
                        end_frame=frame_indexes[target_end],
                        start_timestamp_s=timestamps[source_end],
                        end_timestamp_s=timestamps[target_end],
                        duration_s=round(
                            timestamps[target_end] - timestamps[source_end], 6
                        ),
                        detector_version=rule["detector_version"],
                        evidence=dict(evidence),
                    )
                )
        return events
