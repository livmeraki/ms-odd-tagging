from __future__ import annotations

import json

from ms_odd_tagging.qwen_vlm_poc.client import _vlm_candidate_input
from ms_odd_tagging.qwen_vlm_poc.models import CandidateWindow, EvidenceItem


def _candidate() -> CandidateWindow:
    speed_series = [
        {"frame": index, "time_s": index * 0.1, "speed_mps": round(8.0 - index * 0.1, 3)}
        for index in range(30)
    ]
    track_points = [
        {
            "frame": index,
            "time_offset_s": round((index - 15) * 0.1, 3),
            "longitudinal_m": round(10.0 - index * 0.1, 3),
            "lateral_m": round(4.0 - index * 0.25, 3),
        }
        for index in range(24)
    ]
    return CandidateWindow(
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
        primary_object_ids=["ped-1"],
        metadata={
            "candidate_strategy": "event-driven",
            "visual_evidence_id": "rec_waiting_scene_000010_000040:bev_sequence",
            "ego_measurements": [{"frame": 10, "time_s": 1.0, "speed_mps": 7.5}],
            "ego_speed_series": speed_series,
            "pedestrian_measurements": [
                {
                    "frame": 10,
                    "time_s": 1.0,
                    "pedestrians": [
                        {"object_id": "ped-1", "longitudinal_m": 8.0, "lateral_m": 4.0}
                    ],
                }
            ],
            "pedestrian_tracks_reference": {
                "reference_frame": 15,
                "coordinate_frame": "reference_frame_ego_centered_heading_aligned",
                "pedestrians": [{"object_id": "ped-1", "points": track_points}],
            },
            "ego_future_paths": [
                {
                    "frame": 10,
                    "corridor_half_width_m": 1.5,
                    "points": [
                        {"longitudinal_m": 0.0, "lateral_m": 0.0},
                        {"longitudinal_m": 20.0, "lateral_m": 3.0},
                    ],
                }
            ],
            "ego_response_frames": [20, 21],
            "temporally_linked": True,
        },
    )


def test_event_driven_waiting_vlm_input_is_compact_and_neutral():
    payload = _vlm_candidate_input(_candidate())
    text = json.dumps(payload, sort_keys=True)

    assert payload["evaluation_mode"] == "compact_bev_tracks_speed"
    assert payload["target_pedestrian_ids"] == ["ped-1"]
    assert payload["bev_frame_indices"] == [10, 16, 22, 28, 34, 40]
    assert len(payload["ego_speed_series"]) == 30
    assert len(payload["pedestrian_tracks_reference"]["pedestrians"][0]["points"]) == 24

    # These were intentionally removed because the same information is already
    # represented by the BEV overlays or the denser temporal evidence.
    assert "ego_measurements" not in payload
    assert "pedestrian_measurements" not in payload
    assert "ego_future_paths" not in payload
    assert "candidate_scene_id" not in payload

    for forbidden in (
        "conflict",
        "moving_toward_corridor",
        "ego_response_frames",
        "temporally_linked",
        "pedestrian_corridor_conflict",
        '"yielding"',
        '"crossing": true',
    ):
        assert forbidden not in text


def test_overflow_compaction_downsamples_temporal_evidence():
    payload = _vlm_candidate_input(_candidate(), overflow_compact=True)

    assert payload["evaluation_mode"] == "compact_overflow_retry_bev_tracks_speed"
    assert len(payload["ego_speed_series"]) <= 12
    points = payload["pedestrian_tracks_reference"]["pedestrians"][0]["points"]
    assert len(points) <= 10
    assert points[0]["frame"] == 0
    assert points[-1]["frame"] == 23
