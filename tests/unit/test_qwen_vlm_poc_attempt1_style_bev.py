from __future__ import annotations

from ms_odd_tagging.qwen_vlm_poc.attempt1_style_bev import render_candidate_bevs_attempt1_style
from ms_odd_tagging.qwen_vlm_poc.config import load_config
from ms_odd_tagging.qwen_vlm_poc.models import CandidateWindow, EvidenceItem


def test_attempt1_style_candidate_renderer_writes_side_bevs(tmp_path):
    recording = {
        "recording_id": "rec-a",
        "frames": [
            {
                "frame_index": 10,
                "ego": {
                    "position_lcs_m": [0.0, 0.0, 0.0],
                    "heading_lcs_rad": 0.0,
                    "speed_mps": 0.0,
                },
                "objects": [
                    {
                        "object_id": "ped-1",
                        "class": "pedestrian",
                        "position_lcs_m": [12.0, 2.0, 0.0],
                        "velocity_lcs_mps": [0.0, -0.8, 0.0],
                    },
                    {
                        "object_id": "veh-1",
                        "class": "car",
                        "position_lcs_m": [20.0, -3.0, 0.0],
                        "dimensions_m": {"length": 4.4, "width": 1.9},
                        "heading_relative_rad": 0.0,
                    },
                ],
                "ld": {"nearby_feature_ids": {"lane_lines": [], "roadmarks": [], "road_boundaries": []}},
            }
        ],
        "ld_feature_store": {"points": [], "lane_lines": [], "roadmarks": [], "road_boundaries": []},
    }
    candidate = CandidateWindow(
        candidate_id="rec-a_waiting_for_pedestrian_to_cross_000010_000010",
        recording_id="rec-a",
        scenario="waiting_for_pedestrian_to_cross",
        start_frame=10,
        end_frame=10,
        start_timestamp_s=1.0,
        end_timestamp_s=1.0,
        evidence=[EvidenceItem("ev-1", "test", "synthetic")],
        selected_frame_indices=[10],
        primary_object_ids=["ped-1"],
    )
    config = load_config(
        overrides={
            "bev_size_px": (240, 240),
            "bev_extent_m": (30.0, 30.0, 10.0, 40.0),
        }
    )

    rendered = render_candidate_bevs_attempt1_style(recording, candidate, tmp_path, config)

    assert len(rendered.bev_paths) == 1
    assert "bev_attempt1_style" in rendered.bev_paths[0]
    assert rendered.metadata["bev_renderer"] == "side-attempt1-style-v1"
    assert tmp_path.joinpath("bev_attempt1_style").is_dir()
