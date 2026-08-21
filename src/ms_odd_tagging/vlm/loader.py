"""Canonical recording loading for the VLM POC."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ms_odd_tagging.frame_inputs.standard import canonical_recording_id


def canonical_path(input_dir: Path, recording_id: str) -> Path:
    candidates = (
        input_dir / f"{recording_id}_canonical_odld_frames.json",
        input_dir / f"{recording_id}_canonical_frames.json",
    )
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        f"canonical recording not found for {recording_id!r} under {input_dir}"
    )


def load_recording(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "recording_id" not in data:
        data["recording_id"] = canonical_recording_id(path)
    data.setdefault("frames", [])
    return data

