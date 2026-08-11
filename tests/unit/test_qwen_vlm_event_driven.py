from __future__ import annotations

from ms_odd_tagging.qwen_vlm_poc.config import load_config
from ms_odd_tagging.qwen_vlm_poc.evidence import _keep_event_driven_waiting_bev
from ms_odd_tagging.qwen_vlm_poc.event_driven import generate_event_driven_candidates
from ms_odd_tagging.qwen_vlm_poc.models import CandidateWindow
from ms_odd_tagging.qwen_vlm_poc.scene_merge import merge_waiting_scene_candidates


def _frame(index: int, *, speed: float = 8.0, accel: float = 0.0, pedestrian: dict | None = None):
    return {
        "frame_index": index,
        "time_since_start_s": index * 0.1,
        "ego": {
            "position_lcs_m": [index * 0.1, 0.0, 0.0],
            "heading_lcs_rad": 0.0,
            "speed_mps": speed,
            "acceleration_mps2": accel,
        },
        "objects": [pedestrian] if pedestrian else [],
        "ld": {"nearby_feature_ids": {"lane_lines": [], "roadmarks": []}},
    }


def _pedestrian(index: int, object_id: str = "ped-1", lateral: float = 2.0) -> dict:
    return {
        "object_id": object_id,
        "class": "pedestrian",
        "position_lcs_m": [10.0 + index * 0.02, lateral, 0.0],
        "position_ego_m": {"longitudinal": 10.0, "lateral": lateral},
        "relative_velocity_ego_mps": {"longitudinal": 0.0, "lateral": -0.4},
    }


def _recording(frames):
    return {"recording_id": "rec-event", "frames": frames, "ld_feature_store": {"points": []}}


def _event_candidate() -> CandidateWindow:
    return CandidateWindow(
        candidate_id="rec-event_waiting_for_pedestrian_to_cross_ped-1_000020_000030",
        recording_id="rec-event",
        scenario="waiting_for_pedestrian_to_cross",
        start_frame=20,
        end_frame=30,
        start_timestamp_s=2.0,
        end_timestamp_s=3.0,
        evidence=[],
        selected_frame_indices=[20, 25, 30],
        primary_object_ids=["ped-1"],
        metadata={"candidate_strategy": "event-driven"},
    )


def _candidate(name: str, start: int, end: int, raw_start: int, raw_end: int, ped: str) -> CandidateWindow:
    return CandidateWindow(
        candidate_id=name,
        recording_id="rec-event",
        scenario="waiting_for_pedestrian_to_cross",
        start_frame=start,
        end_frame=end,
        start_timestamp_s=start * 0.1,
        end_timestamp_s=end * 0.1,
        evidence=[],
        selected_frame_indices=[],
        primary_object_ids=[ped],
        metadata={
            "candidate_strategy": "event-driven",
            "raw_trigger_start_frame": raw_start,
            "raw_trigger_end_frame": raw_end,
        },
    )


