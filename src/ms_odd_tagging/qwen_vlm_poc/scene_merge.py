"""Scene-level deduplication for event-driven VLM candidates."""

from __future__ import annotations

from typing import Any

from .config import VlmPocConfig
from .future_path import future_ego_path, pedestrian_path_distance
from .geometry import ego_speed, object_ego_xy, object_id
from .models import CandidateWindow, EvidenceItem


def _frame_times(recording: dict[str, Any]) -> dict[int, float]:
    return {
        int(frame["frame_index"]): float(frame.get("time_since_start_s") or 0.0)
        for frame in recording.get("frames", [])
        if isinstance(frame.get("frame_index"), int)
    }


def _frames_by_index(recording: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        int(frame["frame_index"]): frame
        for frame in recording.get("frames", [])
        if isinstance(frame.get("frame_index"), int)
    }


def _raw_bounds(candidate: CandidateWindow) -> tuple[int, int]:
    metadata = candidate.metadata or {}
    return (
        int(metadata.get("raw_trigger_start_frame", candidate.start_frame)),
        int(metadata.get("raw_trigger_end_frame", candidate.end_frame)),
    )


def _raw_time_bounds(candidate: CandidateWindow, times: dict[int, float]) -> tuple[float, float]:
    raw_start, raw_end = _raw_bounds(candidate)
    return (
        float(times.get(raw_start, candidate.start_timestamp_s)),
        float(times.get(raw_end, candidate.end_timestamp_s)),
    )


