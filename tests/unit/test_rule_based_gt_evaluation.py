import pytest

from ms_odd_tagging.gt_comparison.rule_based_evaluation import (
    gt_quality_summary,
    metric_row,
    validate_gt,
)


def test_metric_row_calculates_binary_scores() -> None:
    row = metric_row("x", {"tp": 3, "tn": 4, "fp": 1, "fn": 2})
    assert row["accuracy"] == 0.7
    assert row["precision"] == 0.75
    assert row["recall"] == 0.6
    assert row["f1"] == pytest.approx(2 / 3)


def test_validate_gt_rejects_nonexclusive_speed_labels() -> None:
    labels = {
        "stationary": True,
        "high_magnitude_speed": True,
        "low_magnitude_speed": False,
        "medium_magnitude_speed": False,
        "following_lane_with_lead": False,
        "following_lane_without_lead": True,
        "starting_left_turn": False,
        "starting_right_turn": False,
        "stopping_with_lead": False,
        "stopping_without_lead": False,
        "near_multiple_pedestrians": False,
        "near_multiple_motorcycle": False,
    }
    payload = {
        "schema_version": "scenario-frame-gt-labels-v1",
        "recording_id": "rec",
        "frames": {
            "rec:frame-000000": {
                "frame_id": "rec:frame-000000",
                "frame_index": 0,
                "timestamp_unix_s": 10.0,
                "time_since_start_s": 0.0,
                "labels": labels,
            }
        },
    }
    canonical = {
        0: {
            "frame_index": 0,
            "timestamp_unix_s": 10.0,
            "time_since_start_s": 0.0,
        }
    }
    errors = validate_gt(payload, "rec", canonical)
    assert any("exactly one true speed label" in error for error in errors)


def test_quality_summary_excludes_initial_frames() -> None:
    payload = {
        "recording_id": "rec",
        "frames": {
            "first": {
                "frame_index": 0,
                "needs_review": True,
                "labels": {
                    "stationary": False,
                    "high_magnitude_speed": True,
                    "low_magnitude_speed": False,
                    "medium_magnitude_speed": False,
                },
            },
            "scored": {
                "frame_index": 10,
                "needs_review": False,
                "labels": {
                    "stationary": False,
                    "high_magnitude_speed": True,
                    "low_magnitude_speed": False,
                    "medium_magnitude_speed": False,
                },
            },
        },
    }
    canonicals = {
        "rec": {
            "frames": [
                {"frame_index": 0, "ego": {"speed_mps": 16.0}},
                {"frame_index": 10, "ego": {"speed_mps": 16.0}},
            ]
        }
    }
    quality = gt_quality_summary([payload], canonicals, minimum_frame_index=5)
    assert quality["reviewed_frames"] == 1
    assert quality["pending_frames"] == 0
