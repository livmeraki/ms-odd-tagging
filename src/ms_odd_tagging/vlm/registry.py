"""VLM backend ownership and lifecycle status."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


VLMStatus = Literal["canonical", "candidate", "experiment", "legacy"]


@dataclass(frozen=True)
class VLMBackend:
    module: str
    status: VLMStatus
    responsibility: str


VLM_BACKENDS: dict[str, VLMBackend] = {
    "local-vllm": VLMBackend(
        "ms_odd_tagging.tagger.model_based.local_vllm",
        "candidate",
        "Generic local model-facing inference path.",
    ),
    "qwen-poc": VLMBackend(
        "ms_odd_tagging.qwen_vlm_poc",
        "experiment",
        "Qwen-specific evidence, prompting, validation, and review experiment.",
    ),
}


def get_vlm_backend(name: str) -> VLMBackend:
    try:
        return VLM_BACKENDS[name]
    except KeyError as exc:
        known = ", ".join(sorted(VLM_BACKENDS))
        raise KeyError(f"unknown VLM backend {name!r}; choose one of: {known}") from exc
