"""Basic recording-level lane-change detection from existing lane assignments."""

from __future__ import annotations

import math
from statistics import median
from typing import Any

from ms_odd_tagging.features.ego_motion import EgoMotionFeatures

from .scenario_event import ScenarioEvent


INTERSECTION_TOPOLOGY_CLASSES = frozenset(
    {"intersection_unknown", "x-intersection", "t-intersection", "y-intersection", "roundabout"}
)


def _finite_point(value: Any) -> tuple[float, float] | None:
    if (
        not isinstance(value, (list, tuple))
        or len(value) < 2
        or not all(
            isinstance(item, (int, float)) and math.isfinite(item)
            for item in value[:2]
        )
    ):
        return None
    return float(value[0]), float(value[1])


def _cross(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _boundary_crossing(
    start: tuple[float, float],
    end: tuple[float, float],
    boundary: dict[str, Any],
    rule: dict[str, Any],
) -> dict[str, Any] | None:
    """Return a proper ego-center/path intersection with an eligible boundary."""
    attributes = boundary.get("attributes") or {}
    if attributes.get("intersection") is True:
        return None
    # A road edge normalized for lane assignment must not become the ultimate
    # trigger for an ordinary lane change.
    if attributes.get("source_kind", "lane_line") != "lane_line":
        return None
    points = [_finite_point(point) for point in boundary.get("points_lcs_m") or []]
    points = [point for point in points if point is not None]
    if len(points) < 2:
        return None

    motion = (end[0] - start[0], end[1] - start[1])
    motion_length = math.hypot(*motion)
    if motion_length + 1e-9 < float(rule["minimum_center_motion_m"]):
        return None
    minimum_angle = float(rule["minimum_boundary_crossing_angle_deg"])
    endpoint_margin = float(rule["boundary_endpoint_margin_m"])

    for segment_index, (first, second) in enumerate(zip(points, points[1:])):
        edge = (second[0] - first[0], second[1] - first[1])
        edge_length = math.hypot(*edge)
        denominator = _cross(motion, edge)
        if edge_length <= 1e-9 or abs(denominator) <= 1e-9:
            continue
        offset = (first[0] - start[0], first[1] - start[1])
        path_ratio = _cross(offset, edge) / denominator
        edge_ratio = _cross(offset, motion) / denominator
        if not (
            -1e-9 <= path_ratio <= 1.0 + 1e-9
            and -1e-9 <= edge_ratio <= 1.0 + 1e-9
        ):
            continue
        cosine = max(
            -1.0,
            min(
                1.0,
                (motion[0] * edge[0] + motion[1] * edge[1])
                / (motion_length * edge_length),
            ),
        )
        angle = math.degrees(math.acos(cosine))
        crossing_angle = min(angle, 180.0 - angle)
        if crossing_angle + 1e-9 < minimum_angle:
            continue
        intersection = (
            start[0] + path_ratio * motion[0],
            start[1] + path_ratio * motion[1],
        )
        if min(
            math.hypot(intersection[0] - points[0][0], intersection[1] - points[0][1]),
            math.hypot(intersection[0] - points[-1][0], intersection[1] - points[-1][1]),
        ) + 1e-9 < endpoint_margin:
            continue
        return {
            "boundary_edge_id": boundary.get("edge_id"),
            "boundary_segment_index": segment_index,
            "crossing_point_lcs_m": [round(intersection[0], 3), round(intersection[1], 3)],
            "crossing_angle_deg": round(crossing_angle, 2),
            "boundary_attributes": dict(attributes),
            "geometric_direction": (
                "left" if _cross(edge, motion) > 0 else "right"
            ),
            "boundary_segment_lcs_m": [
                [first[0], first[1]], [second[0], second[1]]
            ],
        }
    return None


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
        """Detect lane changes from center crossings, independent of lane-ID switches."""
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
        logical_lanes = [context.get("logical_lane_id") for context in contexts]
        applicability = self._lane_change_applicability(
            contexts, logical_lanes, rule, features
        )
        self.debug_evaluations = [
            {"frame_index": frame_index, **item, "boundary_crossing_candidates": []}
            for frame_index, item in zip(frame_indexes, applicability)
        ]

        def ego_position(index: int) -> tuple[float, float] | None:
            return _finite_point(
                (contexts[index].get("ego") or {}).get("position_lcs_m")
            )

        def signed_line_distance(
            point: tuple[float, float], segment: list[list[float]]
        ) -> float | None:
            if len(segment) != 2:
                return None
            first, second = segment
            edge = (second[0] - first[0], second[1] - first[1])
            length = math.hypot(*edge)
            if length <= 1e-9:
                return None
            offset = (point[0] - first[0], point[1] - first[1])
            return _cross(edge, offset) / length

        def confirmation_end(
            crossing_index: int, crossing: dict[str, Any]
        ) -> tuple[int, float] | None:
            target_time = timestamps[crossing_index] + float(
                rule["crossing_confirmation_s"]
            )
            end = crossing_index
            while end < len(contexts) and timestamps[end] + 1e-9 < target_time:
                if not applicability[end]["lane_change_applicable"]:
                    return None
                end += 1
            if end >= len(contexts) or not applicability[end]["lane_change_applicable"]:
                return None
            target = ego_position(end)
            if target is None:
                return None
            distance = signed_line_distance(
                target, crossing.get("boundary_segment_lcs_m") or []
            )
            if distance is None:
                return None
            expected_sign = 1.0 if crossing["geometric_direction"] == "left" else -1.0
            progress = distance * expected_sign
            if progress + 1e-9 < float(rule["minimum_post_crossing_distance_m"]):
                return None
            return end, progress

        events: list[ScenarioEvent] = []
        physical_id = 0
        last_event_end = -1
        last_edge_time: dict[str, float] = {}
        for index in range(1, len(contexts)):
            if index <= last_event_end:
                continue
            if not all(
                applicability[item]["lane_change_applicable"]
                for item in (index - 1, index)
            ):
                continue
            previous = ego_position(index - 1)
            current = ego_position(index)
            if previous is None or current is None:
                continue
            boundaries = list(contexts[index - 1].get("candidate_boundaries") or [])
            if not boundaries:
                for side in ("left", "right"):
                    boundary = dict(contexts[index - 1].get(f"{side}_boundary") or {})
                    if boundary:
                        boundary["side"] = side
                        boundary["lane_id"] = contexts[index - 1].get("physical_lane_id")
                        boundaries.append(boundary)

            candidates = []
            for boundary_index, boundary in enumerate(boundaries):
                crossing = _boundary_crossing(previous, current, boundary, rule)
                if crossing is None:
                    continue
                edge_key = str(crossing.get("boundary_edge_id") or crossing.get("boundary_segment_lcs_m"))
                if timestamps[index] - last_edge_time.get(edge_key, -math.inf) < float(rule["minimum_crossing_separation_s"]):
                    continue
                confirmed = confirmation_end(index, crossing)
                self.debug_evaluations[index]["boundary_crossing_candidates"].append({
                    "boundary_edge_id": crossing.get("boundary_edge_id"),
                    "boundary_lane_id": boundary.get("lane_id"),
                    "boundary_side": boundary.get("side"),
                    "geometric_direction": crossing["geometric_direction"],
                    "crossing_angle_deg": crossing["crossing_angle_deg"],
                    "confirmed": confirmed is not None,
                })
                if confirmed is None:
                    continue
                end, progress = confirmed
                active_source = boundary.get("lane_id") == contexts[index - 1].get("physical_lane_id")
                candidates.append(
                    (
                        not active_source,
                        -progress,
                        edge_key,
                        boundary_index,
                        boundary,
                        crossing,
                        end,
                        progress,
                    )
                )
            if not candidates:
                continue
            _, _, edge_key, _, boundary, crossing, end, progress = min(candidates)
            start = index - 1
            pre_time = timestamps[index] - float(rule["pre_crossing_event_s"])
            while start > 0 and timestamps[start - 1] + 1e-9 >= pre_time:
                start -= 1

            direction = crossing["geometric_direction"]
            physical_id += 1
            last_event_end = end
            last_edge_time[edge_key] = timestamps[index]
            physical_event_id = f"lane-change-{physical_id:04d}"
            evidence = {
                "physical_lane_change_event_id": physical_event_id,
                "ultimate_trigger": "ego_center_crossed_non_intersection_lane_boundary",
                "direction": direction,
                "direction_evidence": "signed_motion_across_oriented_boundary",
                "crossing_frame": frame_indexes[index],
                "crossing_previous_frame": frame_indexes[index - 1],
                "boundary_lane_id": boundary.get("lane_id"),
                "boundary_side": boundary.get("side"),
                "source_physical_lane_id": contexts[index - 1].get("physical_lane_id"),
                "target_physical_lane_id": contexts[end].get("physical_lane_id"),
                "source_logical_lane_id": contexts[index - 1].get("logical_lane_id"),
                "target_logical_lane_id": contexts[end].get("logical_lane_id"),
                "post_crossing_distance_m": round(progress, 3),
                "target_confirmation_frame": frame_indexes[end],
                "lane_identity_is_confirmation_only": True,
                "lane_change_applicable": True,
                "final_decision_reason": "center_boundary_crossing_with_target_side_persistence",
                **crossing,
            }
            for label in ("changing_lane", f"changing_lane_to_{direction}"):
                events.append(ScenarioEvent(
                    scenario=label,
                    start_frame=frame_indexes[start],
                    end_frame=frame_indexes[end],
                    start_timestamp_s=timestamps[start],
                    end_timestamp_s=timestamps[end],
                    duration_s=round(timestamps[end] - timestamps[start], 6),
                    detector_version=rule["detector_version"],
                    evidence=dict(evidence),
                ))
        return events

    def _detect_lane_transitions_legacy(
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
        applicability = self._lane_change_applicability(contexts, lanes, rule, features)
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

        def find_boundary_crossing(
            source_start: int,
            source_end: int,
            target_start: int,
            direction: str,
        ) -> dict[str, Any] | None:
            boundary = contexts[source_end].get(f"{direction}_boundary") or {}
            earliest_time = timestamps[target_start] - float(
                rule["maximum_crossing_to_lane_transition_s"]
            )
            first = source_start
            while first < target_start and timestamps[first] < earliest_time:
                first += 1
            for index in range(max(1, first), target_start + 1):
                if not all(
                    applicability[item]["lane_change_applicable"]
                    for item in (index - 1, index)
                ):
                    continue
                previous = _finite_point(
                    (contexts[index - 1].get("ego") or {}).get("position_lcs_m")
                )
                current = _finite_point(
                    (contexts[index].get("ego") or {}).get("position_lcs_m")
                )
                if previous is None or current is None:
                    continue
                crossing = _boundary_crossing(previous, current, boundary, rule)
                if crossing is not None:
                    return {
                        **crossing,
                        "boundary_side": direction,
                        "crossing_frame": frame_indexes[index],
                        "crossing_previous_frame": frame_indexes[index - 1],
                    }
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
            crossing = find_boundary_crossing(
                source_start, source_end, target_start, direction
            )
            if crossing is None:
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
                "ultimate_trigger": "ego_center_crossed_non_intersection_source_boundary",
                **crossing,
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
                "final_decision_reason": "ego_center_boundary_crossing_confirmed_by_stable_adjacent_lane_transition",
                "stable_source_duration_s": rule["stable_source_duration_s"],
                "stable_target_duration_s": rule["stable_target_duration_s"],
                "maximum_missing_gap_s": rule["maximum_missing_gap_s"],
                "maximum_temporary_lane_id_inconsistency_s": rule[
                    "maximum_temporary_lane_id_inconsistency_s"
                ],
                "minimum_event_duration_s": rule["minimum_event_duration_s"],
                "maximum_crossing_to_lane_transition_s": rule[
                    "maximum_crossing_to_lane_transition_s"
                ],
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
        features: EgoMotionFeatures,
    ) -> list[dict[str, Any]]:
        suppress_inside = bool(
            rule.get("suppress_lane_change_inside_intersection", True)
        )
        minimum_confidence = float(rule.get("minimum_topology_confidence", 0.0))
        minimum_geometry_confidence = float(
            rule.get("minimum_geometry_confidence", minimum_confidence)
        )
        topology_entry_tolerance_m = float(rule.get("topology_entry_tolerance_m", 0.0))
        suppress_intersection_turn = bool(
            rule.get("suppress_lane_change_during_intersection_turn", True)
        )
        turn_yaw_rate_threshold = float(
            rule.get("intersection_turn_minimum_yaw_rate_rad_s", 0.08)
        )
        turn_yaw_change_threshold_rad = math.radians(
            float(rule.get("intersection_turn_minimum_accumulated_yaw_deg", 5.0))
        )
        turn_yaw_window_s = float(rule.get("intersection_turn_yaw_window_s", 1.0))
        required_stability_frames = max(
            int(rule.get("lane_change_resume_confirmation_frames", 0)),
            int(rule.get("intersection_exit_lane_stability_frames", 0)),
        )

        def accumulated_yaw_change(index: int) -> float | None:
            current = features.unwrapped_heading_rad[index]
            if current is None:
                return None
            start = index
            while (
                start > 0
                and features.timestamp_s[index] - features.timestamp_s[start - 1]
                <= turn_yaw_window_s + 1e-9
            ):
                start -= 1
            start_heading = features.unwrapped_heading_rad[start]
            if start_heading is None:
                return None
            return current - start_heading

        def turn_evidence(index: int) -> tuple[bool, str | None, float | None]:
            yaw_rate = features.yaw_rate_rad_s[index]
            yaw_change = accumulated_yaw_change(index)
            yaw_rate_turning = (
                yaw_rate is not None
                and abs(yaw_rate) + 1e-9 >= turn_yaw_rate_threshold
            )
            yaw_change_turning = (
                yaw_change is not None
                and abs(yaw_change) + 1e-9 >= turn_yaw_change_threshold_rad
            )
            if not yaw_rate_turning and not yaw_change_turning:
                return False, None, (
                    math.degrees(yaw_change) if yaw_change is not None else None
                )
            signed_value = yaw_rate if yaw_rate_turning and yaw_rate is not None else yaw_change
            turn_candidate = (
                "starting_left_turn"
                if signed_value is not None and signed_value > 0
                else "starting_right_turn"
            )
            return True, turn_candidate, (
                math.degrees(yaw_change) if yaw_change is not None else None
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
            topology_subtype = context.get("topology_subtype") or context.get(
                "active_topology_subtype", topology_class
            )
            topology_confidence = float(context.get("topology_confidence") or 0.0)
            component_geometry_confidence = float(
                context.get("component_geometry_confidence") or topology_confidence
            )
            raw_distance = context.get("distance_to_topology_polygon_m")
            distance_to_topology_polygon_m = (
                float(raw_distance)
                if isinstance(raw_distance, (int, float))
                else math.inf
            )
            active_is_intersection = bool(
                context.get("active_is_intersection")
                or context.get("is_intersection_component")
                or topology_subtype in INTERSECTION_TOPOLOGY_CLASSES
            )
            in_topology_area = bool(context.get("ego_inside_topology_polygon")) or (
                distance_to_topology_polygon_m <= topology_entry_tolerance_m
            )
            reliable_intersection = (
                suppress_inside
                and active_is_intersection
                and component_geometry_confidence + 1e-9
                >= minimum_geometry_confidence
            )
            ego_turning, turn_candidate, accumulated_yaw_change_deg = turn_evidence(index)
            inside_intersection_topology = reliable_intersection and in_topology_area
            turning_with_intersection = (
                reliable_intersection
                and suppress_intersection_turn
                and ego_turning
                and not inside_intersection_topology
            )
            intersection_active = (
                inside_intersection_topology or turning_with_intersection
            )

            if intersection_active and not previous_inside:
                pre_intersection_lane_id = last_applicable_lane_id
                post_intersection_lane_id = None
                resume_lane_id = None
                lane_stability_frames = 0
                in_resume_confirmation = False

            if intersection_active:
                lane_change_applicable = False
                suppression_reason = (
                    "suppressed_by_topology_turn"
                    if turning_with_intersection
                    else "suppressed_by_topology"
                )
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
                    "topology_subtype": topology_subtype,
                    "topology_confidence": topology_confidence,
                    "active_is_intersection": active_is_intersection,
                    "active_topology_subtype": topology_subtype,
                    "component_geometry_confidence": component_geometry_confidence,
                    "distance_to_topology_polygon_m": (
                        None
                        if math.isinf(distance_to_topology_polygon_m)
                        else distance_to_topology_polygon_m
                    ),
                    "lane_change_applicable": lane_change_applicable,
                    "lane_change_suppression_reason": suppression_reason,
                    "pre_intersection_lane_id": pre_intersection_lane_id,
                    "current_lane_id": lane_id,
                    "post_intersection_lane_id": post_intersection_lane_id,
                    "lane_stability_frames": lane_stability_frames,
                    "turn_candidate": turn_candidate,
                    "accumulated_yaw_change_deg": accumulated_yaw_change_deg,
                    "final_decision_reason": (
                        "lane_change_not_applicable_during_intersection_turn"
                        if turning_with_intersection
                        else "lane_change_not_applicable_inside_intersection_topology"
                        if intersection_active
                        else suppression_reason
                        or "lane_change_applicable_on_stable_continuing_road"
                    ),
                }
            )
            previous_inside = intersection_active
        return result
