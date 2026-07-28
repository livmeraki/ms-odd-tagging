"""Deterministic scenario event detection and legacy candidate helpers."""

from .scenario_event import ScenarioEvent


def build_candidates(*args, **kwargs):
    """Load the legacy window candidate adapter lazily to avoid import cycles."""
    from .candidates import build_candidates as legacy_build_candidates

    return legacy_build_candidates(*args, **kwargs)


def detect_events(*args, **kwargs):
    from .registry import detect_events as registered_detect_events

    return registered_detect_events(*args, **kwargs)


def detect_recording_events(*args, **kwargs):
    from .registry import detect_recording_events as registered_detect_recording_events

    return registered_detect_recording_events(*args, **kwargs)


def load_config(*args, **kwargs):
    from .registry import load_config as registered_load_config

    return registered_load_config(*args, **kwargs)


def __getattr__(name):
    if name == "PHASE1_SCENARIOS":
        from .registry import PHASE1_SCENARIOS

        return PHASE1_SCENARIOS
    if name == "PHASE2_SCENARIOS":
        from .registry import PHASE2_SCENARIOS

        return PHASE2_SCENARIOS
    if name == "PHASE2B_SCENARIOS":
        from .registry import PHASE2B_SCENARIOS

        return PHASE2B_SCENARIOS
    if name == "PHASE3A_SCENARIOS":
        from .registry import PHASE3A_SCENARIOS

        return PHASE3A_SCENARIOS
    if name == "PHASE3B_SCENARIOS":
        from .registry import PHASE3B_SCENARIOS

        return PHASE3B_SCENARIOS
    if name == "PHASE3C_SCENARIOS":
        from .registry import PHASE3C_SCENARIOS

        return PHASE3C_SCENARIOS
    raise AttributeError(name)

__all__ = ["PHASE1_SCENARIOS", "PHASE2_SCENARIOS", "PHASE2B_SCENARIOS", "PHASE3A_SCENARIOS", "PHASE3B_SCENARIOS", "PHASE3C_SCENARIOS", "ScenarioEvent", "build_candidates", "detect_events", "detect_recording_events", "load_config"]
