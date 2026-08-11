from __future__ import annotations

import json

from ms_odd_tagging.qwen_vlm_poc.client import _vlm_candidate_input
from ms_odd_tagging.qwen_vlm_poc.models import CandidateWindow, EvidenceItem


def test_event_driven_waiting_vlm_input_excludes_candidate_heuristics():
    candidate = CandidateWindow(
        candidate_id="rec_waiting_scene_000010_000040",
        recording_id="rec",
        scenario="waiting_for_pedestrian_to_cross",
        start_frame=10,
        end_frame=40,
        start_timestamp_s=1.0,
        end_timestamp_s=4.0,
        evidence=[
            EvidenceItem(
                evidence_id="heuristic",
                kind="pedestrian_corridor_conflict",
                summary="should not reach model",
                data={"conflict": True, "moving_toward_corridor": True},
            )
        ],
        selected_frame_indices=[10, 16, 22, 28, 34, 40],
        primary_object_ids=["ped-1", "ped-2"],
        metadata={
            "candidate_strategy": "event-driven",
            "visual_evidence_id": "rec_waiting_scene_000010_000040:bev_sequence",
            "ego_measurements": [
                {"frame": 10, "time_s": 1.0, "speed_mps": 7.5},
                {"frame": 16, "time_s": 1.6, "speed_mps": 5.0},
            ],
            "ego_speed_series": [
                {"frame": 10, "time_s": 1.0, "speed_mps": 7.5},
                {"frame": 12, "time_s": 1.2, "speed_mps": 6.8},
                {"frame": 14, "time_s": 1.4, "speed_mps": 4.1},
                {"frame": 16, "time_s": 1.6, "speed_mps": 1.0},
            ],
            "pedestrian_measurements": [
                {
                    "frame": 10,
                    "time_s": 1.0,
                    "pedestrians": [
                        {"object_id": "ped-1", "longitudinal_m": 8.0, "lateral_m": 4.0},
                        {"object_id": "ped-2", "longitudinal_m": 12.0, "lateral_m": -3.0},
                    ],
                }
            ],
            "pedestrian_tracks_reference": {
                "reference_frame": 16,
                "coordinate_frame": "reference_frame_ego_centered_heading_aligned",
                "pedestrians": [
                    {
                        "object_id": "ped-1",
                        "points": [
                            {"frame": 10, "time_offset_s": -0.6, "longitudinal_m": 8.5, "lateral_m": 3.5},
                            {"frame": 16, "time_offset_s": 0.0, "longitudinal_m": 7.0, "lateral_m": 0.2},
                            {"frame": 20, "time_offset_s": 0.4, "longitudinal_m": 6.0, "lateral_m": -2.0},
                        ],
                    }
                ],
            },
            "ego_future_paths": [
                {
                    "frame": 10,
                    "coordinate_frame": "selected_frame_ego_centered_heading_aligned",
                    "horizon_s": 4.0,
                    "corridor_half_width_m": 1.5,
                    "points": [
                        {"frame": 10, "time_offset_s": 0.0, "longitudinal_m": 0.0, "lateral_m": 0.0},
                        {"frame": 20, "time_offset_s": 1.0, "longitudinal_m": 8.0, "lateral_m": 2.0},
                    ],
                }
            ],
            "ego_response_frames": [20, 21],
            "temporally_linked": True,
            "landmark_roles": {"strongest_conflict": 22},
        },
    )

    payload = _vlm_candidate_input(candidate)
    text = json.dumps(payload, sort_keys=True)

    assert payload["evaluation_mode"] == "bev_plus_neutral_future_path_tracks_and_dense_speed"
    assert payload["bev_frame_indices"] == [10, 16, 22, 28, 34, 40]
    assert payload["target_pedestrian_ids"] == ["ped-1", "ped-2"]
    assert payload["coordinate_convention"]["expected_path_reference"] == "ego_future_paths_not_lateral_zero"
    assert payload["coordinate_convention"]["lateral_m"].startswith("positive_left_negative_right")
    assert payload["ego_measurements"][0] == {
        "frame": 10,
        "time_s": 1.0,
        "speed_mps": 7.5,
    }
    assert payload["ego_speed_series"][-1]["speed_mps"] == 1.0
    assert payload["pedestrian_measurements"][0]["pedestrians"][0] == {
        "object_id": "ped-1",
        "longitudinal_m": 8.0,
        "lateral_m": 4.0,
    }
    assert payload["pedestrian_tracks_reference"]["reference_frame"] == 16
    assert payload["pedestrian_tracks_reference"]["pedestrians"][0]["points"][-1]["lateral_m"] == -2.0
    assert payload["ego_future_paths"][0]["corridor_half_width_m"] == 1.5
    assert payload["ego_future_paths"][0]["points"][1]["lateral_m"] == 2.0
    assert payload["visual_evidence_id"].endswith(":bev_sequence")
    for forbidden in (
        "conflict",
        "moving_toward_corridor",
        "ego_response_frames",
        "temporally_linked",
        "strongest_conflict",
        "pedestrian_corridor_conflict",
        '"yielding"',
        '"crossing": true',
    ):
        assert forbidden not in text
