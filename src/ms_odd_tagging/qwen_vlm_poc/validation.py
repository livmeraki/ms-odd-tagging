"""Strict VLM response parsing and validation."""

from __future__ import annotations

import json
from typing import Any

from .config import VlmPocConfig
from .models import CandidateWindow, ValidationResult, VlmDecision


REQUIRED_KEYS = {
    "recording_id",
    "window_start_frame",
    "window_end_frame",
    "scenario",
    "decision",
    "confidence",
    "event_start_frame",
    "event_end_frame",
    "primary_object_ids",
    "evidence_ids",
    "reason",
    "ambiguities",
    "insufficient_evidence",
    "review_required",
}


def _json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        raise ValueError("markdown fenced response is not JSON-only")
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("response JSON must be an object")
    return parsed


def parse_and_validate_response(
    raw_text: str,
    candidate: CandidateWindow,
    config: VlmPocConfig,
) -> ValidationResult:
    reasons: list[str] = []
    try:
        data = _json_object(raw_text)
    except Exception as exc:
        return ValidationResult(False, True, [f"malformed_json:{exc}"], raw_text=raw_text)

    missing = sorted(REQUIRED_KEYS - set(data))
    if missing:
        reasons.append("missing_keys:" + ",".join(missing))
    extra = sorted(set(data) - REQUIRED_KEYS)
    if extra:
        reasons.append("extra_keys:" + ",".join(extra))
    if data.get("recording_id") != candidate.recording_id:
        reasons.append("wrong_recording_id")
    if data.get("scenario") != candidate.scenario:
        reasons.append("wrong_scenario")
    if data.get("window_start_frame") != candidate.start_frame or data.get("window_end_frame") != candidate.end_frame:
        reasons.append("invalid_window_frame_range")

    decision = data.get("decision")
    if not isinstance(decision, bool):
        reasons.append("decision_not_boolean")
    confidence = data.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0.0 <= float(confidence) <= 1.0:
        reasons.append("invalid_confidence")
        confidence = 0.0

    event_start = data.get("event_start_frame")
    event_end = data.get("event_end_frame")
    if decision is True:
        if not isinstance(event_start, int) or not isinstance(event_end, int):
            reasons.append("positive_missing_event_frame_range")
        elif event_start < candidate.start_frame or event_end > candidate.end_frame or event_start > event_end:
            reasons.append("invalid_event_frame_range")
    elif event_start is not None or event_end is not None:
        reasons.append("negative_has_event_frame_range")

    evidence_ids = data.get("evidence_ids")
    if not isinstance(evidence_ids, list) or not all(isinstance(value, str) for value in evidence_ids):
        reasons.append("invalid_evidence_ids")
        evidence_ids = []
    else:
        unknown = sorted(set(evidence_ids) - candidate.evidence_ids())
        if unknown:
            reasons.append("nonexistent_evidence_ids:" + ",".join(unknown))

    primary_object_ids = data.get("primary_object_ids")
    if not isinstance(primary_object_ids, list) or not all(isinstance(value, str) for value in primary_object_ids):
        reasons.append("invalid_primary_object_ids")
        primary_object_ids = []
    if candidate.scenario == "waiting_for_pedestrian_to_cross" and decision is True and not primary_object_ids:
        reasons.append("missing_pedestrian_ids")
    if candidate.scenario == "waiting_for_pedestrian_to_cross" and decision is True:
        unknown_objects = sorted(set(primary_object_ids) - set(candidate.primary_object_ids))
        if unknown_objects:
            reasons.append("unknown_primary_object_ids:" + ",".join(unknown_objects))

    ambiguities = data.get("ambiguities")
    if not isinstance(ambiguities, list) or not all(isinstance(value, str) for value in ambiguities):
        reasons.append("invalid_ambiguities")
        ambiguities = []
    insufficient = data.get("insufficient_evidence")
    review_required = data.get("review_required")
    if not isinstance(insufficient, bool):
        reasons.append("invalid_insufficient_evidence_flag")
        insufficient = True
    if not isinstance(review_required, bool):
        reasons.append("invalid_review_required_flag")
        review_required = True
    reason_text = data.get("reason")
    if not isinstance(reason_text, str) or not reason_text.strip():
        reasons.append("missing_reason")
        reason_text = ""
    if decision is True and insufficient is True:
        reasons.append("positive_marked_insufficient_evidence")
    if decision is True and not evidence_ids:
        reasons.append("positive_missing_evidence_ids")
    reason_lower = reason_text.lower()
    if decision is False and candidate.scenario == "on_intersection" and any(
        phrase in reason_lower
        for phrase in (
            "inside the effective intersection",
            "confirms the presence of intersecting",
            "indicate an intersection",
            "confirms it is within an intersection",
        )
    ):
        reasons.append("inconsistent_negative_reason")
    if (
        decision is False
        and candidate.scenario == "waiting_for_pedestrian_to_cross"
        and any(
            phrase in reason_lower
            for phrase in (
                "indicating a conflict and intent to yield",
            )
        )
    ):
        reasons.append("inconsistent_negative_reason")

    review = bool(review_required or reasons or insufficient)
    accepted = (
        not reasons
        and decision is True
        and not insufficient
        and float(confidence) >= config.acceptance_threshold
    )
    if decision is True and not accepted and float(confidence) >= config.review_threshold:
        review = True

    parsed_decision = VlmDecision(
        recording_id=str(data.get("recording_id")),
        window_start_frame=int(data.get("window_start_frame") or candidate.start_frame),
        window_end_frame=int(data.get("window_end_frame") or candidate.end_frame),
        scenario=str(data.get("scenario")),
        decision=bool(decision) if isinstance(decision, bool) else False,
        confidence=float(confidence),
        event_start_frame=event_start if isinstance(event_start, int) else None,
        event_end_frame=event_end if isinstance(event_end, int) else None,
        primary_object_ids=list(primary_object_ids),
        evidence_ids=list(evidence_ids),
        reason=reason_text,
        ambiguities=list(ambiguities),
        insufficient_evidence=bool(insufficient),
        review_required=review,
    )
    return ValidationResult(
        accepted=accepted,
        review_required=review,
        reasons=reasons,
        decision=parsed_decision,
        raw_text=raw_text,
    )
