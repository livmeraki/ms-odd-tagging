from __future__ import annotations

import json
from pathlib import Path

import pytest

from ms_odd_tagging.gt_comparison.authoring import build_review_payload, discover_recordings, write_reviewer
from ms_odd_tagging.gt_comparison.labels import (
    IMPLEMENTED_SCENARIOS,
    MINIMUM_REVIEW_FRAME_INDEX,
    SCENARIO_GROUPS,
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
    assert len(TAXONOMY) == 49
    assert TAXONOMY[0] == "stationary"
    assert TAXONOMY[-1] == "behind_motorcycle"
    assert "accelerating_at_traffic_light_with_lead" in TAXONOMY
    assert "near_pedestrian_on_crosswalk_with_ego" in TAXONOMY
    assert {
        "crossed_by_bike",
        "crossed_by_motorcycle",
        "crossed_by_vehicle",
        "following_lane_with_slow_lead",
        "near_barrier_on_driveable",
    }.issubset(IMPLEMENTED_SCENARIOS)
    assert len(TAXONOMY) == len(set(TAXONOMY))
    assert SCENARIO_GROUPS[-1]["implemented"] is False


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


def test_review_payload_keeps_compact_event_and_nearby_object_debug(
    tmp_path: Path,
) -> None:
    frame_inputs = tmp_path / "frame_inputs"
    make_frame(frame_inputs, 10, 4.0)
    frame_dir = frame_inputs / RECORDING / "frame_000010"
    frame_path = frame_dir / "frame.json"
    frame = json.loads(frame_path.read_text(encoding="utf-8"))
    frame["objects"] = [
        {
            "object_id": "1202",
            "class": "car",
            "annotation_type": "dynamic",
            "position_ego_m": {
                "distance": 12.0,
                "longitudinal": 8.0,
                "lateral": -9.0,
            },
            "velocity_lcs_mps": [3.0, 4.0, 0.0],
            "heading_relative_rad": 1.2,
        },
        {
            "object_id": "far",
            "class": "car",
            "annotation_type": "dynamic",
            "position_ego_m": {
                "distance": 31.0,
                "longitudinal": 31.0,
                "lateral": 0.0,
            },
        },
    ]
    frame_path.write_text(json.dumps(frame), encoding="utf-8")
    (frame_dir / "gt_reference.json").write_text(
        json.dumps(
            {
                "directly_derived_labels": {"crossed_by_vehicle": True},
                "rule_based_reference": {
                    "active_labels": ["crossed_by_vehicle"],
                    "active_events": [
                        {
                            "scenario": "crossed_by_vehicle",
                            "start_frame": 8,
                            "end_frame": 12,
                            "evidence": {
                                "object_track_id": "vehicle:1202",
                                "crossing_angle_deg": 82.0,
                                "large_geometry": [[0, 1]] * 100,
                            },
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    review = build_review_payload(frame_inputs, RECORDING)["review_frames"][0]
    assert review["derivation"]["active_events"][0]["evidence"] == {
        "object_track_id": "vehicle:1202",
        "crossing_angle_deg": 82.0,
    }
    assert review["debug"]["nearby_dynamic_objects"] == [
        {
            "object_id": "1202",
            "class": "car",
            "distance_m": 12.0,
            "longitudinal_m": 8.0,
            "lateral_m": -9.0,
            "speed_mps": 5.0,
            "heading_relative_rad": 1.2,
        }
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
    assert 'id="scenarioFilter"' in page
    assert "groupStateKey" in page
    assert "restoreGroupState()" in page
    assert "selectedScenario()" in page
    assert "frameMatchesScenario" in page
    assert "shownScenarios" in page
    assert "gtFrame().labels[scenario]" in page
    assert "scenario-frame-gt-labels-v1" in page
    assert "phase3c_path_crossing" in page
    assert "crossed_by_vehicle" in page
    assert "Frame debug evidence" in page
    assert "Dynamic objects within 30 m" in page
    assert "Active rule events" in page
    assert "Excluded from scoring" in page
    assert page.count("document.createElement('img')") == 1
    assert "median speed" not in page.lower()
    assert "start keyframe" not in page.lower()
    assert "middle keyframe" not in page.lower()
    assert "end keyframe" not in page.lower()


def test_write_reviewer_uses_relative_bev_paths(tmp_path: Path) -> None:
    frame_inputs = tmp_path / "outputs" / "02_frame_inputs_revised"
    make_frame(frame_inputs, 0, 2.0)
    output = tmp_path / "outputs" / "frame_gt_authoring" / "review.html"
    write_reviewer(frame_inputs, RECORDING, output)
    page = output.read_text(encoding="utf-8")
    assert "file://" not in page
    assert "../02_frame_inputs_revised/Rec_Test_001/frame_000000/bev.png" in page


def test_frames_before_detection_reliability_boundary_are_excluded(
    tmp_path: Path,
) -> None:
    frame_inputs = tmp_path / "frame_inputs"
    first = make_frame(frame_inputs, 0, 2.0)
    reliable = make_frame(frame_inputs, MINIMUM_REVIEW_FRAME_INDEX, 2.0)
    payload = build_review_payload(frame_inputs, RECORDING)
    assert payload["minimum_scored_frame_index"] == 5
    assert payload["gt"]["minimum_scored_frame_index"] == 5
    assert payload["gt"]["frames"][first]["excluded_from_evaluation"] is True
    assert payload["gt"]["frames"][reliable]["excluded_from_evaluation"] is False


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