def test_waiting_event_candidate_uses_trigger_bounds_plus_context_not_fixed_window():
    frames = []
    for index in range(60):
        ped = _pedestrian(index) if 20 <= index <= 30 else None
        speed = 0.4 if 23 <= index <= 34 else 8.0
        accel = -0.8 if 22 <= index <= 25 else 0.0
        frames.append(_frame(index, speed=speed, accel=accel, pedestrian=ped))

    config = load_config(
        overrides={
            "minimum_duration_s": 0.5,
            "maximum_inactive_gap_s": 0.3,
            "event_candidate_pre_context_s": 0.5,
            "event_candidate_post_context_s": 0.7,
            "event_response_link_s": 0.5,
            "max_bev_images": 6,
        }
    )
    candidates = generate_event_driven_candidates(
        _recording(frames), "waiting_for_pedestrian_to_cross", config
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.metadata["candidate_strategy"] == "event-driven"
    assert candidate.metadata["raw_trigger_start_frame"] == 20
    assert candidate.metadata["raw_trigger_end_frame"] == 30
    assert candidate.start_frame == 15
    assert candidate.end_frame == 37
    assert candidate.end_frame - candidate.start_frame != 50
    assert candidate.primary_object_ids == ["ped-1"]
    assert len(candidate.selected_frame_indices) <= 6
    assert 20 in candidate.selected_frame_indices
    assert "strongest_conflict" in candidate.metadata["landmark_roles"]
    assert "strongest_ego_response" in candidate.metadata["landmark_roles"]


def test_waiting_event_candidate_requires_temporally_linked_ego_response():
    frames = [
        _frame(index, speed=8.0, accel=0.0, pedestrian=_pedestrian(index) if 20 <= index <= 30 else None)
        for index in range(60)
    ]
    config = load_config(
        overrides={
            "minimum_duration_s": 0.5,
            "maximum_inactive_gap_s": 0.3,
            "event_candidate_pre_context_s": 0.5,
            "event_candidate_post_context_s": 0.5,
            "event_response_link_s": 0.5,
        }
    )
    assert generate_event_driven_candidates(
        _recording(frames), "waiting_for_pedestrian_to_cross", config
    ) == []


def test_waiting_event_candidate_bridges_short_conflict_dropout():
    frames = []
    for index in range(60):
        active = 20 <= index <= 32 and index not in {25, 26}
        ped = _pedestrian(index) if active else None
        speed = 0.3 if 22 <= index <= 34 else 8.0
        frames.append(_frame(index, speed=speed, accel=-0.5 if index == 22 else 0.0, pedestrian=ped))

    config = load_config(
        overrides={
            "minimum_duration_s": 0.5,
            "maximum_inactive_gap_s": 0.35,
            "event_candidate_pre_context_s": 0.2,
            "event_candidate_post_context_s": 0.2,
            "event_response_link_s": 0.5,
        }
    )
    candidates = generate_event_driven_candidates(
        _recording(frames), "waiting_for_pedestrian_to_cross", config
    )
    assert len(candidates) == 1
    assert candidates[0].metadata["raw_trigger_start_frame"] == 20
    assert candidates[0].metadata["raw_trigger_end_frame"] == 32


def test_event_driven_waiting_bev_keeps_neutral_selected_frames():
    config = load_config()
    candidate = _event_candidate()

    assert _keep_event_driven_waiting_bev(
        _frame(20, speed=8.0, accel=0.0), candidate, config
    )
    assert _keep_event_driven_waiting_bev(
        _frame(21, speed=8.0, accel=-0.8), candidate, config
    )
    assert _keep_event_driven_waiting_bev(
        _frame(22, speed=4.0, accel=0.0), candidate, config
    )


def test_scene_merge_uses_future_path_and_neutral_landmarks():
    frames = []
    for index in range(100):
        ped = None
        if 20 <= index <= 36:
            lateral = 4.0 - 0.25 * (index - 20)
            ped = _pedestrian(index, "ped-1", lateral)
        speed = 0.2 if index == 33 else 8.0
        frames.append(_frame(index, speed=speed, pedestrian=ped))
    recording = _recording(frames)
    config = load_config(overrides={"event_scene_merge_gap_s": 0.5, "max_bev_images": 6})

    first = _candidate("first", 10, 40, 20, 30, "ped-1")
    second = _candidate("second", 18, 48, 28, 36, "ped-2")

    merged = merge_waiting_scene_candidates(recording, [first, second], config)
    assert len(merged) == 1
    scene = merged[0]
    assert scene.primary_object_ids == ["ped-1", "ped-2"]
    assert scene.metadata["source_candidate_count"] == 2
    assert scene.metadata["scene_merge_policy"] == "pairwise_raw_interval_proximity"
    assert scene.metadata["vlm_input_mode"] == "bev_plus_neutral_future_path_and_motion_measurements"
    assert scene.metadata["frame_selection_strategy"] == "neutral_event_landmarks"
    assert scene.metadata["frame_selection_landmarks"]["minimum_ego_speed"] == 33
    assert 33 in scene.selected_frame_indices
    assert 19 in scene.selected_frame_indices
    assert 20 in scene.selected_frame_indices
    assert 36 in scene.selected_frame_indices
    assert [item["frame"] for item in scene.metadata["ego_measurements"]] == scene.selected_frame_indices
    assert [item["frame"] for item in scene.metadata["pedestrian_measurements"]] == scene.selected_frame_indices
    assert [item["frame"] for item in scene.metadata["ego_future_paths"]] == scene.selected_frame_indices
    assert all(item["corridor_half_width_m"] == 1.5 for item in scene.metadata["ego_future_paths"])
    assert all(item["points"] for item in scene.metadata["ego_future_paths"])
    assert "landmark_roles" not in scene.metadata
    assert "ego_response_frames" not in scene.metadata
    assert len(scene.evidence) == 1
    assert scene.evidence[0].kind == "bev_sequence"


def test_scene_merge_does_not_transitively_chain_unrelated_pedestrians():
    frames = [_frame(index) for index in range(80)]
    config = load_config(overrides={"event_scene_merge_gap_s": 0.0, "max_bev_images": 6})
    candidates = [
        _candidate("a", 5, 25, 10, 20, "ped-a"),
        _candidate("b", 14, 35, 19, 30, "ped-b"),
        _candidate("c", 24, 45, 29, 40, "ped-c"),
    ]
    scenes = merge_waiting_scene_candidates(_recording(frames), candidates, config)
    assert len(scenes) == 2
    assert scenes[0].primary_object_ids == ["ped-a", "ped-b"]
    assert scenes[1].primary_object_ids == ["ped-c"]


def test_event_driven_strategy_falls_back_for_other_scenarios():
    frames = [_frame(index) for index in range(20)]
    config = load_config()
    assert generate_event_driven_candidates(
        _recording(frames), "starting_u_turn", config
    ) == []
