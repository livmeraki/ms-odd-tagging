from __future__ import annotations

import json
from pathlib import Path

from ms_odd_tagging.input_generator.frame_input import (
    SCHEMA_VERSION,
    build_frame_json,
    frame_id,
    sample_frames_by_rate,
)
from ms_odd_tagging.validator.frame_schema import validate_frame_file


def sample_frame(index: int = 7) -> dict:
    return {
        "frame_index": index,
        "timestamp_unix_s": 1000.7,
        "time_since_start_s": 0.7,
        "ego": {"speed_mps": 5.0, "position_lcs_m": [1.0, 2.0, 0.0]},
        "scenario_signals": {"nearby_30m_counts": {"pedestrian": 0, "motorcycle": 0}},
        "objects": [],
        "interaction_candidates": [],
        "ld": {"available": False},
    }


def test_frame_id_is_stable_and_zero_padded() -> None:
    assert frame_id("recording", 7) == "recording:frame-000007"


def test_timestamp_sampling_defaults_can_select_one_frame_per_second() -> None:
    frames = [
        {"frame_index": index, "time_since_start_s": timestamp}
        for index, timestamp in enumerate((0.0, 0.1, 0.9, 1.0, 1.9, 2.05))
    ]
    assert [frame["frame_index"] for frame in sample_frames_by_rate(frames, 1.0)] == [
        0,
        3,
        5,
    ]
    assert sample_frames_by_rate(frames, None) == frames


def test_timestamp_sampling_rejects_non_positive_rates() -> None:
    try:
        sample_frames_by_rate([], 0.0)
    except ValueError as exc:
        assert "positive finite" in str(exc)
    else:
        raise AssertionError("zero frames-per-second must be rejected")


def test_build_frame_json_is_single_frame_and_has_one_bev() -> None:
    recording = {"recording_id": "recording", "scenario_taxonomy": ["stationary"]}
    payload = build_frame_json(
        recording,
        sample_frame(),
        Path("canonical/recording.json"),
        "bev.png",
        max_objects=80,
    )
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["frame_index"] == payload["bev"]["frame_index"] == 7
    assert payload["bev"]["path"] == "bev.png"
    assert "time_window" not in payload
    assert "bev_keyframes" not in payload
    assert "rule_based_events" not in payload


def test_frame_schema_validates_same_frame_bev(tmp_path: Path) -> None:
    recording = {"recording_id": "recording", "scenario_taxonomy": []}
    payload = build_frame_json(
        recording,
        sample_frame(),
        Path("canonical/recording.json"),
        "bev.png",
        max_objects=80,
    )
    (tmp_path / "bev.png").write_bytes(b"png-placeholder")
    frame_path = tmp_path / "frame.json"
    frame_path.write_text(json.dumps(payload), encoding="utf-8")
    assert validate_frame_file(frame_path) == []
