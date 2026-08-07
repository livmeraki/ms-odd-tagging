"""Serializable models for Qwen VLM candidate bundles and decisions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ScenarioName = Literal[
    "waiting_for_pedestrian_to_cross",
    "on_intersection",
    "starting_u_turn",
    "traffic_light_episode",
]


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    kind: str
    summary: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateWindow:
    candidate_id: str
    recording_id: str
    scenario: ScenarioName
    start_frame: int
    end_frame: int
    start_timestamp_s: float
    end_timestamp_s: float
    evidence: list[EvidenceItem]
    selected_frame_indices: list[int]
    bev_paths: list[str] = field(default_factory=list)
    primary_object_ids: list[str] = field(default_factory=list)
    recall_reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def evidence_ids(self) -> set[str]:
        return {item.evidence_id for item in self.evidence}

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence"] = [item.to_dict() for item in self.evidence]
        return data


@dataclass(frozen=True)
class VlmDecision:
    recording_id: str
    window_start_frame: int
    window_end_frame: int
    scenario: str
    decision: bool
    confidence: float
    event_start_frame: int | None
    event_end_frame: int | None
    primary_object_ids: list[str]
    evidence_ids: list[str]
    reason: str
    ambiguities: list[str]
    insufficient_evidence: bool
    review_required: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationResult:
    accepted: bool
    review_required: bool
    reasons: list[str]
    decision: VlmDecision | None = None
    decisions: list[VlmDecision] = field(default_factory=list)
    raw_text: str | None = None
