from __future__ import annotations

import json
from pathlib import Path

from ms_odd_tagging.gt.workspace import (
    _dashboard_html,
    _prediction_tags,
    _prepare_rows,
)


def _write_frame_tag(path: Path, frame: int, timestamp_s: float, labels: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "frame": frame,
                "timestamp_s": timestamp_s,
                "tags": {
                    "motional_scenarios": {
                        label: True for label in labels
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_prediction_tags_reads_current_recording_frame_tags(tmp_path: Path) -> None:
    recording = tmp_path / "Rec_A"
    tags = recording / "recording_frame_tags_1fps"
    _write_frame_tag(tags / "frame_000000.json", 0, 0.0, ["stationary"])
    _write_frame_tag(tags / "frame_000010.json", 10, 1.0, ["starting_left_turn"])

    assert _prediction_tags(recording) == ["starting_left_turn", "stationary"]


def test_prepare_rows_uses_timestamp_fallback_and_preserves_unreviewed_state(tmp_path: Path) -> None:
    recording = tmp_path / "Rec_A"
    tags = recording / "recording_frame_tags_1fps"
    _write_frame_tag(tags / "frame_000010.json", 10, 1.0, ["stationary"])

    rows = [
        {
            "frame_index": 11,
            "timestamp": 1.02,
            "prediction": {},
            "gt": None,
            "reviewed": False,
        }
    ]
    gt_path = tmp_path / "gt" / "Rec_A_manual_gt.json"

    matched = _prepare_rows(rows, recording, gt_path, 1.0)

    assert matched == 1
    assert rows[0]["prediction_source_frame_index"] == 10
    assert rows[0]["reviewed"] is False
    assert rows[0]["prediction"]["ego_motion"]["state"] == "stationary"
    assert rows[0]["gt"] == rows[0]["prediction"]


def test_dashboard_describes_current_prediction_source() -> None:
    page = _dashboard_html()

    assert "current frame inputs + current 1 FPS tags" in page
    assert "Missing prediction" in page
    assert "GT finished" in page
