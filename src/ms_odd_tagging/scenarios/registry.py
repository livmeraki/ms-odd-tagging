"""Authoritative scenario implementation ownership.

This does not combine detector algorithms. It records which package owns each
kind of work so features, policies, and experiments cannot silently replace one
another.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ScenarioStatus = Literal["canonical", "candidate", "experiment", "unsupported"]


@dataclass(frozen=True)
class ScenarioOwner:
    module: str | None
    status: ScenarioStatus
    responsibility: str


SCENARIO_OWNERS: dict[str, ScenarioOwner] = {
    "direct_rule_based": ScenarioOwner(
        "ms_odd_tagging.tagger.rule_based.registry",
        "canonical",
        "Production detector registry and policy-driven recording events.",
    ),
    "shared_features": ScenarioOwner(
        "ms_odd_tagging.features",
        "canonical",
        "Reusable deterministic measurements; never final scenario policy.",
    ),
    "following_lane": ScenarioOwner(
        "ms_odd_tagging.scenarios.following_lane",
        "canonical",
        "Physical lane-following and lead-vehicle state.",
    ),
    "model_based": ScenarioOwner(
        "ms_odd_tagging.tagger.model_based.local_vllm",
        "candidate",
        "General local model inference compatibility path.",
    ),
    "qwen_vlm": ScenarioOwner(
        "ms_odd_tagging.qwen_vlm_poc",
        "experiment",
        "Scenario-specific VLM evidence and candidate-generation experiment.",
    ),
}


def get_scenario_owner(name: str) -> ScenarioOwner:
    try:
        return SCENARIO_OWNERS[name]
    except KeyError as exc:
        known = ", ".join(sorted(SCENARIO_OWNERS))
        raise KeyError(f"unknown scenario owner {name!r}; choose one of: {known}") from exc
