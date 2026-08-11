"""Scene-level deduplication for event-driven VLM candidates."""

from __future__ import annotations

from typing import Any

from .config import VlmPocConfig
from .future_path import DEFAULT_CORRIDOR_HALF_WIDTH_M, distance_to_polyline, future_ego_path, pedestrian_path_distance
from .geometry import ego_speed, lcs_to_ego, object_ego_xy, object_id
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

    for pool in (inside, values):
        remaining = count - len(selected)
        if remaining <= 0:
            break
        fill = _uniform_indices([value for value in pool if value not in selected], remaining)
        selected.extend(value for value in fill if value not in selected)

    return sorted(selected[:count]), landmarks


def _path_points(path_geometry: dict[str, Any]) -> list[tuple[float, float]]:
    return [
        (float(row["longitudinal_m"]), float(row["lateral_m"]))
        for row in path_geometry.get("points", [])
        if isinstance(row.get("longitudinal_m"), (int, float))
        and not isinstance(row.get("longitudinal_m"), bool)
        and isinstance(row.get("lateral_m"), (int, float))
        and not isinstance(row.get("lateral_m"), bool)
    ]


def _pedestrian_path_distances(
    available: list[int],
    frames_by_index: dict[int, dict[str, Any]],
    pedestrian_id: str,
) -> list[dict[str, Any]]:
    """Neutral distance between one pedestrian and actual future ego corridor."""
    rows: list[dict[str, Any]] = []
    for frame_index in available:
        frame = frames_by_index.get(frame_index)
        if frame is None:
            continue
        path = future_ego_path(frames_by_index, frame_index)
        points = _path_points(path)
        if not points:
            continue
        for obj in frame.get("objects", []):
            if object_id(obj) != pedestrian_id:
                continue
            position = object_ego_xy(obj, frame)
            if position is None:
                continue
            distance = distance_to_polyline(position, points)
            if distance is None:
                continue
            timestamp = frame.get("time_since_start_s")
            rows.append(
                {
                    "frame": frame_index,
                    "time_s": round(float(timestamp), 3)
                    if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool)
                    else None,
                    "longitudinal_m": round(float(position[0]), 3),
                    "lateral_m": round(float(position[1]), 3),
                    "distance_to_future_path_m": round(float(distance), 3),
                    "corridor_half_width_m": path.get("corridor_half_width_m", DEFAULT_CORRIDOR_HALF_WIDTH_M),
                }
            )
    return rows


def _pedestrian_focus_score(
    available: list[int],
    frames_by_index: dict[int, dict[str, Any]],
    pedestrian_id: str,
    raw_start: int,
    raw_end: int,
) -> dict[str, Any]:
    """Rank one pedestrian with geometry/motion only; never model-facing truth."""
    distances = _pedestrian_path_distances(available, frames_by_index, pedestrian_id)
    if not distances:
        return {
            "pedestrian_id": pedestrian_id,
            "score": -1.0,
            "min_distance_to_future_path_m": None,
            "lateral_span_m": 0.0,
            "speed_overlap_min_mps": None,
            "observed_frame_count": 0,
        }
    inside = [row for row in distances if raw_start <= int(row["frame"]) <= raw_end] or distances
    min_distance = min(float(row["distance_to_future_path_m"]) for row in inside)
    laterals = [float(row["lateral_m"]) for row in inside]
    lateral_span = max(laterals) - min(laterals) if laterals else 0.0
    speeds = [
        ego_speed(frames_by_index[row["frame"]])
        for row in inside
        if frames_by_index.get(row["frame"]) is not None and ego_speed(frames_by_index[row["frame"]]) is not None
    ]
    min_speed = min(speeds) if speeds else None
    temporal_overlap = len([row for row in distances if raw_start <= int(row["frame"]) <= raw_end])
    score = (
        -min_distance
        + 0.25 * abs(lateral_span)
        + (2.0 - min(float(min_speed), 2.0) if min_speed is not None else 0.0)
        + min(temporal_overlap, 10) * 0.01
    )
    closest = min(inside, key=lambda row: float(row["distance_to_future_path_m"]))
    return {
        "pedestrian_id": pedestrian_id,
        "score": round(float(score), 3),
        "min_distance_to_future_path_m": round(float(min_distance), 3),
        "lateral_span_m": round(float(lateral_span), 3),
        "speed_overlap_min_mps": round(float(min_speed), 3) if min_speed is not None else None,
        "observed_frame_count": len(distances),
        "closest_frame": closest["frame"],
    }


