"""Shared VLM contracts and backend ownership.

Evidence construction remains scenario-specific. Only transport-neutral request,
response, and backend selection contracts belong here.
"""

from .contracts import VLMClient, VLMRequest, VLMResponse
from .registry import VLM_BACKENDS, VLMBackend, get_vlm_backend

__all__ = [
    "VLM_BACKENDS",
    "VLMBackend",
    "VLMClient",
    "VLMRequest",
    "VLMResponse",
    "get_vlm_backend",
]
