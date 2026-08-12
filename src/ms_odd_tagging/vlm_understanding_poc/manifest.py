"""Manifest loading with reusable ${VARIABLE} substitution."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .runner import Probe


_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _substitute(value: Any, variables: dict[str, str]) -> Any:
    if isinstance(value, str):
        def repl(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in variables:
                raise ValueError(f"Undefined manifest variable: {name}")
            return variables[name]
        return _VAR_PATTERN.sub(repl, value)
    if isinstance(value, list):
        return [_substitute(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(item, variables) for key, item in value.items()}
    return value


def _resolve_value(value: Any, base_dir: Path) -> Any:
    if isinstance(value, dict) and set(value) == {"json_file"}:
        path = (base_dir / value["json_file"]).resolve()
        return json.loads(path.read_text(encoding="utf-8"))
    return value


def load_manifest(path: Path, overrides: dict[str, str] | None = None) -> list[Probe]:
    """Load probes and expand top-level manifest variables.

    Manifest example::

        {
          "variables": {"BEV_ROOT": "/path/to/recording"},
          "probes": [{"images": ["${BEV_ROOT}/frame_000401/bev_revised.png"]}]
        }

    CLI overrides may replace any variable without editing the manifest.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    variables = {str(k): str(v) for k, v in (payload.get("variables") or {}).items()}
    if overrides:
        variables.update({str(k): str(v) for k, v in overrides.items()})

    raw_probes = _substitute(payload.get("probes", []), variables)
    base_dir = path.parent
    probes: list[Probe] = []
    for raw in raw_probes:
        images = tuple((base_dir / item).resolve() for item in raw.get("images", []))
        probes.append(
            Probe(
                probe_id=str(raw["probe_id"]),
                sample_id=str(raw.get("sample_id") or raw["probe_id"]),
                category=str(raw["category"]),
                modality=str(raw["modality"]),
                question=str(raw["question"]),
                expected_answer=raw.get("expected_answer"),
                answer_choices=tuple(raw.get("answer_choices") or ()),
                images=images,
                structured_evidence=_resolve_value(raw.get("structured_evidence"), base_dir),
                legend=_resolve_value(raw.get("legend"), base_dir),
                notes=raw.get("notes"),
            )
        )
    return probes


def parse_set_args(items: list[str] | None) -> dict[str, str]:
    """Parse repeated KEY=VALUE CLI overrides."""
    result: dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"--set expects KEY=VALUE, got: {item}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"--set has empty key: {item}")
        result[key] = value
    return result
