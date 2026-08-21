"""Strict VLM response parsing and validation."""

from __future__ import annotations

import json
from typing import Any

from .config import TRAFFIC_LIGHT_LABELS, VlmPocConfig
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


def _on_intersection_negative_reason_is_contradictory(reason_lower: str) -> bool:
    negated_inside_phrases = (
        "not inside the effective intersection",
        "not spatially inside the effective intersection",
        "not being inside the effective intersection",
        "not inside the intersection",
        "not being inside the intersection",
        "not inside an intersection",
        "not within the effective intersection",
        "not within the intersection",
        "no longer inside the effective intersection",
        "no longer within the effective intersection",
        "outside the effective intersection",
        "outside the intersection footprint",
    )
    if any(phrase in reason_lower for phrase in negated_inside_phrases):
        return False
    return any(
        phrase in reason_lower
        for phrase in (
            "inside the effective intersection",
            "spatially inside the effective intersection",
            "confirms the presence of intersecting",
            "indicate an intersection",
            "confirms it is within an intersection",
        )
    )


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
    if candidate.scenario == "traffic_light_episode":
        return _parse_traffic_light_episode_response(data, raw_text, candidate, config)

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
    if (
        decision is False
        and candidate.scenario == "on_intersection"
        and _on_intersection_negative_reason_is_contradictory(reason_lower)
    ):
        reasons.append("inconsistent_negative_reason")
    if (
        decision is False
        and candidate.scenario == "waiting_for_pedestrian_to_cross"
        and any(
            phrase in reason_lower
            for phrase in (
                "indicating a conflict and intent to yield",
                "stationary and not stopped",
                "stationary and not stopped or moving slowly",
                "stationary but not stopped",
                "stationary does not satisfy the stopped",
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
        decisions=[parsed_decision] if accepted else [],
        raw_text=raw_text,
    )


TRAFFIC_LIGHT_REQUIRED_KEYS = {
    "recording_id",
    "window_start_frame",
    "window_end_frame",
    "scenario",
    "traffic_light_context",
    "labels",
    "confidence_by_label",
    "event_frame_ranges",
    "reason_by_label",
    "evidence_ids_by_label",
    "ambiguities",
    "insufficient_evidence",
    "review_required",
}

MUTUALLY_EXCLUSIVE_LABELS = (
    ("accelerating_at_traffic_light_with_lead", "accelerating_at_traffic_light_without_lead"),
    ("stationary_at_traffic_light_with_lead", "stationary_at_traffic_light_without_lead"),
    ("stopping_at_traffic_light_with_lead", "stopping_at_traffic_light_without_lead"),
)


def _parse_traffic_light_episode_response(
    data: dict[str, Any],
    raw_text: str,
    candidate: CandidateWindow,
    config: VlmPocConfig,
) -> ValidationResult:
    reasons: list[str] = []
    missing = sorted(TRAFFIC_LIGHT_REQUIRED_KEYS - set(data))
    if missing:
        reasons.append("missing_keys:" + ",".join(missing))
    extra = sorted(set(data) - TRAFFIC_LIGHT_REQUIRED_KEYS)
    if extra:
        reasons.append("extra_keys:" + ",".join(extra))
    if data.get("recording_id") != candidate.recording_id:
        reasons.append("wrong_recording_id")
    if data.get("scenario") != "traffic_light_episode":
        reasons.append("wrong_scenario")
    if data.get("window_start_frame") != candidate.start_frame or data.get("window_end_frame") != candidate.end_frame:
        reasons.append("invalid_window_frame_range")
    if not isinstance(data.get("traffic_light_context"), bool):
        reasons.append("invalid_traffic_light_context")

    labels = data.get("labels")
    if not isinstance(labels, dict):
        reasons.append("invalid_labels")
        labels = {}
    missing_labels = sorted(set(TRAFFIC_LIGHT_LABELS) - set(labels))
    extra_labels = sorted(set(labels) - set(TRAFFIC_LIGHT_LABELS))
    if missing_labels:
        reasons.append("missing_labels:" + ",".join(missing_labels))
    if extra_labels:
        reasons.append("extra_labels:" + ",".join(extra_labels))
    for label in TRAFFIC_LIGHT_LABELS:
        if label in labels and not isinstance(labels[label], bool):
            reasons.append(f"label_not_boolean:{label}")

    for left, right in MUTUALLY_EXCLUSIVE_LABELS:
        if labels.get(left) is True and labels.get(right) is True:
            reasons.append(f"mutually_exclusive_labels:{left},{right}")

    confidence_by_label = data.get("confidence_by_label")
    if not isinstance(confidence_by_label, dict):
        reasons.append("invalid_confidence_by_label")
        confidence_by_label = {}
    event_ranges = data.get("event_frame_ranges")
    if not isinstance(event_ranges, dict):
        reasons.append("invalid_event_frame_ranges")
        event_ranges = {}
    reason_by_label = data.get("reason_by_label")
    if not isinstance(reason_by_label, dict):
        reasons.append("invalid_reason_by_label")
        reason_by_label = {}
    evidence_by_label = data.get("evidence_ids_by_label")
    if not isinstance(evidence_by_label, dict):
        reasons.append("invalid_evidence_ids_by_label")
        evidence_by_label = {}

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

    known_evidence_ids = candidate.evidence_ids()
    decisions: list[VlmDecision] = []
    for label in TRAFFIC_LIGHT_LABELS:
        if labels.get(label) is not True:
            continue
        confidence = confidence_by_label.get(label)
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0.0 <= float(confidence) <= 1.0:
            reasons.append(f"invalid_label_confidence:{label}")
            confidence = 0.0
        frame_range = event_ranges.get(label)
        if not isinstance(frame_range, dict):
            reasons.append(f"positive_missing_event_frame_range:{label}")
            event_start = None
            event_end = None
        else:
            event_start = frame_range.get("start_frame")
            event_end = frame_range.get("end_frame")
            if (
                not isinstance(event_start, int)
                or not isinstance(event_end, int)
                or event_start < candidate.start_frame
                or event_end > candidate.end_frame
                or event_start > event_end
            ):
                reasons.append(f"invalid_event_frame_range:{label}")
                event_start = None
                event_end = None
        evidence_ids = evidence_by_label.get(label)
        if not isinstance(evidence_ids, list) or not all(isinstance(value, str) for value in evidence_ids):
            reasons.append(f"invalid_evidence_ids:{label}")
            evidence_ids = []
        else:
            unknown = sorted(set(evidence_ids) - known_evidence_ids)
            if unknown:
                reasons.append(f"nonexistent_evidence_ids:{label}:" + ",".join(unknown))
        reason_text = reason_by_label.get(label)
        if not isinstance(reason_text, str) or not reason_text.strip():
            reasons.append(f"missing_reason:{label}")
            reason_text = ""
        if insufficient:
            reasons.append(f"positive_marked_insufficient_evidence:{label}")
        if not evidence_ids:
            reasons.append(f"positive_missing_evidence_ids:{label}")
        if float(confidence) >= config.acceptance_threshold:
            decisions.append(
                VlmDecision(
                    recording_id=candidate.recording_id,
                    window_start_frame=candidate.start_frame,
                    window_end_frame=candidate.end_frame,
                    scenario=label,
                    decision=True,
                    confidence=float(confidence),
                    event_start_frame=event_start,
                    event_end_frame=event_end,
                    primary_object_ids=[],
                    evidence_ids=list(evidence_ids),
                    reason=reason_text,
                    ambiguities=list(ambiguities),
                    insufficient_evidence=bool(insufficient),
                    review_required=bool(review_required),
                )
            )
        elif float(confidence) >= config.review_threshold:
            review_required = True

    review = bool(review_required or reasons or insufficient)
    accepted = bool(not reasons and decisions and not insufficient)
    return ValidationResult(
        accepted=accepted,
        review_required=review,
        reasons=reasons,
        decision=decisions[0] if decisions else None,
        decisions=decisions if accepted else [],
        raw_text=raw_text,
    )
