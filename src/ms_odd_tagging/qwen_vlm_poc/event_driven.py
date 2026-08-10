"""Additive event-driven candidate generation for the Qwen VLM POC.

The current fixed-window candidate generators remain untouched.  This module is
only used when the CLI explicitly requests the ``event-driven`` strategy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .candidates import (
    _ego_response,
    _pedestrian_motion_summary,
    _pedestrian_objects,
    pedestrian_corridor_conflict,
)
from .config import VlmPocConfig
from .evidence import frame_summary
from .geometry import ego_acceleration, ego_speed, finite, motion_state, object_id
from .models import CandidateWindow, EvidenceItem, ScenarioName


@dataclass(frozen=True)
class _ConflictSample:
    pos: int
    frame_index: int
    timestamp_s: float
    object_id: str
    conflict: dict[str, Any]


def generate_event_driven_candidates(
    recording: dict[str, Any],
    scenario: ScenarioName,
    config: VlmPocConfig,
) -> list[CandidateWindow]:
    """Generate candidates with event-derived boundaries where implemented.

    The experiment currently changes only ``waiting_for_pedestrian_to_cross``.
    Other scenarios deliberately fall back to the existing implementation so
    the strategy can be enabled safely while the experiment is expanded.
    """
    if scenario == "waiting_for_pedestrian_to_cross":
        return generate_waiting_event_candidates(recording, config)

    from .candidates import generate_candidates

    return generate_candidates(recording, scenario, config)


def _timestamp(frame: dict[str, Any]) -> float | None:
    value = frame.get("time_since_start_s")
    return float(value) if finite(value) else None


def _conflict_samples_by_pedestrian(
    frames: list[dict[str, Any]], config: VlmPocConfig
) -> dict[str, list[_ConflictSample]]:
    result: dict[str, list[_ConflictSample]] = {}
    for pos, frame in enumerate(frames):
        timestamp = _timestamp(frame)
        if timestamp is None or not isinstance(frame.get("frame_index"), int):
            continue
        for obj in _pedestrian_objects(frame):
            conflict = pedestrian_corridor_conflict(frame, obj, config)
            if not conflict.get("conflict"):
                continue
            ped_id = object_id(obj)
            if not ped_id:
                continue
            result.setdefault(ped_id, []).append(
                _ConflictSample(
                    pos=pos,
                    frame_index=int(frame["frame_index"]),
                    timestamp_s=timestamp,
                    object_id=ped_id,
                    conflict=conflict,
                )
            )
    return result


def _split_conflict_episodes(
    samples: list[_ConflictSample], max_gap_s: float
) -> list[list[_ConflictSample]]:
    if not samples:
        return []
    episodes: list[list[_ConflictSample]] = [[samples[0]]]
    for sample in samples[1:]:
        previous = episodes[-1][-1]
        if sample.timestamp_s - previous.timestamp_s <= max_gap_s + 1e-9:
            episodes[-1].append(sample)
        else:
            episodes.append([sample])
    return episodes


def _context_bounds(
    frames: list[dict[str, Any]],
    raw_start_pos: int,
    raw_end_pos: int,
    config: VlmPocConfig,
) -> tuple[int, int]:
    raw_start_t = _timestamp(frames[raw_start_pos]) or 0.0
    raw_end_t = _timestamp(frames[raw_end_pos]) or raw_start_t
    start_target = raw_start_t - config.event_candidate_pre_context_s
    end_target = raw_end_t + config.event_candidate_post_context_s

    start_pos = raw_start_pos
    while start_pos > 0:
        previous_t = _timestamp(frames[start_pos - 1])
        if previous_t is None or previous_t < start_target - 1e-9:
            break
        start_pos -= 1

    end_pos = raw_end_pos
    while end_pos + 1 < len(frames):
        next_t = _timestamp(frames[end_pos + 1])
        if next_t is None or next_t > end_target + 1e-9:
            break
        end_pos += 1
    return start_pos, end_pos


def _response_positions(
    frames: list[dict[str, Any]], start_pos: int, end_pos: int, config: VlmPocConfig
) -> list[int]:
    return [
        pos
        for pos in range(start_pos, end_pos + 1)
        if _ego_response(frames[pos], config)
    ]


def _response_is_temporally_linked(
    frames: list[dict[str, Any]],
    response_positions: list[int],
    raw_start_pos: int,
    raw_end_pos: int,
    config: VlmPocConfig,
) -> bool:
    if not response_positions:
        return False
    raw_start_t = _timestamp(frames[raw_start_pos])
    raw_end_t = _timestamp(frames[raw_end_pos])
    if raw_start_t is None or raw_end_t is None:
        return False
    for pos in response_positions:
        timestamp = _timestamp(frames[pos])
        if timestamp is None:
            continue
        if raw_start_t - config.event_response_link_s <= timestamp <= raw_end_t + config.event_response_link_s:
            return True
    return False


def _strongest_response_pos(
    frames: list[dict[str, Any]], response_positions: list[int]
) -> int | None:
    if not response_positions:
        return None

    def score(pos: int) -> tuple[float, float, float]:
        frame = frames[pos]
        state = motion_state(frame)
        state_score = {
            "stationary": 5.0,
            "stopping": 4.0,
            "decelerating": 3.0,
            "slow": 2.0,
        }.get(state, 1.0)
        speed = ego_speed(frame)
        accel = ego_acceleration(frame)
        low_speed_score = -float(speed) if finite(speed) else -math.inf
        decel_score = -float(accel) if finite(accel) else -math.inf
        return state_score, low_speed_score, decel_score

    return max(response_positions, key=score)


def _landmarks(
    frames: list[dict[str, Any]],
    context_start_pos: int,
    context_end_pos: int,
    episode: list[_ConflictSample],
    response_positions: list[int],
    config: VlmPocConfig,
) -> tuple[list[int], dict[str, int]]:
    raw_start_pos = episode[0].pos
    raw_end_pos = episode[-1].pos
    corridor_entry = next(
        (sample for sample in episode if sample.conflict.get("in_future_corridor")),
        None,
    )
    strongest = min(
        episode,
        key=lambda sample: float(sample.conflict.get("distance_m"))
        if finite(sample.conflict.get("distance_m"))
        else math.inf,
    )
    strongest_response = _strongest_response_pos(frames, response_positions)

    roles_by_pos: list[tuple[str, int | None]] = [
        ("pre_conflict", raw_start_pos - 1 if raw_start_pos > context_start_pos else context_start_pos),
        ("conflict_onset", raw_start_pos),
        ("corridor_entry", corridor_entry.pos if corridor_entry is not None else None),
        ("strongest_conflict", strongest.pos),
        ("strongest_ego_response", strongest_response),
        ("resolution", raw_end_pos + 1 if raw_end_pos < context_end_pos else context_end_pos),
    ]

    selected_positions: list[int] = []
    roles: dict[str, int] = {}
    for role, pos in roles_by_pos:
        if pos is None or not (context_start_pos <= pos <= context_end_pos):
            continue
        frame_index = int(frames[pos]["frame_index"])
        roles[role] = frame_index
        if pos not in selected_positions:
            selected_positions.append(pos)

    if len(selected_positions) > config.max_bev_images:
        priority = (
            "pre_conflict",
            "conflict_onset",
            "corridor_entry",
            "strongest_conflict",
            "strongest_ego_response",
            "resolution",
        )
        keep_indices: list[int] = []
        for role in priority:
            frame_index = roles.get(role)
            if frame_index is not None and frame_index not in keep_indices:
                keep_indices.append(frame_index)
            if len(keep_indices) >= config.max_bev_images:
                break
        return sorted(keep_indices), roles

    return sorted(int(frames[pos]["frame_index"]) for pos in selected_positions), roles


def generate_waiting_event_candidates(
    recording: dict[str, Any], config: VlmPocConfig
) -> list[CandidateWindow]:
    """Build continuous pedestrian-conflict episodes instead of sliding windows."""
    frames = recording.get("frames", [])
    recording_id = str(recording.get("recording_id") or "unknown")
    if not frames:
        return []

    results: list[CandidateWindow] = []
    by_pedestrian = _conflict_samples_by_pedestrian(frames, config)
    for pedestrian_id, samples in sorted(by_pedestrian.items()):
        episodes = _split_conflict_episodes(samples, config.maximum_inactive_gap_s)
        for episode in episodes:
            raw_start_pos = episode[0].pos
            raw_end_pos = episode[-1].pos
            raw_duration_s = episode[-1].timestamp_s - episode[0].timestamp_s
            if raw_duration_s + 1e-9 < config.minimum_duration_s:
                continue

            context_start_pos, context_end_pos = _context_bounds(
                frames, raw_start_pos, raw_end_pos, config
            )
            responses = _response_positions(
                frames, context_start_pos, context_end_pos, config
            )
            if not _response_is_temporally_linked(
                frames, responses, raw_start_pos, raw_end_pos, config
            ):
                continue

            context = frames[context_start_pos : context_end_pos + 1]
            track = [
                {
                    "frame_index": sample.frame_index,
                    "object_id": sample.object_id,
                    "conflict": sample.conflict,
                }
                for sample in episode
            ]
            motion = _pedestrian_motion_summary(context, pedestrian_id, track)
            selected_indices, landmark_roles = _landmarks(
                frames,
                context_start_pos,
                context_end_pos,
                episode,
                responses,
                config,
            )

            start_frame = int(frames[context_start_pos]["frame_index"])
            end_frame = int(frames[context_end_pos]["frame_index"])
            cid = (
                f"{recording_id}_waiting_for_pedestrian_to_cross_"
                f"{start_frame:06d}_{end_frame:06d}"
            )
            response_frame_indices = [int(frames[pos]["frame_index"]) for pos in responses]
            evidence = [
                EvidenceItem(
                    f"{cid}:ego_motion",
                    "ego_motion",
                    "Ego motion across automatically expanded event context.",
                    {"frames": [frame_summary(frame) for frame in context]},
                ),
                EvidenceItem(
                    f"{cid}:future_corridor",
                    "ego_future_corridor",
                    "Deterministic ego-aligned future corridor used for high-recall candidate generation.",
                    {
                        "longitudinal_range_m": [
                            -config.pedestrian_behind_m,
                            config.pedestrian_forward_m,
                        ],
                        "lateral_abs_m": config.pedestrian_corridor_lateral_m,
                    },
                ),
                EvidenceItem(
                    f"{cid}:pedestrian_conflicts",
                    "pedestrian_corridor_conflict",
                    "One pedestrian conflict episode with derived motion and ego response.",
                    {
                        "tracks": {pedestrian_id: track},
                        "motion": {pedestrian_id: motion},
                        "ego_response_frames": response_frame_indices,
                    },
                ),
                EvidenceItem(
                    f"{cid}:event_landmarks",
                    "event_landmarks",
                    "Machine-selected temporal landmarks; no manual metadata is used.",
                    {
                        "roles": landmark_roles,
                        "raw_trigger_start_frame": episode[0].frame_index,
                        "raw_trigger_end_frame": episode[-1].frame_index,
                        "candidate_context_start_frame": start_frame,
                        "candidate_context_end_frame": end_frame,
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
                    start_timestamp_s=float(_timestamp(frames[context_start_pos]) or 0.0),
                    end_timestamp_s=float(_timestamp(frames[context_end_pos]) or 0.0),
                    evidence=evidence,
                    selected_frame_indices=selected_indices,
                    primary_object_ids=[pedestrian_id],
                    recall_reasons=[
                        "event_driven_pedestrian_corridor_conflict",
                        "temporally_linked_ego_response",
                    ],
                    metadata={
                        "candidate_strategy": "event-driven",
                        "raw_trigger_start_frame": episode[0].frame_index,
                        "raw_trigger_end_frame": episode[-1].frame_index,
                        "landmark_roles": landmark_roles,
                    },
                )
            )

    results.sort(key=lambda item: (item.start_timestamp_s, item.end_timestamp_s, item.candidate_id))
    return results