def _pedestrian_landmark_indices(
    available: list[int],
    raw_start: int,
    raw_end: int,
    count: int,
    frames_by_index: dict[int, dict[str, Any]],
    pedestrian_id: str,
) -> tuple[list[int], dict[str, int | None], list[dict[str, Any]]]:
    """Select per-pedestrian interaction landmarks for a focused VLM request."""
    values = sorted(set(available))
    if not values or count <= 0:
        return [], {}, []
    distances = _pedestrian_path_distances(values, frames_by_index, pedestrian_id)
    if not distances:
        selected, landmarks = _landmark_event_indices(
            values, raw_start, raw_end, count, frames_by_index, [pedestrian_id]
        )
        return selected, landmarks, distances

    inside = [row for row in distances if raw_start <= int(row["frame"]) <= raw_end] or distances
    corridor_rows = [
        row
        for row in inside
        if float(row["distance_to_future_path_m"]) <= float(row.get("corridor_half_width_m") or DEFAULT_CORRIDOR_HALF_WIDTH_M)
    ]
    speeds = [
        index
        for index in values
        if frames_by_index.get(index) is not None and ego_speed(frames_by_index[index]) is not None
    ]
    before = [value for value in values if value < raw_start]
    after = [value for value in values if value > raw_end]
    closest = min(inside, key=lambda row: float(row["distance_to_future_path_m"]))
    min_speed_frame = min(speeds, key=lambda index: ego_speed(frames_by_index[index])) if speeds else None
    landmarks: dict[str, int | None] = {
        "before_approach": before[-1] if before else values[0],
        "raw_trigger_start": _nearest(values, raw_start),
        "first_entry_toward_corridor": int(corridor_rows[0]["frame"]) if corridor_rows else int(closest["frame"]),
        "closest_to_future_corridor": int(closest["frame"]),
        "minimum_ego_speed_during_interaction": min_speed_frame,
        "exit_or_resolution": _nearest(values, raw_end),
        "post_interaction": after[0] if after else None,
    }
    selected: list[int] = []
    for key in (
        "before_approach",
        "raw_trigger_start",
        "first_entry_toward_corridor",
        "closest_to_future_corridor",
        "minimum_ego_speed_during_interaction",
        "exit_or_resolution",
        "post_interaction",
    ):
        value = landmarks.get(key)
        if value is not None and value not in selected:
            selected.append(value)
        if len(selected) >= count:
            break
    if len(selected) < count:
        remaining = [value for value in values if value not in selected and raw_start <= value <= raw_end]
        selected.extend(_uniform_indices(remaining, count - len(selected)))
    return sorted(set(selected))[:count], landmarks, distances


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


def _dense_ego_speed_series(
    available: list[int],
    frames_by_index: dict[int, dict[str, Any]],
    *,
    max_points: int = 25,
) -> list[dict[str, Any]]:
    """Compact the full scene speed curve while preserving the minimum-speed frame."""
    valid = [
        index
        for index in available
        if frames_by_index.get(index) is not None and ego_speed(frames_by_index[index]) is not None
    ]
    if not valid:
        return []
    min_frame = min(valid, key=lambda index: ego_speed(frames_by_index[index]))
    sampled = _uniform_indices(valid, max(1, max_points - 1))
    if min_frame not in sampled:
        sampled.append(min_frame)
    sampled = sorted(set(sampled))
    if len(sampled) > max_points:
        non_min = [index for index in sampled if index != min_frame]
        sampled = sorted(_uniform_indices(non_min, max_points - 1) + [min_frame])
    return _ego_measurements(sampled, frames_by_index)


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


