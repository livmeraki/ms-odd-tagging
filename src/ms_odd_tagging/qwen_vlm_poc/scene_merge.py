"""Scene-level deduplication for event-driven VLM candidates."""

from __future__ import annotations

from typing import Any

from .config import VlmPocConfig
from .models import CandidateWindow


def _frame_times(recording: dict[str, Any]) -> dict[int, float]:
    return {
        int(frame["frame_index"]): float(frame.get("time_since_start_s") or 0.0)
        for frame in recording.get("frames", [])
        if isinstance(frame.get("frame_index"), int)
    }


def _raw_bounds(candidate: CandidateWindow) -> tuple[int, int]:
    metadata = candidate.metadata or {}
    return (
        int(metadata.get("raw_trigger_start_frame", candidate.start_frame)),
        int(metadata.get("raw_trigger_end_frame", candidate.end_frame)),
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


def merge_waiting_scene_candidates(
    recording: dict[str, Any],
    candidates: list[CandidateWindow],
    config: VlmPocConfig,
) -> list[CandidateWindow]:
    """Merge overlapping pedestrian-specific candidates into scene-level requests.

    Clustering uses raw trigger intervals rather than expanded context windows so
    pre/post context does not create artificial overlap. A short temporal gap is
    allowed so multiple pedestrians participating in one physical scene share one
    VLM request. The VLM-facing candidate deliberately drops heuristic evidence;
    only neutral scene metadata and BEV frames remain.
    """
    if not candidates:
        return []

    times = _frame_times(recording)
    ordered = sorted(candidates, key=lambda item: (_raw_bounds(item)[0], _raw_bounds(item)[1]))
    clusters: list[list[CandidateWindow]] = []

    for candidate in ordered:
        raw_start, raw_end = _raw_bounds(candidate)
        start_t = times.get(raw_start, candidate.start_timestamp_s)
        end_t = times.get(raw_end, candidate.end_timestamp_s)
        if not clusters:
            clusters.append([candidate])
            continue

        previous = clusters[-1]
        previous_end_frame = max(_raw_bounds(item)[1] for item in previous)
        previous_end_t = max(
            times.get(_raw_bounds(item)[1], item.end_timestamp_s)
            for item in previous
        )
        if start_t <= previous_end_t + config.maximum_inactive_gap_s + 1e-9:
            previous.append(candidate)
        else:
            clusters.append([candidate])

    frames = [
        int(frame["frame_index"])
        for frame in recording.get("frames", [])
        if isinstance(frame.get("frame_index"), int)
    ]
    results: list[CandidateWindow] = []
    recording_id = str(recording.get("recording_id") or candidates[0].recording_id)

    for cluster in clusters:
        context_start = min(item.start_frame for item in cluster)
        context_end = max(item.end_frame for item in cluster)
        raw_start = min(_raw_bounds(item)[0] for item in cluster)
        raw_end = max(_raw_bounds(item)[1] for item in cluster)
        pedestrian_ids = sorted({pid for item in cluster for pid in item.primary_object_ids})
        source_ids = [item.candidate_id for item in cluster]

        available = [index for index in frames if context_start <= index <= context_end]
        selected = _uniform_indices(available, config.max_bev_images)
        start_t = times.get(context_start, min(item.start_timestamp_s for item in cluster))
        end_t = times.get(context_end, max(item.end_timestamp_s for item in cluster))
        candidate_id = (
            f"{recording_id}_waiting_for_pedestrian_to_cross_scene_"
            f"{context_start:06d}_{context_end:06d}"
        )

        results.append(
            CandidateWindow(
                candidate_id=candidate_id,
                recording_id=recording_id,
                scenario="waiting_for_pedestrian_to_cross",
                start_frame=context_start,
                end_frame=context_end,
                start_timestamp_s=float(start_t),
                end_timestamp_s=float(end_t),
                evidence=[],
                selected_frame_indices=selected,
                primary_object_ids=pedestrian_ids,
                recall_reasons=["scene_level_event_candidate"],
                metadata={
                    "candidate_strategy": "event-driven",
                    "vlm_input_mode": "bev_only",
                    "scene_merged": True,
                    "raw_trigger_start_frame": raw_start,
                    "raw_trigger_end_frame": raw_end,
                    "pedestrian_ids": pedestrian_ids,
                    "source_candidate_ids": source_ids,
                    "source_candidate_count": len(cluster),
                },
            )
        )

    return results
