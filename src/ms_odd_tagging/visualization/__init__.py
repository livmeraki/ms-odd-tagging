"""Standalone visualization generators."""


def build_explorer_payload(*args, **kwargs):
    from .scenario_explorer import build_explorer_payload as build

    return build(*args, **kwargs)


def generate_explorer(*args, **kwargs):
    from .scenario_explorer import generate_explorer as generate

    return generate(*args, **kwargs)


__all__ = ["build_explorer_payload", "generate_explorer"]
