"""Shared state machine for bicycle, motorcycle, and vehicle path crossings."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from statistics import median
from typing import Any

from ms_odd_tagging.features.ego_motion import EgoMotionFeatures

from .scenario_event import ScenarioEvent


SCENARIOS = frozenset(
    {"crossed_by_bike", "crossed_by_motorcycle", "crossed_by_vehicle"}
)


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def _duration(observations: list[dict[str, Any]], start: int, end: int) -> float:
    return max(
        0.0,
        float(observations[end]["timestamp_s"])
        - float(observations[start]["timestamp_s"]),
    )


def _stable_run_end(
    observations: list[dict[str, Any]],
    start: int,
    side: str,
    minimum_duration_s: float,
) -> int | None:
    end = start
    while end + 1 < len(observations) and observations[end + 1]["side"] == side:
        end += 1
        if _duration(observations, start, end) + 1e-9 >= minimum_duration_s:
            return end
    if _duration(observations, start, end) + 1e-9 >= minimum_duration_s:
        return end
    return None


def _with_roll(
    observations: list[dict[str, Any]],
    index: int,
    duration_s: float,
    *,
    before: bool,
) -> int:
    target = float(observations[index]["timestamp_s"]) + (
        -duration_s if before else duration_s
    )
    if before:
        eligible = [
            position
            for position in range(index + 1)
            if float(observations[position]["timestamp_s"]) >= target - 1e-9
        ]
        return eligible[0] if eligible else index
    eligible = [
        position
        for position in range(index, len(observations))
        if float(observations[position]["timestamp_s"]) <= target + 1e-9
    ]
    return eligible[-1] if eligible else index


def _contiguous_segments(
    observations: list[dict[str, Any]],
    nominal_step_s: float,
    maximum_missing_gap_s: float,
) -> list[list[dict[str, Any]]]:
    segments: list[list[dict[str, Any]]] = []
    for observation in observations:
        if (
            not observation.get("relation_valid")
            or not _finite(observation.get("timestamp_s"))
        ):
            continue
        if not segments:
            segments.append([observation])
            continue
        gap = (
            float(observation["timestamp_s"])
            - float(segments[-1][-1]["timestamp_s"])
        )
        if (
            gap <= 0
            or gap > nominal_step_s + maximum_missing_gap_s + 1e-9
        ):
            segments.append([observation])
        else:
            segments[-1].append(observation)
    return segments


def detect_object_path_crossings(
    frames: list[dict[str, Any]],
    config: dict[str, Any],
    relation_payload: dict[str, Any] | None,
) -> tuple[list[ScenarioEvent], list[dict[str, Any]]]:
    """Return confirmed per-object events plus structured rejection diagnostics."""
    if not frames or not relation_payload:
        return [], []
    settings = config["object_path_crossing_interactions"]
    maximum_plausible_speed = float(
        config["object_relations"]["maximum_physically_plausible_object_speed_mps"]
    )
    detector_version = settings["detector_version"]
    timestamps = [
        float(frame["time_since_start_s"])
        for frame in frames
        if _finite(frame.get("time_since_start_s"))
    ]
    steps = [
        current - previous
        for previous, current in zip(timestamps, timestamps[1:])
        if current > previous
    ]
    nominal_step = median(steps) if steps else 0.0
    by_track: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for relation_frame in relation_payload.get("frames", []):
        for relation in relation_frame.get("objects", []):
            by_track[str(relation["track_id"])].append(relation)

    events: list[ScenarioEvent] = []
    diagnostics: list[dict[str, Any]] = []
    category_mapping = settings["category_to_scenario"]
    for track_id, track_observations in sorted(by_track.items()):
        track_observations.sort(
            key=lambda item: (float(item.get("timestamp_s", math.inf)), item.get("frame_index", -1))
        )
        category = track_observations[0].get("normalized_category")
        scenario = category_mapping.get(category)
        if scenario not in SCENARIOS:
            continue
        for observation in track_observations:
            if observation.get("invalid_reason") == "impossible_position_jump":
                diagnostics.append(
                    {
                        "track_id": track_id,
                        "category": category,
                        "reason": "impossible_position_jump",
                        "frame_index": observation.get("frame_index"),
                    }
                )
        segments = _contiguous_segments(
            track_observations,
            nominal_step,
            float(settings["maximum_missing_frame_gap_s"]),
        )
        for observations in segments:
            if len(observations) < 2:
                continue
            if (
                float(observations[-1]["timestamp_s"])
                - float(observations[0]["timestamp_s"])
                < float(settings["minimum_track_age_s"])
            ):
                diagnostics.append(
                    {
                        "track_id": track_id,
                        "category": category,
                        "reason": "insufficient_track_age",
                    }
                )
                continue

            index = 0
            while index < len(observations):
                source_side = observations[index].get("side")
                if source_side not in {"LEFT", "RIGHT"}:
                    if index == 0 and source_side == "INSIDE_ARC":
                        diagnostics.append(
                            {
                                "track_id": track_id,
                                "category": category,
                                "reason": "first_appears_inside_arc",
                                "frame_index": observations[index]["frame_index"],
                            }
                        )
                    index += 1
                    continue
                source_end = _stable_run_end(
                    observations,
                    index,
                    source_side,
                    float(settings["side_stability_duration_s"]),
                )
                if source_end is None:
                    index += 1
                    continue
                target_side = "RIGHT" if source_side == "LEFT" else "LEFT"
                maximum_end_time = (
                    float(observations[source_end]["timestamp_s"])
                    + float(settings["maximum_crossing_duration_s"])
                )
                entry_index = None
                exit_index = None
                target_end = None
                returned_to_source = False
                search = source_end + 1
                while (
                    search < len(observations)
                    and float(observations[search]["timestamp_s"])
                    <= maximum_end_time + 1e-9
                ):
                    side = observations[search].get("side")
                    if side == "INSIDE_ARC" and entry_index is None:
                        entry_index = search
                    elif entry_index is not None and side == source_side:
                        returned_to_source = True
                        break
                    elif entry_index is not None and side == target_side:
                        exit_index = exit_index if exit_index is not None else search
                        target_end = _stable_run_end(
                            observations,
                            search,
                            target_side,
                            float(settings["target_side_stability_duration_s"]),
                        )
                        if target_end is not None:
                            break
                    search += 1

                reason = None
                if returned_to_source:
                    reason = "entered_arc_then_returned_to_source_side"
                elif entry_index is None:
                    reason = "never_entered_forward_arc"
                elif exit_index is None:
                    reason = "disappeared_or_remained_inside_arc"
                elif target_end is None:
                    reason = "opposite_side_not_stable"
                if reason is not None:
                    diagnostics.append(
                        {
                            "track_id": track_id,
                            "category": category,
                            "reason": reason,
                            "source_side": source_side,
                            "source_frame": observations[index]["frame_index"],
                            "entry_frame": (
                                observations[entry_index]["frame_index"]
                                if entry_index is not None
                                else None
                            ),
                        }
                    )
                    index = max(source_end + 1, search)
                    continue

                assert entry_index is not None
                assert exit_index is not None
                assert target_end is not None
                expected_normal_sign = -1.0 if source_side == "LEFT" else 1.0
                approach_index = None
                for candidate_index in range(
                    max(1, source_end), entry_index + 1
                ):
                    current = observations[candidate_index]
                    previous = observations[candidate_index - 1]
                    normal_speed = current.get("path_normal_speed_mps")
                    current_signed = current.get("signed_lateral_distance_m")
                    previous_signed = previous.get(
                        "signed_lateral_distance_m"
                    )
                    if (
                        _finite(normal_speed)
                        and float(normal_speed) * expected_normal_sign
                        >= float(settings["minimum_path_normal_speed_mps"])
                        and _finite(current_signed)
                        and _finite(previous_signed)
                        and abs(float(current_signed))
                        < abs(float(previous_signed)) - 1e-9
                    ):
                        approach_index = candidate_index
                        break
                if approach_index is None:
                    diagnostics.append(
                        {
                            "track_id": track_id,
                            "category": category,
                            "reason": "no_sustained_approach_motion",
                            "source_frame": observations[source_end][
                                "frame_index"
                            ],
                            "entry_frame": observations[entry_index][
                                "frame_index"
                            ],
                        }
                    )
                    index = target_end + 1
                    continue
                crossing_duration = _duration(
                    observations, approach_index, target_end
                )
                arc_dwell_duration = _duration(
                    observations, entry_index, exit_index
                )
                initial_signed = float(
                    observations[approach_index]["signed_lateral_distance_m"]
                )
                final_signed = float(
                    observations[target_end]["signed_lateral_distance_m"]
                )
                lateral_displacement = abs(final_signed - initial_signed)
                initial_center = observations[approach_index].get("center_lcs_m") or []
                final_center = observations[target_end].get("center_lcs_m") or []
                ground_displacement = (
                    math.dist(
                        (float(initial_center[0]), float(initial_center[1])),
                        (float(final_center[0]), float(final_center[1])),
                    )
                    if len(initial_center) >= 2 and len(final_center) >= 2
                    else 0.0
                )
                normal_speeds = [
                    abs(float(item["path_normal_speed_mps"]))
                    for item in observations[approach_index : target_end + 1]
                    if _finite(item.get("path_normal_speed_mps"))
                ]
                signed_normal_speeds = [
                    float(item["path_normal_speed_mps"])
                    for item in observations[approach_index : target_end + 1]
                    if _finite(item.get("path_normal_speed_mps"))
                    and abs(float(item["path_normal_speed_mps"]))
                    >= float(settings["minimum_path_normal_speed_mps"])
                ]
                directional_fraction = (
                    sum(
                        speed * expected_normal_sign > 0
                        for speed in signed_normal_speeds
                    )
                    / len(signed_normal_speeds)
                    if signed_normal_speeds
                    else 0.0
                )
                representative_normal_speed = (
                    median(normal_speeds)
                    if normal_speeds
                    else lateral_displacement / max(crossing_duration, 1e-9)
                )
                projected_slice = observations[
                    approach_index : exit_index + 1
                ]
                projected_confirmations = [
                    item
                    for item in projected_slice
                    if item.get("projected_intersection_valid") is True
                ]
                projection_rejections = Counter(
                    str(item["projection_rejection_reason"])
                    for item in projected_slice
                    if item.get("projection_rejection_reason")
                )
                representative_projection = (
                    min(
                        projected_confirmations,
                        key=lambda item: float(
                            item["time_to_intersection_difference_s"]
                        ),
                    )
                    if projected_confirmations
                    else None
                )
                if (
                    crossing_duration
                    < float(settings["minimum_crossing_duration_s"]) - 1e-9
                ):
                    reason = "crossing_too_short"
                elif (
                    arc_dwell_duration
                    < float(settings["minimum_arc_dwell_duration_s"])
                    - 1e-9
                ):
                    reason = "arc_dwell_too_short"
                elif (
                    crossing_duration
                    > float(settings["maximum_crossing_duration_s"]) + 1e-9
                ):
                    reason = "crossing_too_long"
                elif (
                    lateral_displacement
                    < float(settings["minimum_lateral_displacement_m"]) - 1e-9
                ):
                    reason = "insufficient_lateral_displacement"
                elif (
                    ground_displacement
                    < float(settings["minimum_lateral_displacement_m"]) - 1e-9
                ):
                    reason = "static_object_or_ego_only_motion"
                elif (
                    representative_normal_speed
                    < float(settings["minimum_path_normal_speed_mps"]) - 1e-9
                ):
                    reason = "insufficient_path_normal_motion"
                elif (
                    directional_fraction
                    < float(settings["minimum_directional_motion_fraction"])
                    - 1e-9
                ):
                    reason = "inconsistent_crossing_motion_direction"
                elif len(projected_confirmations) < int(
                    settings["minimum_projected_intersection_confirmations"]
                ):
                    reason = (
                        projection_rejections.most_common(1)[0][0]
                        if projection_rejections
                        else "forward_projected_intersection_not_confirmed"
                    )
                elif any(
                    (
                        item.get("observed_ground_speed_mps") is not None
                        and float(item["observed_ground_speed_mps"])
                        > maximum_plausible_speed
                    )
                    for item in observations[approach_index : target_end + 1]
                ):
                    reason = "impossible_position_jump"
                if reason is not None:
                    diagnostics.append(
                        {
                            "track_id": track_id,
                            "category": category,
                            "reason": reason,
                            "source_frame": observations[source_end]["frame_index"],
                            "entry_frame": observations[entry_index]["frame_index"],
                            "exit_frame": observations[exit_index]["frame_index"],
                            "lateral_displacement_m": round(lateral_displacement, 4),
                            "ground_displacement_m": round(ground_displacement, 4),
                            "arc_dwell_duration_s": round(
                                arc_dwell_duration, 4
                            ),
                            "directional_motion_fraction": round(
                                directional_fraction, 4
                            ),
                            "projected_intersection_confirmations": len(
                                projected_confirmations
                            ),
                            "projection_rejection_reasons": dict(
                                projection_rejections
                            ),
                        }
                    )
                    index = target_end + 1
                    continue

                event_start = _with_roll(
                    observations,
                    approach_index,
                    float(settings["event_pre_roll_s"]),
                    before=True,
                )
                event_end = _with_roll(
                    observations,
                    target_end,
                    float(settings["event_post_roll_s"]),
                    before=False,
                )
                event_slice = observations[event_start : event_end + 1]
                speeds = [
                    float(item["object_speed_mps"])
                    for item in event_slice
                    if _finite(item.get("object_speed_mps"))
                ]
                minimum_path_distance = min(
                    abs(float(item["signed_lateral_distance_m"]))
                    for item in observations[entry_index : exit_index + 1]
                    if _finite(item.get("signed_lateral_distance_m"))
                )
                source_ids = sorted(
                    {
                        str(source_id)
                        for item in event_slice
                        for source_id in item.get("source_object_ids", [])
                        if source_id not in (None, "")
                    }
                )
                direction = (
                    "left_to_right"
                    if source_side == "LEFT"
                    else "right_to_left"
                )
                start_time = float(observations[event_start]["timestamp_s"])
                end_time = float(observations[event_end]["timestamp_s"])
                entry_frame = observations[entry_index]["frame_index"]
                event_id = f"path-crossing:{track_id}:{entry_frame}"
                events.append(
                    ScenarioEvent(
                        scenario=scenario,
                        start_frame=observations[event_start]["frame_index"],
                        end_frame=observations[event_end]["frame_index"],
                        start_timestamp_s=start_time,
                        end_timestamp_s=end_time,
                        duration_s=round(end_time - start_time, 6),
                        detector_version=detector_version,
                        evidence={
                            "object_path_crossing_event_id": event_id,
                            "object_track_id": track_id,
                            "object_track_ids": [track_id],
                            "source_object_ids": source_ids,
                            "original_class": observations[entry_index].get(
                                "class_name"
                            ),
                            "normalized_category": category,
                            "crossing_direction": direction,
                            "initial_side": source_side,
                            "final_side": target_side,
                            "arc_entry_frame": entry_frame,
                            "arc_exit_frame": observations[exit_index][
                                "frame_index"
                            ],
                            "source_side_confirmation_frame": observations[
                                source_end
                            ]["frame_index"],
                            "approach_start_frame": observations[
                                approach_index
                            ]["frame_index"],
                            "target_side_confirmation_frame": observations[
                                target_end
                            ]["frame_index"],
                            "minimum_path_distance_m": round(
                                minimum_path_distance, 4
                            ),
                            "lateral_displacement_m": round(
                                lateral_displacement, 4
                            ),
                            "ground_displacement_m": round(
                                ground_displacement, 4
                            ),
                            "representative_speed_mps": (
                                round(median(speeds), 4) if speeds else None
                            ),
                            "representative_path_normal_speed_mps": round(
                                representative_normal_speed, 4
                            ),
                            "arc_dwell_duration_s": round(
                                arc_dwell_duration, 4
                            ),
                            "directional_motion_fraction": round(
                                directional_fraction, 4
                            ),
                            "projected_intersection_confirmations": len(
                                projected_confirmations
                            ),
                            "projected_intersection_lcs_m": (
                                representative_projection.get(
                                    "projected_intersection_lcs_m"
                                )
                                if representative_projection is not None
                                else None
                            ),
                            "intersection_path_progress_m": (
                                representative_projection.get(
                                    "intersection_path_progress_m"
                                )
                                if representative_projection is not None
                                else None
                            ),
                            "crossing_angle_deg": (
                                representative_projection.get(
                                    "crossing_angle_deg"
                                )
                                if representative_projection is not None
                                else None
                            ),
                            "object_heading_lcs_rad": (
                                representative_projection.get(
                                    "object_heading_lcs_rad"
                                )
                                if representative_projection is not None
                                else None
                            ),
                            "heading_motion_difference_deg": (
                                representative_projection.get(
                                    "heading_motion_difference_deg"
                                )
                                if representative_projection is not None
                                else None
                            ),
                            "ego_time_to_intersection_s": (
                                representative_projection.get(
                                    "ego_time_to_intersection_s"
                                )
                                if representative_projection is not None
                                else None
                            ),
                            "object_time_to_intersection_s": (
                                representative_projection.get(
                                    "object_time_to_intersection_s"
                                )
                                if representative_projection is not None
                                else None
                            ),
                            "time_to_intersection_difference_s": (
                                representative_projection.get(
                                    "time_to_intersection_difference_s"
                                )
                                if representative_projection is not None
                                else None
                            ),
                            "velocity_sources": sorted(
                                {
                                    item.get("velocity_source")
                                    for item in event_slice
                                    if item.get("velocity_source")
                                    not in (None, "unavailable")
                                }
                            ),
                            "interval_convention": (
                                "inclusive observed start/end frames"
                            ),
                            "forward_arc": relation_payload.get("arc", {}),
                            "threshold_provenance": settings.get(
                                "provenance", "provisional"
                            ),
                        },
                    )
                )
                index = target_end + 1

    events.sort(
        key=lambda event: (
            event.start_timestamp_s,
            event.scenario,
            event.evidence.get("object_track_id", ""),
        )
    )
    diagnostics.sort(
        key=lambda item: (
            str(item.get("track_id")),
            int(item.get("source_frame", item.get("frame_index", -1))),
            str(item.get("reason")),
        )
    )
    return events, diagnostics


class ObjectPathCrossingDetector:
    scenario_name = "object_path_crossings"
    required_features = frozenset()
    output_scenarios = SCENARIOS

    def detect(
        self,
        frames: list[dict[str, Any]],
        features: EgoMotionFeatures,
        config: dict[str, Any],
        relation_payload: dict[str, Any] | None = None,
    ) -> list[ScenarioEvent]:
        del features
        events, _ = detect_object_path_crossings(
            frames, config, relation_payload
        )
        return events


__all__ = [
    "ObjectPathCrossingDetector",
    "SCENARIOS",
    "detect_object_path_crossings",
]
