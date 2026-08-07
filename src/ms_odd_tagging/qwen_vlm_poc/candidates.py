"""Deterministic recall-oriented candidate generation for the VLM POC."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ms_odd_tagging.features.ego_motion import extract_ego_motion_features
from ms_odd_tagging.features.object_relations import build_object_relations
from ms_odd_tagging.features.road_feature_relations import build_road_feature_relations
from ms_odd_tagging.features.traffic_light_context import build_traffic_light_context
from ms_odd_tagging.features.traffic_relations import build_traffic_relations
from ms_odd_tagging.tagger.rule_based.registry import load_config as load_rule_config

from .config import TRAFFIC_LIGHT_LABELS, VlmPocConfig
from .evidence import frame_summary, selected_window_frames
from .geometry import (
    ego_acceleration,
    ego_heading,
    ego_position,
    ego_speed,
    finite,
    motion_state,
    normalized_class,
    object_ego_xy,
    object_id,
)
from .models import CandidateWindow, EvidenceItem, ScenarioName


CandidateGenerator = Callable[[dict[str, Any], VlmPocConfig], list[CandidateWindow]]


@dataclass(frozen=True)
class ScenarioSpec:
    name: str
    candidate_generator: CandidateGenerator
    dedupe: bool = False


def pedestrian_corridor_conflict(
    frame: dict[str, Any],
    obj: dict[str, Any],
    config: VlmPocConfig,
) -> dict[str, Any]:
    xy = object_ego_xy(obj, frame)
    if xy is None:
        return {"conflict": False, "reason": "missing_position"}
    longitudinal, lateral = xy
    distance = math.hypot(longitudinal, lateral)
    velocity = obj.get("relative_velocity_ego_mps") or obj.get("velocity_lcs_mps") or []
    moving_toward_corridor = False
    lateral_speed = None
    if isinstance(velocity, dict) and finite(velocity.get("lateral")):
        lateral_speed = float(velocity["lateral"])
    elif isinstance(velocity, (list, tuple)) and len(velocity) >= 2 and finite(velocity[1]):
        lateral_speed = float(velocity[1])
    if lateral_speed is not None:
        moving_toward_corridor = abs(lateral) > 0.5 and lateral * lateral_speed < 0
    in_corridor = (
        -config.pedestrian_behind_m <= longitudinal <= config.pedestrian_forward_m
        and abs(lateral) <= config.pedestrian_corridor_lateral_m
    )
    near = distance <= config.pedestrian_near_radius_m
    ahead_or_entering = longitudinal >= -config.pedestrian_behind_m and (
        in_corridor or moving_toward_corridor
    )
    return {
        "conflict": bool(near and ahead_or_entering),
        "distance_m": round(distance, 3),
        "longitudinal_m": round(longitudinal, 3),
        "lateral_m": round(lateral, 3),
        "in_future_corridor": in_corridor,
        "moving_toward_corridor": moving_toward_corridor,
        "lateral_speed_mps": round(lateral_speed, 3) if lateral_speed is not None else None,
        "reason": "near_future_corridor_or_entering" if near and ahead_or_entering else "no_corridor_conflict",
    }


def _velocity_longitudinal_lateral(obj: dict[str, Any]) -> tuple[float | None, float | None]:
    velocity = obj.get("relative_velocity_ego_mps")
    if isinstance(velocity, dict):
        longitudinal = velocity.get("longitudinal")
        lateral = velocity.get("lateral")
        return (
            float(longitudinal) if finite(longitudinal) else None,
            float(lateral) if finite(lateral) else None,
        )
    velocity = obj.get("velocity_lcs_mps")
    if isinstance(velocity, (list, tuple)) and len(velocity) >= 2:
        return (
            float(velocity[0]) if finite(velocity[0]) else None,
            float(velocity[1]) if finite(velocity[1]) else None,
        )
    return None, None


def _position_lcs_xy(obj: dict[str, Any]) -> tuple[float, float] | None:
    point = obj.get("position_lcs_m") or obj.get("center_lcs_m")
    if isinstance(point, (list, tuple)) and len(point) >= 2 and finite(point[0]) and finite(point[1]):
        return float(point[0]), float(point[1])
    return None


def _pedestrian_motion_summary(
    window: list[dict[str, Any]],
    pedestrian_id: str,
    conflict_track: list[dict[str, Any]],
) -> dict[str, Any]:
    samples = []
    longitudinal_velocities = []
    lateral_velocities = []
    moving_toward = False
    for frame in window:
        frame_index = int(frame.get("frame_index"))
        timestamp = frame.get("time_since_start_s")
        for obj in _pedestrian_objects(frame):
            if object_id(obj) != pedestrian_id:
                continue
            point = _position_lcs_xy(obj)
            xy = object_ego_xy(obj, frame)
            lon_v, lat_v = _velocity_longitudinal_lateral(obj)
            if lon_v is not None:
                longitudinal_velocities.append(lon_v)
            if lat_v is not None:
                lateral_velocities.append(lat_v)
            if xy is not None and lat_v is not None and abs(xy[1]) > 0.5 and xy[1] * lat_v < 0:
                moving_toward = True
            if point is not None:
                samples.append(
                    {
                        "frame_index": frame_index,
                        "time_since_start_s": float(timestamp) if finite(timestamp) else None,
                        "position_lcs_m": point,
                    }
                )
            break

    displacement = None
    speed = None
    if len(samples) >= 2:
        first = samples[0]
        last = samples[-1]
        displacement = math.hypot(
            last["position_lcs_m"][0] - first["position_lcs_m"][0],
            last["position_lcs_m"][1] - first["position_lcs_m"][1],
        )
        t0 = first["time_since_start_s"]
        t1 = last["time_since_start_s"]
        if t0 is not None and t1 is not None and t1 > t0:
            speed = displacement / (t1 - t0)

    corridor_entry_frame = None
    for item in conflict_track:
        conflict = item.get("conflict") or {}
        if conflict.get("in_future_corridor"):
            corridor_entry_frame = item.get("frame_index")
            break
    if not moving_toward:
        moving_toward = any((item.get("conflict") or {}).get("moving_toward_corridor") for item in conflict_track)

    if speed is None:
        motion_state_value = "unknown"
    elif speed >= 0.5:
        motion_state_value = "moving"
    elif speed >= 0.15:
        motion_state_value = "slow"
    else:
        motion_state_value = "stationary"

    return {
        "first_frame": samples[0]["frame_index"] if samples else None,
        "last_frame": samples[-1]["frame_index"] if samples else None,
        "pedestrian_speed_mps": round(speed, 3) if speed is not None else None,
        "pedestrian_displacement_m": round(displacement, 3) if displacement is not None else None,
        "pedestrian_motion_state": motion_state_value,
        "longitudinal_velocity_mps": round(sum(longitudinal_velocities) / len(longitudinal_velocities), 3)
        if longitudinal_velocities
        else None,
        "lateral_velocity_mps": round(sum(lateral_velocities) / len(lateral_velocities), 3)
        if lateral_velocities
        else None,
        "moving_toward_corridor": bool(moving_toward),
        "corridor_entry_frame": corridor_entry_frame,
    }


def _waiting_bev_frame_indices(
    window: list[dict[str, Any]],
    ped_tracks: dict[str, list[dict[str, Any]]],
    response_frames: list[int],
    config: VlmPocConfig,
) -> list[int]:
    if not window:
        return []
    by_index = {int(frame["frame_index"]): frame for frame in window}
    all_conflicts = [
        item
        for track in ped_tracks.values()
        for item in track
        if isinstance(item.get("frame_index"), int)
    ]
    corridor_entries = [
        item
        for item in all_conflicts
        if (item.get("conflict") or {}).get("in_future_corridor")
    ]
    entry_frame = min((int(item["frame_index"]) for item in corridor_entries), default=None)
    strongest_frame = min(
        (
            (
                float((item.get("conflict") or {}).get("distance_m")),
                int(item["frame_index"]),
            )
            for item in all_conflicts
            if finite((item.get("conflict") or {}).get("distance_m"))
        ),
        default=(math.inf, None),
    )[1]
    first_conflict = min((int(item["frame_index"]) for item in all_conflicts), default=None)
    last_conflict = max((int(item["frame_index"]) for item in all_conflicts), default=None)
    response_or_exit = None
    valid_response_frames = [
        int(index)
        for index in response_frames
        if isinstance(index, int) and int(index) in by_index
    ]
    if valid_response_frames:
        response_or_exit = max(valid_response_frames)
    if response_or_exit is None:
        response_or_exit = last_conflict

    candidates = [
        int(window[0]["frame_index"]),
        (entry_frame - 1) if entry_frame is not None else ((first_conflict - 1) if first_conflict is not None else None),
        entry_frame,
        strongest_frame,
        response_or_exit,
        int(window[-1]["frame_index"]),
    ]
    selected = []
    for frame_index in candidates:
        if frame_index is None:
            continue
        if frame_index not in by_index:
            continue
        if frame_index not in selected:
            selected.append(frame_index)
    if len(selected) < config.max_bev_images:
        for frame in selected_window_frames(window, 0, len(window) - 1, config):
            frame_index = int(frame["frame_index"])
            if frame_index not in selected:
                selected.append(frame_index)
            if len(selected) >= config.max_bev_images:
                break
    return sorted(selected[: config.max_bev_images])


def _pedestrian_objects(frame: dict[str, Any]) -> list[dict[str, Any]]:
    return [obj for obj in frame.get("objects", []) if normalized_class(obj) == "pedestrian"]


def _ego_response(frame: dict[str, Any], config: VlmPocConfig) -> bool:
    speed = ego_speed(frame)
    accel = ego_acceleration(frame)
    state = motion_state(frame)
    return (
        state in {"stationary", "slow", "decelerating", "stopping"}
        or (speed is not None and speed <= config.pedestrian_slow_speed_mps)
        or (accel is not None and accel <= config.pedestrian_decel_mps2)
    )


def _topology_signal(frame: dict[str, Any], config: VlmPocConfig) -> dict[str, Any]:
    topology_class = str(
        frame.get("topology_class")
        or frame.get("topology_subtype")
        or frame.get("active_topology_subtype")
        or "normal"
    )
    confidence = frame.get("topology_confidence")
    confidence_f = float(confidence) if finite(confidence) else None
    arm_count = frame.get("arm_count") or frame.get("external_corridor_count")
    arm_count_i = int(arm_count) if isinstance(arm_count, int) else None
    nearby = (frame.get("ld") or {}).get("nearby_feature_ids") or {}
    roadmark_count = len(nearby.get("roadmarks") or [])
    lane_line_count = len(nearby.get("lane_lines") or [])
    active = topology_class in config.intersection_classes and (
        confidence_f is None or confidence_f >= config.minimum_intersection_confidence
    )
    connected = arm_count_i is not None and arm_count_i >= 3
    road_feature_support = roadmark_count > 0
    return {
        "active": bool(active or connected),
        "topology_class": topology_class,
        "topology_confidence": confidence_f,
        "external_corridor_count": arm_count_i,
        "roadmark_count": roadmark_count,
        "lane_line_count": lane_line_count,
        "road_feature_support": road_feature_support,
    }


def _angle_delta(start: float, end: float) -> float:
    return math.atan2(math.sin(end - start), math.cos(end - start))


def _cumulative_heading_change(headings: list[float]) -> float:
    if len(headings) < 2:
        return 0.0
    return sum(abs(_angle_delta(a, b)) for a, b in zip(headings, headings[1:]))


def _representative_window_frames(
    window: list[dict[str, Any]],
    strongest_frame_index: int | None,
    config: VlmPocConfig,
) -> list[int]:
    if not window:
        return []
    count = max(1, config.max_bev_images)
    indices = [int(window[0]["frame_index"])]
    if strongest_frame_index is not None:
        indices.append(int(strongest_frame_index))
    if len(window) > 1:
        indices.append(int(window[-1]["frame_index"]))
    deduped = []
    for index in indices:
        if index not in deduped:
            deduped.append(index)
    if len(deduped) < count and len(window) > 2:
        middle = int(window[len(window) // 2]["frame_index"])
        if middle not in deduped:
            deduped.insert(1, middle)
    if len(deduped) < count:
        for frame in selected_window_frames(window, 0, len(window) - 1, config):
            frame_index = int(frame["frame_index"])
            if frame_index not in deduped:
                deduped.append(frame_index)
            if len(deduped) >= count:
                break
    return sorted(deduped[:count])


def _window_positions(frames: list[dict[str, Any]], config: VlmPocConfig) -> list[tuple[int, int]]:
    if not frames:
        return []
    positions = []
    start = 0
    while start < len(frames):
        start_t = float(frames[start].get("time_since_start_s") or 0.0)
        end = start
        while end + 1 < len(frames):
            next_t = frames[end + 1].get("time_since_start_s")
            if not finite(next_t) or float(next_t) > start_t + config.window_seconds + 1e-9:
                break
            end += 1
        positions.append((start, end))
        next_start = start + 1
        while next_start < len(frames):
            next_t = frames[next_start].get("time_since_start_s")
            if finite(next_t) and float(next_t) >= start_t + config.candidate_stride_seconds - 1e-9:
                break
            next_start += 1
        if next_start <= start:
            next_start = start + 1
        start = next_start
    return positions


def _candidate_id(recording_id: str, scenario: str, start_frame: int, end_frame: int) -> str:
    return f"{recording_id}_{scenario}_{start_frame:06d}_{end_frame:06d}"


def _selected_frame_set(selected: list[dict[str, Any]], window: list[dict[str, Any]]) -> set[int]:
    indices = {int(frame["frame_index"]) for frame in selected if isinstance(frame.get("frame_index"), int)}
    if window:
        indices.add(int(window[0]["frame_index"]))
        indices.add(int(window[-1]["frame_index"]))
    return indices


def _compact_intersection_line_data(
    window: list[dict[str, Any]],
    line_evidence: list[dict[str, Any]],
    selected: list[dict[str, Any]],
) -> dict[str, Any]:
    selected_indices = _selected_frame_set(selected, window)
    unique_ids = sorted(
        {
            str(line_id)
            for evidence in line_evidence
            for line_id in evidence.get("intersection_true_lane_line_ids", [])
        }
    )
    active_frames = [
        int(frame["frame_index"])
        for frame, evidence in zip(window, line_evidence)
        if evidence.get("count", 0) > 0 and isinstance(frame.get("frame_index"), int)
    ]
    sampled_frames = []
    for frame, evidence in zip(window, line_evidence):
        frame_index = int(frame["frame_index"])
        if frame_index not in selected_indices and evidence.get("count", 0) <= 0:
            continue
        if frame_index not in selected_indices and sampled_frames:
            continue
        sampled_frames.append(
            {
                "frame_index": frame_index,
                "time_since_start_s": frame.get("time_since_start_s"),
                "count": evidence.get("count", 0),
                "intersection_true_lane_line_ids_sample": [
                    str(line_id)
                    for line_id in (evidence.get("intersection_true_lane_line_ids") or [])[:12]
                ],
            }
        )
    return {
        "frame_count_with_intersection_true_lane_lines": len(active_frames),
        "first_active_frame": min(active_frames) if active_frames else None,
        "last_active_frame": max(active_frames) if active_frames else None,
        "max_intersection_true_lane_line_count": max((item.get("count", 0) for item in line_evidence), default=0),
        "unique_lane_line_id_count": len(unique_ids),
        "unique_lane_line_ids_sample": unique_ids[:24],
        "sampled_frames": sampled_frames,
        "warning": (
            "Multiple intersection=True lane lines can belong to the same physical intersection. "
            "Do not count lane-line IDs as connected roads or as final proof of on_intersection."
        ),
    }


def _intersection_bev_frame_indices(
    all_frames: list[dict[str, Any]],
    start_pos: int,
    window: list[dict[str, Any]],
    strongest_frame_index: int,
    config: VlmPocConfig,
    *,
    include_pre_context: bool,
) -> list[int]:
    selected = _representative_window_frames(window, strongest_frame_index, config)
    if not include_pre_context or start_pos <= 0 or not selected:
        return selected
    pre_pos = max(0, start_pos - 10)
    pre_index = int(all_frames[pre_pos]["frame_index"])
    if pre_index not in selected:
        selected = [pre_index] + selected
    if len(selected) <= config.max_bev_images:
        return sorted(selected)

    protected = {
        pre_index,
        int(window[0]["frame_index"]),
        int(window[-1]["frame_index"]),
        strongest_frame_index,
    }
    trimmed = list(selected)
    for index in list(trimmed):
        if len(trimmed) <= config.max_bev_images:
            break
        if index not in protected:
            trimmed.remove(index)
    return sorted(trimmed[: config.max_bev_images])


def generate_candidates(
    recording: dict[str, Any],
    scenario: ScenarioName,
    config: VlmPocConfig,
) -> list[CandidateWindow]:
    spec = SCENARIO_REGISTRY.get(str(scenario))
    if spec is None:
        raise ValueError(f"unsupported scenario: {scenario}")
    candidates = spec.candidate_generator(recording, config)
    return dedupe_overlapping_candidates(candidates, config) if spec.dedupe else candidates


def generate_waiting_candidates(recording: dict[str, Any], config: VlmPocConfig) -> list[CandidateWindow]:
    frames = recording.get("frames", [])
    recording_id = str(recording.get("recording_id") or "unknown")
    results = []
    for start_pos, end_pos in _window_positions(frames, config):
        window = frames[start_pos : end_pos + 1]
        ped_tracks: dict[str, list[dict[str, Any]]] = defaultdict(list)
        response_frames = []
        for frame in window:
            if _ego_response(frame, config):
                response_frames.append(frame.get("frame_index"))
            for obj in _pedestrian_objects(frame):
                conflict = pedestrian_corridor_conflict(frame, obj, config)
                if conflict["conflict"]:
                    ped_tracks[object_id(obj)].append(
                        {
                            "frame_index": frame.get("frame_index"),
                            "object_id": object_id(obj),
                            "conflict": conflict,
                        }
                    )
        if not ped_tracks or not response_frames:
            continue
        selected_indices = _waiting_bev_frame_indices(window, ped_tracks, response_frames, config)
        motion_by_pedestrian = {
            pedestrian_id: _pedestrian_motion_summary(window, pedestrian_id, track)
            for pedestrian_id, track in ped_tracks.items()
        }
        start_frame = int(window[0]["frame_index"])
        end_frame = int(window[-1]["frame_index"])
        cid = _candidate_id(recording_id, "waiting_for_pedestrian_to_cross", start_frame, end_frame)
        evidence = [
            EvidenceItem(
                f"{cid}:ego_motion",
                "ego_motion",
                "Ego speed, acceleration, heading, motion state across the candidate window.",
                {"frames": [frame_summary(frame) for frame in window]},
            ),
            EvidenceItem(
                f"{cid}:future_corridor",
                "ego_future_corridor",
                "Ego-aligned future corridor used only for deterministic candidate recall.",
                {
                    "longitudinal_range_m": [-config.pedestrian_behind_m, config.pedestrian_forward_m],
                    "lateral_abs_m": config.pedestrian_corridor_lateral_m,
                },
            ),
            EvidenceItem(
                f"{cid}:pedestrian_conflicts",
                "pedestrian_corridor_conflict",
                "Pedestrians near, ahead of, or moving toward ego's expected corridor.",
                {
                    "tracks": dict(ped_tracks),
                    "motion": motion_by_pedestrian,
                    "ego_response_frames": response_frames,
                },
            ),
        ]
        results.append(
            CandidateWindow(
                candidate_id=cid,
                recording_id=recording_id,
                scenario="waiting_for_pedestrian_to_cross",
                start_frame=start_frame,
                end_frame=end_frame,
                start_timestamp_s=float(window[0].get("time_since_start_s") or 0.0),
                end_timestamp_s=float(window[-1].get("time_since_start_s") or 0.0),
                evidence=evidence,
                selected_frame_indices=selected_indices,
                primary_object_ids=sorted(k for k in ped_tracks if k),
                recall_reasons=["pedestrian_corridor_conflict", "ego_slow_or_decelerating"],
            )
        )
    return results


def generate_intersection_candidates(recording: dict[str, Any], config: VlmPocConfig) -> list[CandidateWindow]:
    frames = recording.get("frames", [])
    recording_id = str(recording.get("recording_id") or "unknown")
    results = []
    for start_pos, end_pos in _window_positions(frames, config):
        window = frames[start_pos : end_pos + 1]
        signals = [_topology_signal(frame, config) for frame in window]
        line_evidence = [_intersection_line_evidence(frame, recording) for frame in window]
        intersection_line_frames = [
            {
                "frame_index": frame.get("frame_index"),
                "time_since_start_s": frame.get("time_since_start_s"),
                **evidence,
            }
            for frame, evidence in zip(window, line_evidence)
            if evidence["count"] > 0
        ]
        if not intersection_line_frames:
            continue
        strongest_frame_index = max(
            (
                (int(evidence.get("count") or 0), int(frame["frame_index"]))
                for frame, evidence in zip(window, line_evidence)
                if isinstance(frame.get("frame_index"), int)
            ),
            default=(0, int(window[0]["frame_index"])),
        )[1]
        selected_indices_for_window = _intersection_bev_frame_indices(
            frames,
            start_pos,
            window,
            strongest_frame_index,
            config,
            include_pre_context=len(results) == 1,
        )
        selected = [
            frame
            for frame in window
            if int(frame["frame_index"]) in set(selected_indices_for_window)
        ]
        selected_indices = _selected_frame_set(selected, window)
        start_frame = int(window[0]["frame_index"])
        end_frame = int(window[-1]["frame_index"])
        cid = _candidate_id(recording_id, "on_intersection", start_frame, end_frame)
        lane_counts = [item["lane_line_count"] for item in signals]
        sampled_signals = [
            {"frame_index": int(frame["frame_index"]), **signal}
            for frame, signal in zip(window, signals)
            if int(frame["frame_index"]) in selected_indices
        ]
        evidence = [
            EvidenceItem(
                f"{cid}:ego_motion",
                "ego_motion",
                "Ego pose, heading, and speed for selected frames in the candidate window.",
                {"frames": [frame_summary(frame) for frame in window if int(frame["frame_index"]) in selected_indices]},
            ),
            EvidenceItem(
                f"{cid}:intersection_true_lane_lines",
                "intersection_true_lane_lines",
                "LD lane-line pieces marked intersection=True; used only to recall windows for VLM BEV verification.",
                _compact_intersection_line_data(window, line_evidence, selected),
            ),
            EvidenceItem(
                f"{cid}:intersection_context",
                "intersection_context",
                "Optional context only; topology class and corridor count are not trusted recall filters.",
                {
                    "sampled_frames": sampled_signals,
                    "max_roadmark_count": max([item["roadmark_count"] for item in signals], default=0),
                    "lane_line_count_min": min(lane_counts) if lane_counts else 0,
                    "lane_line_count_max": max(lane_counts) if lane_counts else 0,
                    "lane_boundary_count_changes": (max(lane_counts) - min(lane_counts)) if lane_counts else 0,
                },
            ),
        ]
        results.append(
            CandidateWindow(
                candidate_id=cid,
                recording_id=recording_id,
                scenario="on_intersection",
                start_frame=start_frame,
                end_frame=end_frame,
                start_timestamp_s=float(window[0].get("time_since_start_s") or 0.0),
                end_timestamp_s=float(window[-1].get("time_since_start_s") or 0.0),
                evidence=evidence,
                selected_frame_indices=selected_indices_for_window,
                recall_reasons=["ld_intersection_true_lane_lines"],
                metadata={
                    "dedupe_key": "ld_intersection_true_lane_lines",
                    "topology_class_not_used_for_recall": True,
                    "corridor_count_not_used_for_recall": True,
                },
            )
        )
    return results


def generate_starting_u_turn_candidates(recording: dict[str, Any], config: VlmPocConfig) -> list[CandidateWindow]:
    frames = recording.get("frames", [])
    recording_id = str(recording.get("recording_id") or "unknown")
    results = []
    for start_pos, end_pos in _window_positions(frames, config):
        window = frames[start_pos : end_pos + 1]
        if len(window) < 3:
            continue
        headings = [ego_heading(frame) for frame in window]
        net_delta = _angle_delta(headings[0], headings[-1])
        cumulative_delta = _cumulative_heading_change(headings)
        max_step = max(
            (abs(_angle_delta(a, b)) for a, b in zip(headings, headings[1:])),
            default=0.0,
        )
        if (
            abs(net_delta) < config.u_turn_min_heading_change_rad
            and cumulative_delta < config.u_turn_min_cumulative_heading_change_rad
        ):
            continue
        strongest_pos = max(
            range(1, len(window)),
            key=lambda pos: abs(_angle_delta(headings[pos - 1], headings[pos])),
        )
        strongest_frame_index = int(window[strongest_pos]["frame_index"])
        start_frame = int(window[0]["frame_index"])
        end_frame = int(window[-1]["frame_index"])
        cid = _candidate_id(recording_id, "starting_u_turn", start_frame, end_frame)
        positions = [ego_position(frame) for frame in window]
        displacement = math.hypot(positions[-1][0] - positions[0][0], positions[-1][1] - positions[0][1])
        evidence = [
            EvidenceItem(
                f"{cid}:ego_motion",
                "ego_motion",
                "Ego pose, speed, heading, and motion state across the candidate U-turn window.",
                {"frames": [frame_summary(frame) for frame in window]},
            ),
            EvidenceItem(
                f"{cid}:heading_change",
                "ego_heading_change",
                "High-recall U-turn prefilter based on ego heading change over time.",
                {
                    "net_heading_change_rad": round(net_delta, 4),
                    "net_heading_change_deg": round(math.degrees(net_delta), 2),
                    "absolute_net_heading_change_rad": round(abs(net_delta), 4),
                    "cumulative_heading_change_rad": round(cumulative_delta, 4),
                    "max_step_heading_change_rad": round(max_step, 4),
                    "strongest_frame_index": strongest_frame_index,
                    "turn_direction": "left" if net_delta > 0 else "right",
                    "displacement_m": round(displacement, 3),
                },
            ),
        ]
        results.append(
            CandidateWindow(
                candidate_id=cid,
                recording_id=recording_id,
                scenario="starting_u_turn",
                start_frame=start_frame,
                end_frame=end_frame,
                start_timestamp_s=float(window[0].get("time_since_start_s") or 0.0),
                end_timestamp_s=float(window[-1].get("time_since_start_s") or 0.0),
                evidence=evidence,
                selected_frame_indices=_representative_window_frames(window, strongest_frame_index, config),
                recall_reasons=["large_ego_heading_change"],
                metadata={"dedupe_key": "ego_u_turn_motion"},
            )
        )
    return results


def _feature_by_id(store: dict[str, Any], kind: str, feature_id: str) -> dict[str, Any]:
    features = store.get(kind) or []
    if isinstance(features, dict):
        value = features.get(str(feature_id))
        return value if isinstance(value, dict) else {}
    if isinstance(features, list):
        for item in features:
            if not isinstance(item, dict):
                continue
            candidate_ids = (
                item.get("id"),
                item.get("feature_id"),
                item.get("line_id"),
                item.get("lane_line_id"),
                item.get("road_boundary_id"),
                item.get("roadmark_id"),
            )
            if str(feature_id) in {str(value) for value in candidate_ids if value is not None}:
                return item
    return {}


def _rule_frame_context(recording: dict[str, Any]) -> dict[int, dict[str, Any]]:
    context = {}
    for frame in recording.get("frames", []):
        frame_index = frame.get("frame_index")
        if frame_index is None:
            continue
        context[int(frame_index)] = {
            key: frame[key]
            for key in (
                "topology_class",
                "ego_inside_topology_polygon",
                "distance_to_topology_polygon_m",
                "topology_confidence",
                "active_is_intersection",
                "active_topology_subtype",
                "active_topology_component",
                "component_geometry_confidence",
                "subtype_confidence",
                "intersection_evidence_score",
                "is_intersection_component",
                "topology_subtype",
                "logical_lane_id",
                "left_logical_lane_id",
                "right_logical_lane_id",
            )
            if key in frame
        }
    return context


def _phase1_traffic_light_context_by_frame(recording: dict[str, Any]) -> dict[int, dict[str, Any]]:
    try:
        rule_config = load_rule_config()
        feature_config = rule_config["feature_extraction"]
        features = extract_ego_motion_features(
            recording.get("frames", []),
            max_sample_gap_s=feature_config["max_sample_gap_s"],
            heading_change_horizon_s=feature_config["heading_change_horizon_s"],
            jerk_mode=rule_config["jerk"]["calculation_mode"],
        )
        road_relations = build_road_feature_relations(
            recording, rule_config["road_feature_relations"]
        )
        object_relations = build_object_relations(
            recording, rule_config["object_relations"]
        )
        frame_context = _rule_frame_context(recording)
        traffic_relations = build_traffic_relations(
            recording.get("frames", []),
            features,
            object_relations,
            rule_config,
            frame_context=frame_context,
        )
        payload = build_traffic_light_context(
            recording,
            features,
            road_relations,
            traffic_relations,
            rule_config,
            frame_context=frame_context,
        )
    except Exception:
        return {}
    return {
        int(frame["frame_index"]): frame
        for frame in payload.get("frames", [])
        if isinstance(frame.get("frame_index"), int)
    }


def _feature_mentions_traffic_light(feature: Any) -> bool:
    if isinstance(feature, dict):
        return any(_feature_mentions_traffic_light(value) for value in feature.values())
    if isinstance(feature, list):
        return any(_feature_mentions_traffic_light(value) for value in feature)
    text = str(feature).lower()
    return "traffic_light" in text or "traffic light" in text or "signal" in text


def _traffic_light_evidence(frame: dict[str, Any], recording: dict[str, Any], config: VlmPocConfig) -> dict[str, Any]:
    objects = []
    for obj in frame.get("objects", []):
        cls = normalized_class(obj)
        if cls in config.traffic_light_classes or "traffic_light" in cls:
            xy = object_ego_xy(obj, frame)
            objects.append(
                {
                    "frame_index": frame.get("frame_index"),
                    "object_id": object_id(obj),
                    "class": cls,
                    "ego_xy_m": [round(xy[0], 3), round(xy[1], 3)] if xy else None,
                }
            )
    nearby = (frame.get("ld") or {}).get("nearby_feature_ids") or {}
    store = recording.get("ld_feature_store") or {}
    feature_ids = []
    for kind in ("roadmarks", "topologies", "lanes", "lane_lines"):
        for feature_id in nearby.get(kind) or []:
            feature = _feature_by_id(store, kind, str(feature_id))
            if _feature_mentions_traffic_light(feature):
                feature_ids.append({"kind": kind, "feature_id": str(feature_id)})
    return {"objects": objects, "ld_features": feature_ids, "has_signal": bool(objects or feature_ids)}


def _frame_traffic_light_context(frame: dict[str, Any]) -> dict[str, Any] | None:
    context = frame.get("traffic_light_context")
    return context if isinstance(context, dict) else None


def _traffic_light_path_objects(frame: dict[str, Any], config: VlmPocConfig) -> list[dict[str, Any]]:
    objects = []
    for obj in frame.get("objects", []):
        cls = normalized_class(obj)
        if cls not in config.traffic_light_classes and "traffic_light" not in cls:
            continue
        xy = object_ego_xy(obj, frame)
        if xy is None:
            continue
        longitudinal, lateral = xy
        distance = math.hypot(longitudinal, lateral)
        path_compatible = (
            -config.traffic_light_backward_m <= longitudinal <= config.traffic_light_forward_m
            and abs(lateral) <= config.traffic_light_path_lateral_m
        )
        objects.append(
            {
                "object_id": object_id(obj),
                "class": cls,
                "ego_distance_m": round(distance, 3),
                "longitudinal_m": round(longitudinal, 3),
                "lateral_m": round(lateral, 3),
                "path_compatible": path_compatible,
                "association_confidence": 0.65 if path_compatible else 0.15,
                "association_reason": "ego_forward_path_corridor" if path_compatible else "outside_ego_path_corridor",
            }
        )
    return objects


def _stopline_feature_evidence(frame: dict[str, Any], recording: dict[str, Any]) -> dict[str, Any]:
    context = _frame_traffic_light_context(frame)
    if context:
        stopline = context.get("stopline") or {}
        if stopline.get("id"):
            return {
                "id": str(stopline.get("id")),
                "distance_m": stopline.get("distance_m"),
                "relation": stopline.get("relation"),
                "association_confidence": stopline.get("association_confidence") or stopline.get("confidence"),
                "source": "phase1_traffic_light_context",
            }
    nearby = (frame.get("ld") or {}).get("nearby_feature_ids") or {}
    store = recording.get("ld_feature_store") or {}
    ego_x, ego_y = ego_position(frame)
    best: dict[str, Any] | None = None
    for feature_id in nearby.get("roadmarks") or []:
        feature = _feature_by_id(store, "roadmarks", str(feature_id))
        text = json_like_lower(feature)
        if "stopline" not in text and "stop_line" not in text and "stop line" not in text:
            continue
        distance = feature.get("signed_longitudinal_distance_m") if isinstance(feature, dict) else None
        if distance is None and isinstance(feature, dict):
            point = feature.get("position_lcs_m") or feature.get("center_lcs_m")
            if isinstance(point, (list, tuple)) and len(point) >= 2 and finite(point[0]) and finite(point[1]):
                distance = float(point[0]) - ego_x
        if not finite(distance):
            distance = None
        relation = "unknown"
        if distance is not None:
            if abs(float(distance)) <= 1.5:
                relation = "on_stopline"
            elif float(distance) > 1.5:
                relation = "before_stopline"
            else:
                relation = "passed_stopline"
        item = {
            "id": str(feature_id),
            "distance_m": round(float(distance), 3) if distance is not None else None,
            "relation": relation,
            "association_confidence": "medium",
            "source": "ld_roadmark_stopline",
        }
        if best is None or abs(float(item["distance_m"] or 1e9)) < abs(float(best["distance_m"] or 1e9)):
            best = item
    return best or {
        "id": None,
        "distance_m": None,
        "relation": "unknown",
        "association_confidence": "none",
        "source": "unavailable",
    }


def json_like_lower(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(f"{key} {json_like_lower(val)}" for key, val in value.items()).lower()
    if isinstance(value, list):
        return " ".join(json_like_lower(item) for item in value).lower()
    return str(value).lower()


def _lead_evidence(frame: dict[str, Any], config: VlmPocConfig) -> dict[str, Any]:
    context = _frame_traffic_light_context(frame)
    if context:
        lead = context.get("lead") or {}
        if lead.get("exists"):
            return {**lead, "source": "phase1_traffic_light_context"}
    candidates = []
    for obj in frame.get("objects", []):
        cls = normalized_class(obj)
        if not any(token in cls for token in ("vehicle", "car", "truck", "bus", "motorcycle", "bike")):
            continue
        xy = object_ego_xy(obj, frame)
        if xy is None:
            continue
        longitudinal, lateral = xy
        same_path = bool(
            obj.get("same_lane")
            or obj.get("path_compatible")
            or obj.get("same_path_compatible")
            or obj.get("same_logical_lane")
        )
        if not same_path:
            continue
        if 0.0 <= longitudinal <= config.traffic_light_lead_forward_m and abs(lateral) <= config.traffic_light_lead_lateral_m:
            candidates.append((longitudinal, lateral, obj))
    if not candidates:
        return {
            "exists": False,
            "object_id": None,
            "longitudinal_distance_m": None,
            "lateral_distance_m": None,
            "same_path_compatible": False,
            "confidence": "none",
            "source": "no_path_compatible_vehicle",
        }
    longitudinal, lateral, obj = min(candidates, key=lambda item: item[0])
    return {
        "exists": True,
        "object_id": object_id(obj),
        "longitudinal_distance_m": round(longitudinal, 3),
        "lateral_distance_m": round(lateral, 3),
        "same_path_compatible": True,
        "confidence": "medium",
        "source": "object_same_path_compatible",
    }


def _intersection_line_evidence(frame: dict[str, Any], recording: dict[str, Any]) -> dict[str, Any]:
    nearby = (frame.get("ld") or {}).get("nearby_feature_ids") or {}
    store = recording.get("ld_feature_store") or {}
    ids = []
    for feature_id in nearby.get("lane_lines") or []:
        feature = _feature_by_id(store, "lane_lines", str(feature_id))
        attributes = feature.get("attributes") if isinstance(feature, dict) else None
        is_intersection = bool(
            isinstance(feature, dict)
            and (
                feature.get("intersection") is True
                or (isinstance(attributes, dict) and attributes.get("intersection") is True)
            )
        )
        if is_intersection:
            ids.append(str(feature_id))
    return {"intersection_true_lane_line_ids": ids, "count": len(ids)}


def _traffic_light_frame_signal(frame: dict[str, Any], recording: dict[str, Any], config: VlmPocConfig) -> dict[str, Any]:
    context = _frame_traffic_light_context(frame)
    topology = _topology_signal(frame, config)
    line_evidence = _intersection_line_evidence(frame, recording)
    stopline = _stopline_feature_evidence(frame, recording)
    path_lights = _traffic_light_path_objects(frame, config)
    raw_signal = _traffic_light_evidence(frame, recording, config)
    if context:
        context_lights = context.get("traffic_lights") or []
        path_lights = [
            {
                "object_id": str(light.get("object_id")),
                "class": light.get("class_name") or light.get("class"),
                "ego_distance_m": light.get("distance_m"),
                "longitudinal_m": light.get("signed_longitudinal_m"),
                "lateral_m": light.get("signed_lateral_m"),
                "path_compatible": bool(light.get("relevant")),
                "association_confidence": light.get("association_confidence"),
                "association_reason": ",".join(light.get("association_reasons") or []),
            }
            for light in context_lights
        ]
    motion = _frame_traffic_light_context(frame).get("ego_motion") if context else None
    if not isinstance(motion, dict):
        motion = {
            "speed_mps": ego_speed(frame),
            "acceleration_mps2": ego_acceleration(frame),
            "stationary": motion_state(frame) == "stationary",
            "stopping": ego_acceleration(frame) <= -0.4 if finite(ego_acceleration(frame)) else False,
            "accelerating": ego_acceleration(frame) >= 0.3 if finite(ego_acceleration(frame)) else False,
            "temporal_state": motion_state(frame),
        }
    lead = _lead_evidence(frame, config)
    stopline_distance = stopline.get("distance_m")
    stopline_near = stopline.get("id") is not None and (
        stopline_distance is None or abs(float(stopline_distance)) <= config.traffic_light_stopline_near_m
    )
    relevant_lights = [light for light in path_lights if light.get("path_compatible")]
    topology_support = bool(topology.get("active") or line_evidence["count"])
    strong_motion_near_stopline = bool(stopline_near and (motion.get("stationary") or motion.get("stopping") or motion.get("accelerating")))
    trigger = bool(relevant_lights or stopline_near or strong_motion_near_stopline or (lead.get("exists") and stopline_near) or topology_support)
    reasons = []
    if relevant_lights:
        reasons.append("relevant_od_traffic_light")
    if stopline_near:
        reasons.append("associated_or_nearby_stopline")
    if strong_motion_near_stopline:
        reasons.append("ego_motion_near_stopline")
    if lead.get("exists") and stopline_near:
        reasons.append("lead_near_same_path_stopline")
    if topology.get("active"):
        reasons.append("derived_intersection_topology")
    if line_evidence["count"]:
        reasons.append("ld_intersection_true_lane_lines")
    return {
        "frame_index": frame.get("frame_index"),
        "time_since_start_s": frame.get("time_since_start_s"),
        "trigger": trigger,
        "recall_reasons": reasons,
        "traffic_lights": path_lights,
        "raw_traffic_light_count": len(raw_signal["objects"]),
        "stopline": stopline,
        "ego_motion": motion,
        "lead": lead,
        "topology": {
            **topology,
            "intersection_true_lane_line_ids": line_evidence["intersection_true_lane_line_ids"],
            "topology_missing": not bool(topology.get("active")) and line_evidence["count"] == 0,
        },
    }


def _traffic_light_selected_frames(window: list[dict[str, Any]], signals: list[dict[str, Any]], config: VlmPocConfig) -> list[int]:
    if not window:
        return []
    candidates: list[int] = [int(window[0]["frame_index"])]
    trigger_frames = [int(item["frame_index"]) for item in signals if item.get("trigger")]
    if trigger_frames:
        candidates.append(min(trigger_frames))
    stopline_frames = [
        (abs(float((item.get("stopline") or {}).get("distance_m"))), int(item["frame_index"]))
        for item in signals
        if finite((item.get("stopline") or {}).get("distance_m"))
    ]
    for threshold_m in (8.0, 2.0):
        threshold_frame = next(
            (
                int(item["frame_index"])
                for item in signals
                if finite((item.get("stopline") or {}).get("distance_m"))
                and abs(float((item.get("stopline") or {}).get("distance_m"))) <= threshold_m
            ),
            None,
        )
        if threshold_frame is not None:
            candidates.append(threshold_frame)
    if stopline_frames:
        candidates.append(min(stopline_frames)[1])
    motion_frames = [
        int(item["frame_index"])
        for item in signals
        if (item.get("ego_motion") or {}).get("stopping")
        or (item.get("ego_motion") or {}).get("stationary")
        or (item.get("ego_motion") or {}).get("accelerating")
    ]
    if motion_frames:
        candidates.append(motion_frames[0])
    lead_frames = [
        int(item["frame_index"])
        for item in signals
        if (item.get("lead") or {}).get("exists")
    ]
    if lead_frames:
        candidates.append(lead_frames[0])
    relevant_light_frames = [
        int(item["frame_index"])
        for item in signals
        if any(light.get("path_compatible") for light in item.get("traffic_lights", []))
    ]
    if relevant_light_frames:
        candidates.append(relevant_light_frames[0])
    if motion_frames:
        candidates.append(motion_frames[len(motion_frames) // 2])
    if trigger_frames:
        candidates.append(max(trigger_frames))
    candidates.append(int(window[-1]["frame_index"]))
    by_index = {int(frame["frame_index"]): frame for frame in window}
    selected = []
    for frame_index in candidates:
        if frame_index in by_index and frame_index not in selected:
            selected.append(frame_index)
    for frame in selected_window_frames(window, 0, len(window) - 1, config):
        frame_index = int(frame["frame_index"])
        if frame_index not in selected:
            selected.append(frame_index)
        if len(selected) >= config.max_bev_images:
            break
    return sorted(selected[: config.max_bev_images])


def _compact_traffic_light_signal_frame(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "frame_index": item.get("frame_index"),
        "time_since_start_s": item.get("time_since_start_s"),
        "recall_reasons": item.get("recall_reasons", []),
        "traffic_lights": [
            light
            for light in item.get("traffic_lights", [])
            if light.get("path_compatible")
        ][:6],
        "raw_traffic_light_count": item.get("raw_traffic_light_count"),
        "stopline": item.get("stopline"),
        "ego_motion": item.get("ego_motion"),
        "lead": item.get("lead"),
        "topology": item.get("topology"),
    }


def _traffic_light_evidence_frames(
    signals: list[dict[str, Any]],
    selected_frame_indices: list[int],
    config: VlmPocConfig,
) -> list[dict[str, Any]]:
    selected = set(selected_frame_indices)
    previous_stopline_relation = None
    previous_lead_exists = None
    previous_motion_state = None
    chosen: list[int] = []
    for index, item in enumerate(signals):
        frame_index = int(item["frame_index"])
        motion = item.get("ego_motion") or {}
        motion_state_value = (
            "stopping" if motion.get("stopping") else
            "stationary" if motion.get("stationary") else
            "accelerating" if motion.get("accelerating") else
            motion.get("temporal_state")
        )
        stopline_relation = (item.get("stopline") or {}).get("relation")
        lead_exists = bool((item.get("lead") or {}).get("exists"))
        has_relevant_light = any(light.get("path_compatible") for light in item.get("traffic_lights", []))
        near_stopline = False
        distance = (item.get("stopline") or {}).get("distance_m")
        if finite(distance):
            near_stopline = abs(float(distance)) <= 8.0
        state_changed = (
            stopline_relation != previous_stopline_relation
            or lead_exists != previous_lead_exists
            or motion_state_value != previous_motion_state
        )
        if frame_index in selected or has_relevant_light or near_stopline and state_changed:
            chosen.append(index)
        previous_stopline_relation = stopline_relation
        previous_lead_exists = lead_exists
        previous_motion_state = motion_state_value

    if len(chosen) > max(12, config.max_bev_images * 3):
        budget = max(12, config.max_bev_images * 3)
        anchors = sorted({0, len(chosen) - 1, *[i for i, idx in enumerate(chosen) if int(signals[idx]["frame_index"]) in selected]})
        keep_positions = set(anchors)
        if len(keep_positions) < budget:
            stride = max(1, len(chosen) // budget)
            keep_positions.update(range(0, len(chosen), stride))
        chosen = [chosen[pos] for pos in sorted(keep_positions)[:budget]]
    return [_compact_traffic_light_signal_frame(signals[index]) for index in chosen]


def generate_traffic_light_episode_candidates(recording: dict[str, Any], config: VlmPocConfig) -> list[CandidateWindow]:
    frames = recording.get("frames", [])
    recording_id = str(recording.get("recording_id") or "unknown")
    if not frames:
        return []
    phase1_by_frame = _phase1_traffic_light_context_by_frame(recording)
    signal_frames = []
    for frame in frames:
        frame_index = frame.get("frame_index")
        if "traffic_light_context" in frame or not isinstance(frame_index, int) or frame_index not in phase1_by_frame:
            signal_frames.append(frame)
        else:
            signal_frames.append({**frame, "traffic_light_context": phase1_by_frame[frame_index]})
    signals = [_traffic_light_frame_signal(frame, recording, config) for frame in signal_frames]
    episodes: list[tuple[int, int]] = []
    current_start: int | None = None
    current_end: int | None = None
    last_trigger_t: float | None = None
    for pos, (frame, signal) in enumerate(zip(frames, signals)):
        if not signal["trigger"]:
            continue
        timestamp = float(frame.get("time_since_start_s") or 0.0)
        if current_start is None:
            current_start = pos
            current_end = pos
            last_trigger_t = timestamp
            continue
        if last_trigger_t is not None and timestamp - last_trigger_t <= config.traffic_light_episode_merge_gap_s:
            current_end = pos
            last_trigger_t = timestamp
        else:
            episodes.append((current_start, current_end or current_start))
            current_start = pos
            current_end = pos
            last_trigger_t = timestamp
    if current_start is not None:
        episodes.append((current_start, current_end or current_start))

    results = []
    for start_pos, end_pos in episodes:
        window = frames[start_pos : end_pos + 1]
        window_signals = signals[start_pos : end_pos + 1]
        start_frame = int(window[0]["frame_index"])
        end_frame = int(window[-1]["frame_index"])
        signal_frame_count = sum(1 for item in window_signals if item.get("trigger"))
        if signal_frame_count < config.traffic_light_episode_min_signal_frames:
            continue
        cid = _candidate_id(recording_id, "traffic_light_episode", start_frame, end_frame)
        recall_reasons = sorted({reason for item in window_signals for reason in item.get("recall_reasons", [])})
        stopline_distances = [
            float((item.get("stopline") or {}).get("distance_m"))
            for item in window_signals
            if finite((item.get("stopline") or {}).get("distance_m"))
        ]
        headings = [ego_heading(frame) for frame in window]
        heading_change = None
        if len(headings) >= 2 and all(finite(value) for value in headings):
            heading_change = _angle_delta(headings[0], headings[-1])
        selected_frame_indices = _traffic_light_selected_frames(window, window_signals, config)
        compact_signal_frames = _traffic_light_evidence_frames(
            window_signals,
            selected_frame_indices,
            config,
        )
        evidence = [
            EvidenceItem(
                f"{cid}:ego_motion",
                "ego_motion",
                "Structured ego speed, acceleration, and motion state across the traffic-light episode candidate.",
                {
                    "frames": [
                        frame_summary(frame)
                        for frame in window
                        if int(frame.get("frame_index")) in set(selected_frame_indices)
                    ],
                    "source_frame_count": len(window),
                },
            ),
            EvidenceItem(
                f"{cid}:traffic_light_context",
                "traffic_light_context",
                "High-recall traffic-light context frames; topology is supporting evidence and may be missing.",
                {
                    "frames": compact_signal_frames,
                    "source_frame_count": len(window_signals),
                    "output_labels": list(TRAFFIC_LIGHT_LABELS),
                },
            ),
            EvidenceItem(
                f"{cid}:stopline_progression",
                "stopline_progression",
                "Stopline distance/relation progression for before/on/passed validation.",
                {
                    "start_distance_m": round(stopline_distances[0], 3) if stopline_distances else None,
                    "minimum_abs_distance_m": round(min(abs(value) for value in stopline_distances), 3) if stopline_distances else None,
                    "end_distance_m": round(stopline_distances[-1], 3) if stopline_distances else None,
                    "relations": [
                        {
                            "frame_index": item["frame_index"],
                            "id": (item.get("stopline") or {}).get("id"),
                            "distance_m": (item.get("stopline") or {}).get("distance_m"),
                            "relation": (item.get("stopline") or {}).get("relation"),
                        }
                        for item in compact_signal_frames
                        if (item.get("stopline") or {}).get("id")
                    ],
                    "source_frame_count": len(window_signals),
                },
            ),
            EvidenceItem(
                f"{cid}:trajectory_progression",
                "trajectory_progression",
                "Trajectory heading and progression evidence for approach, traversal, and exit states.",
                {
                    "heading_change_rad": round(heading_change, 3) if heading_change is not None else None,
                    "start_frame": start_frame,
                    "end_frame": end_frame,
                    "topology_missing_frame_count": sum(
                        1 for item in window_signals if (item.get("topology") or {}).get("topology_missing")
                    ),
                    "derived_topology_frame_count": sum(
                        1 for item in window_signals if (item.get("topology") or {}).get("active")
                    ),
                    "intersection_true_lane_line_frame_count": sum(
                        1 for item in window_signals if (item.get("topology") or {}).get("intersection_true_lane_line_ids")
                    ),
                },
            ),
        ]
        results.append(
            CandidateWindow(
                candidate_id=cid,
                recording_id=recording_id,
                scenario="traffic_light_episode",
                start_frame=start_frame,
                end_frame=end_frame,
                start_timestamp_s=float(window[0].get("time_since_start_s") or 0.0),
                end_timestamp_s=float(window[-1].get("time_since_start_s") or 0.0),
                evidence=evidence,
                selected_frame_indices=selected_frame_indices,
                primary_object_ids=sorted(
                    {
                        str(light.get("object_id"))
                        for item in window_signals
                        for light in item.get("traffic_lights", [])
                        if light.get("object_id") and light.get("path_compatible")
                    }
                ),
                recall_reasons=recall_reasons,
                metadata={
                    "dedupe_key": "traffic_light_episode",
                    "output_labels": list(TRAFFIC_LIGHT_LABELS),
                    "topology_optional": True,
                },
            )
        )
    return results


def _candidate_score(candidate: CandidateWindow) -> float:
    score = 0.0
    for item in candidate.evidence:
        data = item.data
        if item.kind == "ego_heading_change":
            score += float(data.get("absolute_net_heading_change_rad") or 0.0)
            score += 0.5 * float(data.get("cumulative_heading_change_rad") or 0.0)
        elif item.kind == "traffic_light_evidence":
            for frame in data.get("frames", []):
                score += len(frame.get("objects") or []) + len(frame.get("ld_features") or [])
        elif item.kind == "traffic_light_context":
            for frame in data.get("frames", []):
                score += 2.0 if frame.get("trigger") else 0.0
                score += len(frame.get("recall_reasons") or [])
                score += len([light for light in frame.get("traffic_lights", []) if light.get("path_compatible")])
                score += 1.0 if (frame.get("stopline") or {}).get("id") else 0.0
        elif item.kind == "candidate_intersection_footprint":
            for frame in data.get("frames", []):
                score += float(frame.get("external_corridor_count") or 0)
                score += 1.0 if frame.get("active") else 0.0
        elif item.kind == "intersection_true_lane_lines":
            score += len(data.get("unique_lane_line_ids") or [])
            score += sum(float(frame.get("count") or 0) for frame in data.get("frames", []))
    return score


def dedupe_overlapping_candidates(candidates: list[CandidateWindow], config: VlmPocConfig) -> list[CandidateWindow]:
    if not candidates:
        return []
    ordered = sorted(candidates, key=lambda item: (item.recording_id, item.scenario, item.start_frame, item.end_frame))
    groups: list[list[CandidateWindow]] = []
    for candidate in ordered:
        if not groups:
            groups.append([candidate])
            continue
        group = groups[-1]
        last = group[-1]
        gap_s = candidate.start_timestamp_s - last.end_timestamp_s
        frame_overlap = min(candidate.end_frame, last.end_frame) - max(candidate.start_frame, last.start_frame) + 1
        min_len = max(1, min(candidate.end_frame - candidate.start_frame + 1, last.end_frame - last.start_frame + 1))
        overlap_ratio = max(0, frame_overlap) / min_len
        same_key = candidate.metadata.get("dedupe_key") == last.metadata.get("dedupe_key")
        if same_key and (gap_s <= config.maximum_inactive_gap_s or overlap_ratio >= config.overlap_threshold):
            group.append(candidate)
        else:
            groups.append([candidate])
    return [max(group, key=_candidate_score) for group in groups]


SCENARIO_REGISTRY: dict[str, ScenarioSpec] = {
    "waiting_for_pedestrian_to_cross": ScenarioSpec(
        "waiting_for_pedestrian_to_cross",
        generate_waiting_candidates,
    ),
    "on_intersection": ScenarioSpec("on_intersection", generate_intersection_candidates),
    "starting_u_turn": ScenarioSpec(
        "starting_u_turn",
        generate_starting_u_turn_candidates,
        dedupe=True,
    ),
    "traffic_light_episode": ScenarioSpec(
        "traffic_light_episode",
        generate_traffic_light_episode_candidates,
        dedupe=True,
    ),
}
