"""Deterministic recall-oriented candidate generation for the VLM POC."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from .config import VlmPocConfig
from .evidence import frame_summary, selected_window_frames
from .geometry import (
    ego_acceleration,
    ego_speed,
    finite,
    motion_state,
    normalized_class,
    object_ego_xy,
    object_id,
)
from .models import CandidateWindow, EvidenceItem, ScenarioName


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
    if isinstance(velocity, (list, tuple)) and len(velocity) >= 2 and finite(velocity[1]):
        lateral_speed = float(velocity[1])
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


def generate_candidates(
    recording: dict[str, Any],
    scenario: ScenarioName,
    config: VlmPocConfig,
) -> list[CandidateWindow]:
    if scenario == "waiting_for_pedestrian_to_cross":
        return generate_waiting_candidates(recording, config)
    if scenario == "on_intersection":
        return generate_intersection_candidates(recording, config)
    raise ValueError(f"unsupported scenario: {scenario}")


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
        selected = selected_window_frames(frames, start_pos, end_pos, config)
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
                {"tracks": dict(ped_tracks), "ego_response_frames": response_frames},
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
                selected_frame_indices=[int(frame["frame_index"]) for frame in selected],
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
        if not any(item["active"] or item["road_feature_support"] for item in signals):
            continue
        selected = selected_window_frames(frames, start_pos, end_pos, config)
        start_frame = int(window[0]["frame_index"])
        end_frame = int(window[-1]["frame_index"])
        cid = _candidate_id(recording_id, "on_intersection", start_frame, end_frame)
        lane_counts = [item["lane_line_count"] for item in signals]
        evidence = [
            EvidenceItem(
                f"{cid}:ego_motion",
                "ego_motion",
                "Ego pose, heading, and speed across the candidate window.",
                {"frames": [frame_summary(frame) for frame in window]},
            ),
            EvidenceItem(
                f"{cid}:intersection_topology",
                "candidate_intersection_footprint",
                "Existing topology and candidate footprint evidence for recall only.",
                {"frames": signals},
            ),
            EvidenceItem(
                f"{cid}:connected_roads",
                "connected_road_evidence",
                "External corridor, roadmark, and lane/boundary count changes.",
                {
                    "max_external_corridor_count": max(
                        [item["external_corridor_count"] or 0 for item in signals],
                        default=0,
                    ),
                    "max_roadmark_count": max([item["roadmark_count"] for item in signals], default=0),
                    "lane_line_count_min": min(lane_counts) if lane_counts else 0,
                    "lane_line_count_max": max(lane_counts) if lane_counts else 0,
                    "lane_boundary_count_changes": (max(lane_counts) - min(lane_counts)) if lane_counts else 0,
                },
            ),
        ]
        reasons = []
        if any(item["active"] for item in signals):
            reasons.append("topology_or_connected_corridors")
        if any(item["road_feature_support"] for item in signals):
            reasons.append("crosswalk_or_stopline_roadmark")
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
                selected_frame_indices=[int(frame["frame_index"]) for frame in selected],
                recall_reasons=reasons or ["weak_intersection_support"],
            )
        )
    return results

