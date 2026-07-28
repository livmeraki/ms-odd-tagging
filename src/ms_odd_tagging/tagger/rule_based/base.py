"""Common detector contract, intentionally independent of input modality."""

from __future__ import annotations

from typing import Any, Protocol

from ms_odd_tagging.features.ego_motion import EgoMotionFeatures

from .scenario_event import ScenarioEvent


class ScenarioDetector(Protocol):
    scenario_name: str
    required_features: frozenset[str]
    output_scenarios: frozenset[str]

    def detect(
        self,
        frames: list[dict[str, Any]],
        features: EgoMotionFeatures,
        config: dict[str, Any],
    ) -> list[ScenarioEvent]: ...
