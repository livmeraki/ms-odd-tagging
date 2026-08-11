from __future__ import annotations

from ms_odd_tagging.qwen_vlm_poc.event_driven import _pedestrian_parallel_to_ego_path


def _frame(index: int, pedestrian_xy: tuple[float, float] | None, heading: float = 0.0):
    objects = []
    if pedestrian_xy is not None:
        objects.append(
            {
                "object_id": "ped-1",
                "class": "pedestrian",
                "position_lcs_m": [pedestrian_xy[0], pedestrian_xy[1], 0.0],
            }
        )
    return {
        "frame_index": index,
        "time_since_start_s": index * 0.1,
        "ego": {
            "position_lcs_m": [index * 0.1, 0.0, 0.0],
            "heading_lcs_rad": heading,
            "speed_mps": 2.0,
        },
        "objects": objects,
    }


def test_rejects_clear_same_direction_parallel_pedestrian_track():
    frames = [
        _frame(index, (index * 0.25, 3.0))
        for index in range(12)
    ]
    assert _pedestrian_parallel_to_ego_path(frames, "ped-1") is True


def test_rejects_clear_opposite_direction_parallel_pedestrian_track():
    frames = [
        _frame(index, (5.0 - index * 0.25, 3.0))
        for index in range(12)
    ]
    assert _pedestrian_parallel_to_ego_path(frames, "ped-1") is True


def test_keeps_crossing_pedestrian_track():
    frames = [
        _frame(index, (8.0, 3.0 - index * 0.25))
        for index in range(12)
    ]
    assert _pedestrian_parallel_to_ego_path(frames, "ped-1") is False


def test_keeps_short_or_stationary_track_as_ambiguous():
    stationary = [_frame(index, (8.0, 2.0)) for index in range(12)]
    short = [_frame(index, (8.0 + index * 0.05, 2.0)) for index in range(12)]
    assert _pedestrian_parallel_to_ego_path(stationary, "ped-1") is False
    assert _pedestrian_parallel_to_ego_path(short, "ped-1") is False
