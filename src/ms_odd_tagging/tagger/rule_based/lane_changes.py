"""Basic recording-level lane-change detection from existing lane assignments."""

from __future__ import annotations

from statistics import median
from typing import Any

from ms_odd_tagging.features.ego_motion import EgoMotionFeatures

from .scenario_event import ScenarioEvent


INTERSECTION_TOPOLOGY_CLASSES = frozenset(
    {"x-intersection", "t-intersection", "y-intersection", "roundabout"}
)


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
            self.debug_evaluations = []
            return []

        rule = config["lane_change_detection"]
        timestamps = features.timestamp_s
        frame_indexes = features.frame_index
        contexts = [
            {**frames[index], **frame_context.get(frame_index, {})}
            for index, frame_index in enumerate(frame_indexes)
        ]
        lanes = [context.get("logical_lane_id") for context in contexts]
        applicability = self._lane_change_applicability(contexts, lanes, rule)
        self.debug_evaluations = [
            {"frame_index": frame_index, **item}
            for frame_index, item in zip(frame_indexes, applicability)
        ]
        positive_steps = [
            current - previous
            for previous, current in zip(timestamps, timestamps[1:])
            if current > previous
        ]
        nominal_step_s = median(positive_steps) if positive_steps else 0.0

        def observed_duration(start: int, end: int) -> float:
            return timestamps[end] - timestamps[start] + nominal_step_s

        def stable_source_start(source_end: int, source_lane: str) -> int | None:
            if not applicability[source_end]["lane_change_applicable"]:
                return None
            start = source_end
            missing_end = inconsistency_end = None
            for index in range(source_end - 1, -1, -1):
                if not applicability[index]["lane_change_applicable"]:
                    break
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
                if not applicability[index]["lane_change_applicable"]:
                    break
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
            if not applicability[target_start]["lane_change_applicable"]:
                return None
            missing_start = inconsistency_start = None
            for index in range(target_start, len(lanes)):
                if not applicability[index]["lane_change_applicable"]:
                    return None
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
            if not applicability[target_start]["lane_change_applicable"]:
                continue

            source_end = target_start - 1
            while source_end >= 0 and lanes[source_end] is None:
                if not applicability[source_end]["lane_change_applicable"]:
                    source_end = -1
                    break
                if (
                    timestamps[target_start] - timestamps[source_end]
                    > rule["maximum_missing_gap_s"]
                ):
                    source_end = -1
                    break
                source_end -= 1
            if source_end < 0:
                continue
            if any(
                not item["lane_change_applicable"]
                for item in applicability[source_end : target_start + 1]
            ):
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
                "intersection_active": any(
                    item["intersection_active"]
                    for item in applicability[source_end : target_end + 1]
                ),
                "topology_class": applicability[target_start]["topology_class"],
                "topology_confidence": applicability[target_start][
                    "topology_confidence"
                ],
                "lane_change_applicable": True,
                "lane_change_suppression_reason": None,
                "pre_intersection_lane_id": applicability[target_start][
                    "pre_intersection_lane_id"
                ],
                "current_lane_id": target_lane,
                "post_intersection_lane_id": applicability[target_start][
                    "post_intersection_lane_id"
                ],
                "lane_stability_frames": applicability[target_start][
                    "lane_stability_frames"
                ],
                "turn_candidate": None,
                "accumulated_yaw_change_deg": None,
                "final_decision_reason": "stable_adjacent_lane_transition_on_continuing_road",
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

    def _lane_change_applicability(
        self,
        contexts: list[dict[str, Any]],
        lanes: list[str | None],
        rule: dict[str, Any],
    ) -> list[dict[str, Any]]:
        suppress_inside = bool(
            rule.get("suppress_lane_change_inside_intersection", True)
        )
        minimum_confidence = float(rule.get("minimum_topology_confidence", 0.0))
        required_stability_frames = max(
            int(rule.get("lane_change_resume_confirmation_frames", 0)),
            int(rule.get("intersection_exit_lane_stability_frames", 0)),
        )
        result: list[dict[str, Any]] = []
        previous_inside = False
        pre_intersection_lane_id: str | None = None
        post_intersection_lane_id: str | None = None
        resume_lane_id: str | None = None
        lane_stability_frames = 0
        in_resume_confirmation = False
        last_applicable_lane_id: str | None = None

        for index, context in enumerate(contexts):
            lane_id = lanes[index]
            topology_class = context.get("topology_class", "normal")
            topology_confidence = float(context.get("topology_confidence") or 0.0)
            intersection_active = (
                suppress_inside
                and bool(context.get("ego_inside_topology_polygon"))
                and topology_class in INTERSECTION_TOPOLOGY_CLASSES
                and topology_confidence + 1e-9 >= minimum_confidence
            )

            if intersection_active and not previous_inside:
                pre_intersection_lane_id = last_applicable_lane_id
                post_intersection_lane_id = None
                resume_lane_id = None
                lane_stability_frames = 0
                in_resume_confirmation = False

            if intersection_active:
                lane_change_applicable = False
                suppression_reason = "suppressed_by_topology"
            else:
                if previous_inside:
                    in_resume_confirmation = required_stability_frames > 0
                    post_intersection_lane_id = lane_id
                    resume_lane_id = lane_id
                    lane_stability_frames = 1 if lane_id is not None else 0
                elif in_resume_confirmation:
                    if lane_id is not None and lane_id == resume_lane_id:
                        lane_stability_frames += 1
                    else:
                        resume_lane_id = lane_id
                        post_intersection_lane_id = lane_id
                        lane_stability_frames = 1 if lane_id is not None else 0
                    if lane_stability_frames >= required_stability_frames:
                        in_resume_confirmation = False
                elif lane_id is not None and lane_id == last_applicable_lane_id:
                    lane_stability_frames += 1
                elif lane_id is not None:
                    lane_stability_frames = 1
                else:
                    lane_stability_frames = 0

                lane_change_applicable = not in_resume_confirmation
                suppression_reason = (
                    "waiting_for_post_intersection_lane_stability"
                    if in_resume_confirmation
                    else None
                )

            if lane_change_applicable and lane_id is not None:
                last_applicable_lane_id = lane_id

            result.append(
                {
                    "intersection_active": intersection_active,
                    "topology_class": topology_class,
                    "topology_confidence": topology_confidence,
                    "lane_change_applicable": lane_change_applicable,
                    "lane_change_suppression_reason": suppression_reason,
                    "pre_intersection_lane_id": pre_intersection_lane_id,
                    "current_lane_id": lane_id,
                    "post_intersection_lane_id": post_intersection_lane_id,
                    "lane_stability_frames": lane_stability_frames,
                    "final_decision_reason": (
                        "lane_change_not_applicable_inside_intersection_topology"
                        if intersection_active
                        else suppression_reason
                        or "lane_change_applicable_on_stable_continuing_road"
                    ),
                }
            )
            previous_inside = intersection_active
        return result
