"""Stable event representation shared by trajectory and future OD/LD detectors."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ScenarioEvent:
    scenario: str
    start_frame: int
    end_frame: int
    start_timestamp_s: float
    end_timestamp_s: float
    duration_s: float
    confidence: float = 1.0
    source: str = "rule_based"
    detector_version: str = "phase1-v1"
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