def _reference_pedestrian_tracks(
    reference_frame: int | None,
    available: list[int],
    frames_by_index: dict[int, dict[str, Any]],
    pedestrian_ids: list[str],
    *,
    max_points_per_pedestrian: int = 24,
) -> dict[str, Any] | None:
    """Express each observed candidate track in one fixed BEV coordinate frame."""
    if reference_frame is None:
        return None
    anchor = frames_by_index.get(reference_frame)
    if anchor is None:
        return None
    anchor_time = anchor.get("time_since_start_s")
    anchor_time = float(anchor_time) if isinstance(anchor_time, (int, float)) else 0.0
    wanted = {str(value) for value in pedestrian_ids}
    tracks: dict[str, list[dict[str, Any]]] = {value: [] for value in wanted}
    for frame_index in available:
        frame = frames_by_index.get(frame_index)
        if frame is None:
            continue
        timestamp = frame.get("time_since_start_s")
        for obj in frame.get("objects", []):
            obj_id = object_id(obj)
            if obj_id not in wanted:
                continue
            position = obj.get("position_lcs_m") or obj.get("center_lcs_m")
            if not isinstance(position, (list, tuple)) or len(position) < 2:
                continue
            longitudinal_m, lateral_m = lcs_to_ego(position, anchor)
            tracks[obj_id].append(
                {
                    "frame": frame_index,
                    "time_offset_s": round(
                        float(timestamp) - anchor_time,
                        3,
                    )
                    if isinstance(timestamp, (int, float))
                    else None,
                    "longitudinal_m": round(float(longitudinal_m), 3),
                    "lateral_m": round(float(lateral_m), 3),
                }
            )
    serialized = []
    for obj_id in sorted(tracks):
        rows = tracks[obj_id]
        if not rows:
            continue
        indices = _uniform_indices(list(range(len(rows))), max_points_per_pedestrian)
        serialized.append(
            {
                "object_id": obj_id,
                "points": [rows[index] for index in indices],
            }
        )
    return {
        "reference_frame": reference_frame,
        "coordinate_frame": "reference_frame_ego_centered_heading_aligned",
        "pedestrians": serialized,
    }


