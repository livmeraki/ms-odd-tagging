"""Transport-neutral contracts shared by model-based inference paths."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class VLMRequest:
    system_prompt: str
    user_prompt: str
    image_paths: Sequence[Path] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VLMResponse:
    text: str
    model: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


class VLMClient(Protocol):
    def generate(self, request: VLMRequest) -> VLMResponse:
        """Generate one response without applying scenario policy."""
