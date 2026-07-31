from __future__ import annotations

import json
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts" / "odld_explorer"
sys.path.insert(0, str(SCRIPT_DIR))

from serve_gt_authoring_explorers import (  # noqa: E402
    validate_gt_payload,
    write_gt_atomically,
)


def test_write_gt_atomically_uses_recording_filename(tmp_path: Path) -> None:
    payload = {
        "schema_version": "scenario-frame-gt-labels-v1",
        "recording_id": "Rec_Test",
        "label_fields": ["stationary"],
        "frames": {},
    }

    target = write_gt_atomically(tmp_path, validate_gt_payload(payload))

    assert target == tmp_path / "Rec_Test_frame_gt.json"
    assert json.loads(target.read_text(encoding="utf-8")) == payload


def test_validate_gt_payload_rejects_unsafe_recording_id() -> None:
    payload = {
        "schema_version": "scenario-frame-gt-labels-v1",
        "recording_id": "../bad",
        "frames": {},
    }

    try:
        validate_gt_payload(payload)
    except ValueError as exc:
        assert "unsafe recording_id" in str(exc)
    else:
        raise AssertionError("unsafe recording_id was accepted")
