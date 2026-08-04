from __future__ import annotations

import json
from pathlib import Path

from ms_odd_tagging.input_generator import frame_input
from ms_odd_tagging.input_generator.frame_input import (
    SCHEMA_VERSION,
    build_frame_json,
    frame_id,
    following_lane_intervals_to_events,
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


def test_following_lane_intervals_are_serialized_as_events() -> None:
    lane_result = {
        "intervals": [
            {
                "scenario": "following_lane_without_lead",
                "start_frame_index": 0,
                "end_frame_index": 2,
                "start_time_since_start_s": 0.0,
                "end_time_since_start_s": 0.2,
                "start_timestamp_unix_s": 1000.0,
                "end_timestamp_unix_s": 1000.2,
                "frame_count": 3,
                "boundary_convention": "inclusive_observed_frames",
            },
            {
                "scenario": "unknown",
                "start_frame_index": 3,
                "end_frame_index": 3,
                "start_time_since_start_s": 0.3,
                "end_time_since_start_s": 0.3,
            },
            {
                "scenario": "following_lane_with_lead",
                "start_frame_index": 4,
                "end_frame_index": 5,
                "start_time_since_start_s": 0.4,
                "end_time_since_start_s": 0.5,
                "frame_count": 2,
            },
        ]
    }

    events = following_lane_intervals_to_events(lane_result)

    assert [event.scenario for event in events] == [
        "following_lane_without_lead",
        "following_lane_with_lead",
    ]
    assert events[0].start_frame == 0
    assert events[0].end_frame == 2
    assert events[0].detector_version == "following-lane-frame-tags-v1"
    assert events[0].evidence["frame_count"] == 3


def test_build_recording_writes_following_lane_events(
    tmp_path: Path,
    monkeypatch,
) -> None:
    canonical = tmp_path / "rec_canonical_odld_frames.json"
    canonical.write_text(
        json.dumps(
            {
                "recording_id": "rec",
                "scenario_taxonomy": [
                    "following_lane_with_lead",
                    "following_lane_without_lead",
                ],
                "frames": [
                    sample_frame(0),
                    sample_frame(1),
                    sample_frame(2),
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        frame_input,
        "load_config",
        lambda: {
            "config_version": "test",
            "enabled_scenarios": [
                "following_lane_with_lead",
                "following_lane_without_lead",
            ],
        },
    )
    monkeypatch.setattr(frame_input, "detect_recording_events", lambda *_: ([], {}))
    monkeypatch.setattr(
        "ms_odd_tagging.scenarios.following_lane.detector.run_following_lane",
        lambda recording: {
            "frames": [
                {
                    "frame_index": 0,
                    "state": "following_lane_with_lead",
                    "lead": {"class": "car"},
                },
                {
                    "frame_index": 1,
                    "state": "following_lane_with_lead",
                    "lead": {"class": "car"},
                },
                {
                    "frame_index": 2,
                    "state": "following_lane_without_lead",
                },
            ],
            "intervals": [
                {
                    "scenario": "following_lane_with_lead",
                    "start_frame_index": 0,
                    "end_frame_index": 1,
                    "start_time_since_start_s": 0.0,
                    "end_time_since_start_s": 0.1,
                    "frame_count": 2,
                },
                {
                    "scenario": "following_lane_without_lead",
                    "start_frame_index": 2,
                    "end_frame_index": 2,
                    "start_time_since_start_s": 0.2,
                    "end_time_since_start_s": 0.2,
                    "frame_count": 1,
                },
            ],
        },
    )
    monkeypatch.setattr(
        frame_input,
        "render_bev_model_png",
        lambda *args, **kwargs: Path(args[4]).write_bytes(b"png"),
    )

    frame_input.build_recording(
        canonical,
        tmp_path / "out",
        extent=(45.0, 45.0, 25.0, 95.0),
        size=(320, 288),
        ld_filters={"roadmark_classes": set(), "line_patterns": set()},
        max_objects=24,
        frames_per_second=None,
    )

    rule_events = json.loads(
        (tmp_path / "out" / "rec" / "recording_rule_events.json").read_text(
            encoding="utf-8"
        )
    )["rule_based_events"]
    assert [event["scenario"] for event in rule_events] == [
        "following_lane_with_lead",
        "following_lane_without_lead",
    ]
