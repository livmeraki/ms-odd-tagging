"""Temporal merging of accepted VLM candidate windows."""

from __future__ import annotations

from typing import Any

from ms_odd_tagging.tagger.rule_based.scenario_event import ScenarioEvent

from .config import VlmPocConfig
from .models import CandidateWindow, VlmDecision


def _frame_times(recording: dict[str, Any]) -> dict[int, float]:
    return {
        int(frame["frame_index"]): float(frame.get("time_since_start_s") or 0.0)
        for frame in recording.get("frames", [])
        if isinstance(frame.get("frame_index"), int)
    }


def _overlap_ratio(a: tuple[int, int], b: tuple[int, int]) -> float:
    start = max(a[0], b[0])
    end = min(a[1], b[1])
    if end < start:
        return 0.0
    intersection = end - start + 1
    union = max(a[1], b[1]) - min(a[0], b[0]) + 1
    return intersection / union if union > 0 else 0.0


def merge_decisions(
    recording: dict[str, Any],
    accepted: list[tuple[CandidateWindow, VlmDecision]],
    config: VlmPocConfig,
) -> list[ScenarioEvent]:
    if not accepted:
        return []
    times = _frame_times(recording)
    rows = sorted(
        accepted,
        key=lambda item: (
            item[1].event_start_frame if item[1].event_start_frame is not None else item[0].start_frame,
            item[0].scenario,
        ),
    )
    merged: list[dict[str, Any]] = []
    for candidate, decision in rows:
        start = decision.event_start_frame if decision.event_start_frame is not None else candidate.start_frame
        end = decision.event_end_frame if decision.event_end_frame is not None else candidate.end_frame
        start_t = times.get(start, candidate.start_timestamp_s)
        end_t = times.get(end, candidate.end_timestamp_s)
        ped_key = tuple(sorted(decision.primary_object_ids)) if candidate.scenario == "waiting_for_pedestrian_to_cross" else ()
        current = {
            "scenario": candidate.scenario,
            "start": start,
            "end": end,
            "start_t": start_t,
            "end_t": end_t,
            "confidence": decision.confidence,
            "primary_object_ids": set(decision.primary_object_ids),
            "evidence_ids": set(decision.evidence_ids),
            "candidate_ids": [candidate.candidate_id],
            "reasons": [decision.reason],
            "ped_key": ped_key,
        }
        previous = merged[-1] if merged else None
        gap = (start_t - previous["end_t"]) if previous else None
        same_track = (
            previous is not None
            and previous["scenario"] == current["scenario"]
            and (
                current["scenario"] != "waiting_for_pedestrian_to_cross"
                or not previous["ped_key"]
                or not current["ped_key"]
                or bool(set(previous["ped_key"]) & set(current["ped_key"]))
            )
        )
        overlaps = previous is not None and _overlap_ratio((previous["start"], previous["end"]), (start, end)) >= config.overlap_threshold
        close = gap is not None and gap <= config.maximum_inactive_gap_s + config.boundary_hysteresis_s
        if previous is not None and same_track and (overlaps or close):
            previous["end"] = max(previous["end"], end)
            previous["end_t"] = max(previous["end_t"], end_t)
            previous["confidence"] = max(previous["confidence"], current["confidence"])
            previous["primary_object_ids"].update(current["primary_object_ids"])
            previous["evidence_ids"].update(current["evidence_ids"])
            previous["candidate_ids"].extend(current["candidate_ids"])
            previous["reasons"].extend(current["reasons"])
            previous["ped_key"] = tuple(sorted(previous["primary_object_ids"]))
        else:
            merged.append(current)

    events = []
    for item in merged:
        duration = max(0.0, item["end_t"] - item["start_t"])
        if duration + 1e-9 < config.minimum_duration_s:
            continue
        events.append(
            ScenarioEvent(
                scenario=item["scenario"],
                start_frame=int(item["start"]),
                end_frame=int(item["end"]),
                start_timestamp_s=float(item["start_t"]),
                end_timestamp_s=float(item["end_t"]),
                duration_s=round(duration, 6),
                confidence=round(float(item["confidence"]), 6),
                source="qwen_vlm_poc",
                detector_version="qwen-vlm-poc-v1",
                evidence={
                    "candidate_ids": item["candidate_ids"],
                    "evidence_ids": sorted(item["evidence_ids"]),
                    "primary_object_ids": sorted(item["primary_object_ids"]),
                    "merge_policy": {
                        "maximum_inactive_gap_s": config.maximum_inactive_gap_s,
                        "overlap_threshold": config.overlap_threshold,
                        "boundary_hysteresis_s": config.boundary_hysteresis_s,
                    },
                    "reasons": item["reasons"][:5],
                },
            )
        )
    return events

