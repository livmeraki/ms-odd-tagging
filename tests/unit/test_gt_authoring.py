from __future__ import annotations

import json
from pathlib import Path

import pytest

from ms_odd_tagging.gt_comparison.authoring import build_review_payload, discover_recordings, write_reviewer
from ms_odd_tagging.gt_comparison.labels import (
    SPEED_LABELS,
    TAXONOMY,
    labels_with_frame_speed,
    speed_band_from_frame,
)
from ms_odd_tagging.gt_comparison.matching import gt_labels_for_frame


RECORDING = "Rec_Test_001"


def make_frame(root: Path, frame_index: int, speed_mps: object) -> str:
    frame_id = f"{RECORDING}:frame-{frame_index:06d}"
    folder = root / RECORDING / f"frame_{frame_index:06d}"
    folder.mkdir(parents=True)
    (folder / "bev.png").write_bytes(b"png")
    frame = {
        "schema_version": "odld-dynamic-frame-model-input-v1",
        "recording_id": RECORDING,
        "frame_id": frame_id,
        "frame_index": frame_index,
        "timestamp_unix_s": 1_700_000_000 + frame_index / 10,
        "time_since_start_s": frame_index / 10,
        "ego": {"speed_mps": speed_mps},
        "bev": {"path": "bev.png", "frame_index": frame_index, "format": "png"},
    }
    (folder / "frame.json").write_text(json.dumps(frame), encoding="utf-8")
    return frame_id


def test_review_payload_exports_comparison_ready_frame_gt(tmp_path: Path) -> None:
    frame_inputs = tmp_path / "frame_inputs"
    first = make_frame(frame_inputs, 0, 2.0)
    second = make_frame(frame_inputs, 10, 8.0)
    payload = build_review_payload(frame_inputs, RECORDING)
    assert payload["download_filename"] == f"{RECORDING}_frame_gt.json"
    assert len(payload["review_frames"]) == 2
    assert payload["review_frames"][0]["image"].startswith("file:")
    assert gt_labels_for_frame(payload["gt"], RECORDING, first)["low_magnitude_speed"] is True
    assert gt_labels_for_frame(payload["gt"], RECORDING, second)["medium_magnitude_speed"] is True


def test_full_requested_taxonomy_is_available_for_review() -> None:
    assert len(TAXONOMY) == 42
    assert TAXONOMY[0] == "near_multiple_bikes"
    assert TAXONOMY[-1] == "changing_lane_with_trail"
    assert "accelerating_at_traffic_light_with_lead" in TAXONOMY
    assert "near_pedestrian_on_crosswalk_with_ego" in TAXONOMY


def test_direct_references_fill_supported_labels_and_preserve_unknowns(
    tmp_path: Path,
) -> None:
    frame_inputs = tmp_path / "frame_inputs"
    frame_id = make_frame(frame_inputs, 0, 2.0)
    frame_dir = frame_inputs / RECORDING / "frame_000000"
    (frame_dir / "gt_reference.json").write_text(
        json.dumps(
            {
                "directly_derived_labels": {
                    "near_multiple_bikes": True,
                    "following_lane_with_lead": False,
                    "behind_bike": False,
                    "following_lane_with_slow_lead": None,
                },
                "rule_based_reference": {
                    "active_labels": ["near_multiple_bikes"]
                },
            }
        ),
        encoding="utf-8",
    )
    payload = build_review_payload(frame_inputs, RECORDING)
    labels = payload["gt"]["frames"][frame_id]["labels"]
    assert labels["near_multiple_bikes"] is True
    assert labels["following_lane_with_lead"] is False
    assert labels["following_lane_with_slow_lead"] is None
    assert payload["review_frames"][0]["derivation"]["active_labels"] == [
        "near_multiple_bikes"
    ]


def test_reviewer_contains_efficient_frame_review_controls(tmp_path: Path) -> None:
    frame_inputs = tmp_path / "frame_inputs"
    make_frame(frame_inputs, 0, 2.0)
    output = tmp_path / "review" / "review.html"
    write_reviewer(frame_inputs, RECORDING, output)
    page = output.read_text(encoding="utf-8")
    assert "Download GT JSON" in page
    assert "Import GT JSON" in page
    assert "Mark reviewed + next" in page
    assert "Jump to frame index" in page
    assert "localStorage" in page
    assert "scenario-frame-gt-labels-v1" in page
    assert page.count("document.createElement('img')") == 1
    assert "median speed" not in page.lower()
    assert "start keyframe" not in page.lower()
    assert "middle keyframe" not in page.lower()
    assert "end keyframe" not in page.lower()


def test_existing_manual_frame_labels_are_preserved(tmp_path: Path) -> None:
    frame_inputs = tmp_path / "frame_inputs"
    frame_id = make_frame(frame_inputs, 0, 2.0)
    existing = tmp_path / "existing.json"
    existing.write_text(json.dumps({"recording_id": RECORDING, "frames": {frame_id: {
        "labels": {"starting_left_turn": True}, "needs_review": False,
        "reviewer": "reviewer-a", "notes": "confirmed",
    }}}), encoding="utf-8")
    frame = build_review_payload(frame_inputs, RECORDING, existing)["gt"]["frames"][frame_id]
    assert frame["labels"]["starting_left_turn"] is True
    assert frame["needs_review"] is False
    assert frame["reviewer"] == "reviewer-a"
    assert frame["notes"] == "confirmed"


@pytest.mark.parametrize(("speed", "expected"), [
    (0.0, "stationary"), (0.499999, "stationary"),
    (0.5, "low_magnitude_speed"), (4.999999, "low_magnitude_speed"),
    (5.0, "medium_magnitude_speed"), (14.999999, "medium_magnitude_speed"),
    (15.0, "high_magnitude_speed"),
])
def test_frame_speed_boundaries_are_exact_and_exclusive(speed: float, expected: str) -> None:
    assert speed_band_from_frame(speed) == expected
    labels = labels_with_frame_speed({}, speed)
    assert [name for name in SPEED_LABELS if labels[name]] == [expected]


@pytest.mark.parametrize("speed", [None, "5", -0.1, float("nan"), float("inf")])
def test_invalid_frame_speed_remains_unknown(speed: object) -> None:
    assert speed_band_from_frame(speed) is None
    labels = labels_with_frame_speed({}, speed)
    assert all(labels[name] is None for name in SPEED_LABELS)


def test_discover_recordings_scales_across_frame_folders(tmp_path: Path) -> None:
    frame_inputs = tmp_path / "frame_inputs"
    make_frame(frame_inputs, 0, 2.0)
    other = frame_inputs / "Rec_Test_002" / "frame_000000"
    other.mkdir(parents=True)
    (other / "frame.json").write_text("{}", encoding="utf-8")
    (frame_inputs / "empty").mkdir()
    assert discover_recordings(frame_inputs) == [RECORDING, "Rec_Test_002"]