def merge_waiting_scene_candidates(
    recording: dict[str, Any],
    candidates: list[CandidateWindow],
    config: VlmPocConfig,
) -> list[CandidateWindow]:
    """Merge truly co-temporal pedestrian candidates into compact VLM scenes.

    Candidate heuristics remain internal. Model-facing scenes carry neutral future
    ego trajectory geometry, target identity, dense ego speed, and pedestrian tracks.
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

        scene_available = [index for index in frame_indices if context_start <= index <= context_end]
        start_t = times.get(context_start, min(item.start_timestamp_s for item in cluster))
        end_t = times.get(context_end, max(item.end_timestamp_s for item in cluster))
        parent_candidate_id = (
            f"{recording_id}_waiting_for_pedestrian_to_cross_scene_"
            f"{context_start:06d}_{context_end:06d}"
        )
        focus_scores = []
        for item in cluster:
            item_raw_start, item_raw_end = _raw_bounds(item)
            item_available = [index for index in frame_indices if item.start_frame <= index <= item.end_frame]
            for pedestrian_id in sorted({str(value) for value in item.primary_object_ids}):
                score = _pedestrian_focus_score(
                    item_available,
                    frame_lookup,
                    pedestrian_id,
                    item_raw_start,
                    item_raw_end,
                )
                score["source_candidate_id"] = item.candidate_id
                score["raw_trigger_start_frame"] = item_raw_start
                score["raw_trigger_end_frame"] = item_raw_end
                score["candidate_context_start_frame"] = item.start_frame
                score["candidate_context_end_frame"] = item.end_frame
                focus_scores.append(score)
        focus_rank = sorted(
            focus_scores,
            key=lambda row: (
                -float(row.get("score") or -1.0),
                str(row.get("pedestrian_id") or ""),
            ),
        )

        for rank, focus in enumerate(focus_rank, start=1):
            pedestrian_id = str(focus["pedestrian_id"])
            item_context_start = int(focus["candidate_context_start_frame"])
            item_context_end = int(focus["candidate_context_end_frame"])
            item_raw_start = int(focus["raw_trigger_start_frame"])
            item_raw_end = int(focus["raw_trigger_end_frame"])
            available = [index for index in frame_indices if item_context_start <= index <= item_context_end]
            selected, landmarks, path_distances = _pedestrian_landmark_indices(
                available,
                item_raw_start,
                item_raw_end,
                config.max_bev_images,
                frame_lookup,
                pedestrian_id,
            )
            ego_measurements = _ego_measurements(selected, frame_lookup)
            ego_speed_series = _dense_ego_speed_series(available, frame_lookup)
            pedestrian_measurements = _pedestrian_measurements(selected, frame_lookup, [pedestrian_id])
            ego_future_paths = [future_ego_path(frame_lookup, frame_index) for frame_index in selected]
            reference_frame = (
                landmarks.get("closest_to_future_corridor")
                or landmarks.get("first_entry_toward_corridor")
                or landmarks.get("raw_trigger_start")
            )
            pedestrian_tracks_reference = _reference_pedestrian_tracks(
                reference_frame,
                available,
                frame_lookup,
                [pedestrian_id],
            )
            candidate_id = f"{parent_candidate_id}_ped_{pedestrian_id}"
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
                            summary="Focused BEVs for one candidate pedestrian with observed trail, neutral future ego path, and dense ego speed.",
                            data={"frame_indices": selected, "primary_pedestrian_id": pedestrian_id},
                        )
                    ],
                    selected_frame_indices=selected,
                    primary_object_ids=[pedestrian_id],
                    recall_reasons=["focused_scene_level_event_candidate"],
                    metadata={
                        "candidate_strategy": "event-driven",
                        "vlm_input_mode": "focused_bev_primary_pedestrian_track_future_path_and_dense_speed",
                        "focused_vlm_request": True,
                        "focused_primary_pedestrian_id": pedestrian_id,
                        "focused_rank": rank,
                        "focused_rank_count": len(focus_rank),
                        "focused_rank_score": focus,
                        "visual_evidence_id": visual_evidence_id,
                        "parent_scene_candidate_id": parent_candidate_id,
                        "scene_merged": len(cluster) > 1,
                        "raw_trigger_start_frame": item_raw_start,
                        "raw_trigger_end_frame": item_raw_end,
                        "scene_raw_trigger_start_frame": raw_start,
                        "scene_raw_trigger_end_frame": raw_end,
                        "frame_selection_strategy": "focused_primary_pedestrian_landmarks",
                        "frame_selection_landmarks": landmarks,
                        "ego_measurements": ego_measurements,
                        "ego_speed_series": ego_speed_series,
                        "pedestrian_measurements": pedestrian_measurements,
                        "pedestrian_tracks_reference": pedestrian_tracks_reference,
                        "ego_future_paths": ego_future_paths,
                        "pedestrian_ids": [pedestrian_id],
                        "scene_pedestrian_ids": pedestrian_ids,
                        "source_candidate_ids": source_ids,
                        "source_candidate_count": len(cluster),
                        "source_trigger_intervals": source_trigger_intervals,
                        "source_candidate_id": focus.get("source_candidate_id"),
                        "pedestrian_path_distance_series": path_distances,
                        "scene_merge_policy": "pairwise_raw_interval_proximity_with_focused_pedestrian_subrequests",
                        "scene_merge_gap_s": config.event_scene_merge_gap_s,
                    },
                )
            )

        if not focus_rank:
            selected, landmarks = _landmark_event_indices(
                scene_available,
                raw_start,
                raw_end,
                config.max_bev_images,
                frame_lookup,
                pedestrian_ids,
            )
            ego_measurements = _ego_measurements(selected, frame_lookup)
            ego_speed_series = _dense_ego_speed_series(scene_available, frame_lookup)
            pedestrian_measurements = _pedestrian_measurements(selected, frame_lookup, pedestrian_ids)
            ego_future_paths = [future_ego_path(frame_lookup, frame_index) for frame_index in selected]
            reference_frame = landmarks.get("closest_pedestrian_to_future_path") or landmarks.get("interaction_onset")
            pedestrian_tracks_reference = _reference_pedestrian_tracks(
                reference_frame,
                scene_available,
                frame_lookup,
                pedestrian_ids,
            )
            candidate_id = parent_candidate_id
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
                        summary="Ordered BEVs with observed candidate trails plus neutral future ego path and dense ego speed.",
                        data={"frame_indices": selected},
                    )
                ],
                selected_frame_indices=selected,
                primary_object_ids=pedestrian_ids,
                recall_reasons=["scene_level_event_candidate"],
                    metadata={
                        "candidate_strategy": "event-driven",
                        "vlm_input_mode": "bev_plus_neutral_future_path_tracks_and_dense_speed",
                        "visual_evidence_id": visual_evidence_id,
                        "scene_merged": len(cluster) > 1,
                        "raw_trigger_start_frame": raw_start,
                        "raw_trigger_end_frame": raw_end,
                        "frame_selection_strategy": "neutral_event_landmarks",
                        "frame_selection_landmarks": landmarks,
                        "ego_measurements": ego_measurements,
                        "ego_speed_series": ego_speed_series,
                        "pedestrian_measurements": pedestrian_measurements,
                        "pedestrian_tracks_reference": pedestrian_tracks_reference,
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
