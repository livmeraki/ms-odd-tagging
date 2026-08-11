from __future__ import annotations

import math

from ms_odd_tagging.qwen_vlm_poc.future_path import distance_to_polyline, future_ego_path


def _frame(index: int, x: float, y: float, heading: float = 0.0):
    return {
        "frame_index": index,
        "time_since_start_s": index * 0.1,
        "ego": {
            "position_lcs_m": [x, y, 0.0],
            "heading_lcs_rad": heading,
            "speed_mps": 1.0,
        },
        "objects": [],
    }


def test_future_ego_path_preserves_curve_in_selected_frame_coordinates():
    frames = {
        0: _frame(0, 0.0, 0.0),
        1: _frame(1, 1.0, 0.0),
        2: _frame(2, 2.0, 0.5),
        3: _frame(3, 3.0, 1.5),
    }
    geometry = future_ego_path(frames, 0, horizon_s=1.0, max_points=12)

    assert geometry["coordinate_frame"] == "selected_frame_ego_centered_heading_aligned"
    assert geometry["corridor_half_width_m"] == 1.5
    assert geometry["points"][0]["longitudinal_m"] == 0.0
    assert geometry["points"][0]["lateral_m"] == 0.0
    assert geometry["points"][-1]["longitudinal_m"] == 3.0
    assert geometry["points"][-1]["lateral_m"] == 1.5
    assert any(abs(row["lateral_m"]) > 0.1 for row in geometry["points"][1:])


def test_future_ego_path_rotates_with_anchor_heading():
    frames = {
        0: _frame(0, 0.0, 0.0, heading=math.pi / 2.0),
        1: _frame(1, 0.0, 1.0, heading=math.pi / 2.0),
        2: _frame(2, -1.0, 2.0, heading=math.pi / 2.0),
    }
    geometry = future_ego_path(frames, 0, horizon_s=1.0)

    assert geometry["points"][1]["longitudinal_m"] == 1.0
    assert abs(geometry["points"][1]["lateral_m"]) < 1e-6
    assert geometry["points"][2]["longitudinal_m"] == 2.0
    assert geometry["points"][2]["lateral_m"] == 1.0


def test_distance_to_polyline_uses_curved_path_not_heading_centerline():
    path = [(0.0, 0.0), (5.0, 2.0), (10.0, 6.0)]
    pedestrian = (9.0, 5.5)
    distance = distance_to_polyline(pedestrian, path)

    assert distance is not None
    assert distance < 1.0
    assert abs(pedestrian[1]) > 5.0
