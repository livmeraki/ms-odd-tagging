from pathlib import Path

from ms_odd_tagging.experiments.lane_debug_v2.inferred_lane_tuner import (
    render_inferred_lane_tuner,
)


def test_inferred_lane_tuner_contains_live_controls_and_visual_candidates(tmp_path: Path):
    following = {
        "lane_geometry": [{
            "lane_id": "100",
            "centerline_lcs_m": [[0.0, 0.0], [5.0, 0.0]],
            "left_boundary_lcs_m": [[0.0, 1.5], [5.0, 1.5]],
            "right_boundary_lcs_m": [[0.0, -1.5], [5.0, -1.5]],
            "polygon_lcs_m": [[0.0, 1.5], [5.0, 1.5], [5.0, -1.5], [0.0, -1.5]],
        }],
        "continuous_lane_tracks": [{
            "track_id": "physical_track_0001",
            "member_lane_ids": ["100"],
            "centerline_lcs_m": [[-3.0, 0.0], [0.0, 0.0], [5.0, 0.0]],
            "pieces": [{
                "kind": "observed_ld",
                "lane_id": "100",
                "centerline_lcs_m": [[0.0, 0.0], [5.0, 0.0]],
                "polygon_lcs_m": [[0.0, 1.5], [5.0, 1.5], [5.0, -1.5], [0.0, -1.5]],
            }],
        }],
        "static_inferred_lanes": [{
            "static_inferred_lane_id": "static_route_1",
            "route_id": "route_1",
            "centerline_lcs_m": [[5.5, 0.0], [10.0, 0.0]],
            "left_boundary_lcs_m": [[5.5, 1.5], [10.0, 1.5]],
            "right_boundary_lcs_m": [[5.5, -1.5], [10.0, -1.5]],
            "polygon_lcs_m": [[5.5, 1.5], [10.0, 1.5], [10.0, -1.5], [5.5, -1.5]],
            "start_frame_index": 1,
            "end_frame_index": 5,
        }],
        "static_inferred_affiliation_debug": [{
            "static_inferred_lane_id": "static_route_1",
            "back_candidates": [{
                "track_id": "physical_track_0001",
                "track_endpoint_side": "end",
                "supporting_lane_id": "100",
                "supporting_lane_endpoint_side": "end",
                "center_endpoint_distance_m": 0.5,
                "left_boundary_endpoint_distance_m": 0.5,
                "right_boundary_endpoint_distance_m": 0.5,
                "longitudinal_m": 0.5,
                "lateral_error_m": 0.0,
                "heading_difference_deg": 0.0,
                "local_width_difference_m": 0.0,
                "curvature_difference_per_m": 0.0,
                "endpoint_inside_inferred_polygon": False,
                "score": 0.85,
            }],
            "front_candidates": [],
        }],
        "static_inferred_lane_debug": [{
            "static_inferred_lane_id": "static_route_1",
            "accepted": False,
            "rejection_reason": "incomplete_route_or_missing_track_endpoint",
        }],
    }
    out = tmp_path / "tuner.html"
    render_inferred_lane_tuner(following, out, "test_run", {})
    html = out.read_text(encoding="utf-8")
    assert "Inferred Lane Affiliation / Integration Tuner" in html
    assert "Max center endpoint distance" in html
    assert "Max boundary endpoint distance" in html
    assert "Minimum unique score margin" in html
    assert "BACK candidates" in html
    assert "FRONT candidates" in html
    assert "Rejected" in html
    assert "Boundary connections" in html
    assert "Support fragments" in html
    assert "physical_track_0001" in html
    assert '"tracks":' in html
    assert "candidate-track" in html
    assert "back-selected" in html
    assert "back-eligible" in html
    assert "candidate-rejected" in html
    assert "Download tuned JSON" in html