def _uniform_indices(indices: list[int], count: int) -> list[int]:
    values = sorted(set(indices))
    if not values or count <= 0:
        return []
    if len(values) <= count:
        return values
    if count == 1:
        return [values[len(values) // 2]]
    positions = [round(i * (len(values) - 1) / (count - 1)) for i in range(count)]
    return [values[pos] for pos in positions]


def _nearest(values: list[int], target: int) -> int | None:
    if not values:
        return None
    return min(values, key=lambda value: (abs(value - target), value))


def _all_pairwise_close(
    cluster: list[CandidateWindow],
    candidate: CandidateWindow,
    times: dict[int, float],
    gap_s: float,
) -> bool:
    """Avoid transitive scene chaining by requiring closeness to every member."""
    start_t, end_t = _raw_time_bounds(candidate, times)
    for existing in cluster:
        other_start, other_end = _raw_time_bounds(existing, times)
        if start_t > other_end + gap_s + 1e-9 or other_start > end_t + gap_s + 1e-9:
            return False
    return True


def _landmark_event_indices(
    available: list[int],
    raw_start: int,
    raw_end: int,
    count: int,
    frames_by_index: dict[int, dict[str, Any]],
    pedestrian_ids: list[str],
) -> tuple[list[int], dict[str, int | None]]:
    """Select neutral event landmarks instead of fixed fractions of the window."""
    values = sorted(set(available))
    if not values or count <= 0:
        return [], {}
    if len(values) <= count:
        return values, {"pre": values[0], "interaction_onset": values[0], "resolution": values[-1]}

    before = [value for value in values if value < raw_start]
    inside = [value for value in values if raw_start <= value <= raw_end]
    after = [value for value in values if value > raw_end]
    pre = before[-1] if before else values[0]
    onset = _nearest(inside or values, raw_start)
    resolution = _nearest(inside or values, raw_end)
    post = after[0] if after else None

    target_ids = {str(value) for value in pedestrian_ids}
    interaction_frame = None
    interaction_distance = None
    for frame_index in inside:
        frame = frames_by_index.get(frame_index)
        if frame is None:
            continue
        path = future_ego_path(frames_by_index, frame_index)
        distance = pedestrian_path_distance(frame, target_ids, path)
        if distance is None:
            continue
        if interaction_distance is None or distance < interaction_distance:
            interaction_distance = distance
            interaction_frame = frame_index

    min_speed_frame = None
    min_speed = None
    for frame_index in inside:
        frame = frames_by_index.get(frame_index)
        if frame is None:
            continue
        speed = ego_speed(frame)
        if speed is None:
            continue
        if min_speed is None or speed < min_speed:
            min_speed = speed
            min_speed_frame = frame_index

    landmarks = {
        "pre": pre,
        "interaction_onset": onset,
        "closest_pedestrian_to_future_path": interaction_frame,
        "minimum_ego_speed": min_speed_frame,
        "interaction_resolution": resolution,
        "post": post,
    }
    selected: list[int] = []
    for value in landmarks.values():
        if value is not None and value not in selected:
            selected.append(value)
        if len(selected) >= count:
            return sorted(selected[:count]), landmarks

    # Collapsed landmarks are common in short events. Prefer additional frames
    # from the actual trigger interval, then context, while preserving chronology.
    for pool in (inside, values):
        remaining = count - len(selected)
        if remaining <= 0:
            break
        fill = _uniform_indices([value for value in pool if value not in selected], remaining)
        selected.extend(value for value in fill if value not in selected)

    return sorted(selected[:count]), landmarks


def _ego_measurements(
    selected: list[int],
    frames_by_index: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    measurements = []
    for frame_index in selected:
        frame = frames_by_index.get(frame_index)
        if frame is None:
            continue
        timestamp = frame.get("time_since_start_s")
        speed = ego_speed(frame)
        measurements.append(
            {
                "frame": frame_index,
                "time_s": round(float(timestamp), 3)
                if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool)
                else None,
                "speed_mps": round(float(speed), 3) if speed is not None else None,
            }
        )
    return measurements


def _pedestrian_measurements(
    selected: list[int],
    frames_by_index: dict[int, dict[str, Any]],
    pedestrian_ids: list[str],
) -> list[dict[str, Any]]:
    """Serialize neutral per-frame candidate-pedestrian positions in ego coordinates."""
    wanted = {str(value) for value in pedestrian_ids}
    measurements = []
    for frame_index in selected:
        frame = frames_by_index.get(frame_index)
        if frame is None:
            continue
        timestamp = frame.get("time_since_start_s")
        pedestrians = []
        for obj in frame.get("objects", []):
            obj_id = object_id(obj)
            if obj_id not in wanted:
                continue
            position = object_ego_xy(obj, frame)
            if position is None:
                continue
            longitudinal_m, lateral_m = position
            pedestrians.append(
                {
                    "object_id": obj_id,
                    "longitudinal_m": round(float(longitudinal_m), 3),
                    "lateral_m": round(float(lateral_m), 3),
                }
            )
        pedestrians.sort(key=lambda item: item["object_id"])
        measurements.append(
            {
                "frame": frame_index,
                "time_s": round(float(timestamp), 3)
                if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool)
                else None,
                "pedestrians": pedestrians,
            }
        )
    return measurements


def merge_waiting_scene_candidates(
    recording: dict[str, Any],
    candidates: list[CandidateWindow],
    config: VlmPocConfig,
) -> list[CandidateWindow]:
    """Merge truly co-temporal pedestrian candidates into compact VLM scenes.

    Candidate heuristics remain internal. Model-facing scenes carry neutral future
    ego trajectory geometry, target identity, ego speed, and pedestrian positions.
    """
    if not candidates:
        return []

    times = _frame_times(recording)
    frame_lookup = _frames_by_index(recording)
    ordered = sorted(candidates, key=lambda item: (_raw_bounds(item)[0], _raw_bounds(item)[1]))
    clusters: list[list[CandidateWindow]] = []

    for candidate in ordered:
        if not clusters or not _all_pairwise_close(
            clusters[-1], candidate, times, config.event_scene_merge_gap_s
        ):
            clusters.append([candidate])
        else:
            clusters[-1].append(candidate)

    frame_indices = sorted(frame_lookup)
    results: list[CandidateWindow] = []
    recording_id = str(recording.get("recording_id") or candidates[0].recording_id)

    for cluster in clusters:
        context_start = min(item.start_frame for item in cluster)
        context_end = max(item.end_frame for item in cluster)
        raw_start = min(_raw_bounds(item)[0] for item in cluster)
        raw_end = max(_raw_bounds(item)[1] for item in cluster)
        pedestrian_ids = sorted({str(pid) for item in cluster for pid in item.primary_object_ids})
        source_ids = [item.candidate_id for item in cluster]
        source_trigger_intervals = [
            {
                "candidate_id": item.candidate_id,
                "pedestrian_ids": [str(value) for value in item.primary_object_ids],
                "raw_trigger_start_frame": _raw_bounds(item)[0],
                "raw_trigger_end_frame": _raw_bounds(item)[1],
            }
            for item in cluster
        ]

        available = [index for index in frame_indices if context_start <= index <= context_end]
        selected, landmarks = _landmark_event_indices(
            available,
            raw_start,
            raw_end,
            config.max_bev_images,
            frame_lookup,
            pedestrian_ids,
        )
        ego_measurements = _ego_measurements(selected, frame_lookup)
        pedestrian_measurements = _pedestrian_measurements(selected, frame_lookup, pedestrian_ids)
        ego_future_paths = [future_ego_path(frame_lookup, frame_index) for frame_index in selected]
        start_t = times.get(context_start, min(item.start_timestamp_s for item in cluster))
        end_t = times.get(context_end, max(item.end_timestamp_s for item in cluster))
        candidate_id = (
            f"{recording_id}_waiting_for_pedestrian_to_cross_scene_"
            f"{context_start:06d}_{context_end:06d}"
        )
        visual_evidence_id = f"{candidate_id}:bev_sequence"

        results.append(
            CandidateWindow(
                candidate_id=candidate_id,
                recording_id=recording_id,
                scenario="waiting_for_pedestrian_to_cross",
                start_frame=context_start,
                end_frame=context_end,
                start_timestamp_s=float(start_t),
                end_timestamp_s=float(end_t),
                evidence=[
                    EvidenceItem(
                        evidence_id=visual_evidence_id,
                        kind="bev_sequence",
                        summary="Ordered BEVs plus neutral future ego path, ego speed, and pedestrian positions.",
                        data={"frame_indices": selected},
                    )
                ],
                selected_frame_indices=selected,
                primary_object_ids=pedestrian_ids,
                recall_reasons=["scene_level_event_candidate"],
                metadata={
                    "candidate_strategy": "event-driven",
                    "vlm_input_mode": "bev_plus_neutral_future_path_and_motion_measurements",
                    "visual_evidence_id": visual_evidence_id,
                    "scene_merged": len(cluster) > 1,
                    "raw_trigger_start_frame": raw_start,
                    "raw_trigger_end_frame": raw_end,
                    "frame_selection_strategy": "neutral_event_landmarks",
                    "frame_selection_landmarks": landmarks,
                    "ego_measurements": ego_measurements,
                    "pedestrian_measurements": pedestrian_measurements,
                    "ego_future_paths": ego_future_paths,
                    "pedestrian_ids": pedestrian_ids,
                    "source_candidate_ids": source_ids,
                    "source_candidate_count": len(cluster),
                    "source_trigger_intervals": source_trigger_intervals,
                    "scene_merge_policy": "pairwise_raw_interval_proximity",
                    "scene_merge_gap_s": config.event_scene_merge_gap_s,
                },
            )
        )

    return results
