"""Focused synthetic coverage for Phase 2B road-feature relations."""

from __future__ import annotations

import copy
import math

import pytest

from ms_odd_tagging.features.road_feature_relations import (
    build_road_feature_relations,
)
from ms_odd_tagging.tagger.rule_based.registry import (
    detect_events,
    events_overlapping_window,
    load_config,
)


def _roadmark(
    roadmark_id: str,
    class_name: str,
    x: float,
    *,
    y: float = 0.0,
    longitudinal_width: float = 2.0,
    lateral_width: float = 6.0,
    orientation: str = "across",
) -> dict:
    if orientation == "across":
        polygon = [
            [x - longitudinal_width / 2, y - lateral_width / 2, 0.0],
            [x + longitudinal_width / 2, y - lateral_width / 2, 0.0],
            [x + longitudinal_width / 2, y + lateral_width / 2, 0.0],
            [x - longitudinal_width / 2, y + lateral_width / 2, 0.0],
        ]
    else:
        polygon = [
            [x - lateral_width / 2, y - longitudinal_width / 2, 0.0],
            [x + lateral_width / 2, y - longitudinal_width / 2, 0.0],
            [x + lateral_width / 2, y + longitudinal_width / 2, 0.0],
            [x - lateral_width / 2, y + longitudinal_width / 2, 0.0],
        ]
    return {
        "roadmark_id": roadmark_id,
        "class": class_name,
        "subclass": None,
        "shape_type": "polygon",
        "points": [{"position_lcs_m": point} for point in polygon],
        "attributes": {},
        "ignored": False,
    }


def _recording(
    xs: list[float],
    *,
    speeds: list[float] | None = None,
    accelerations: list[float] | None = None,
    headings: list[float] | None = None,
    timestamps: list[float] | None = None,
    roadmarks: list[dict] | None = None,
    nearby: list[list[str]] | None = None,
) -> dict:
    count = len(xs)
    speeds = speeds or [5.0] * count
    accelerations = accelerations or [0.0] * count
    headings = headings or [0.0] * count
    timestamps = timestamps or [round(index * 0.1, 3) for index in range(count)]
    roadmarks = roadmarks or [_roadmark("cw1", "crosswalk", 10.0)]
    all_ids = [str(item["roadmark_id"]) for item in roadmarks]
    nearby = nearby or [all_ids] * count
    frames = []
    for index, (x, speed, acceleration, heading, timestamp) in enumerate(
        zip(xs, speeds, accelerations, headings, timestamps)
    ):
        frames.append(
            {
                "frame_index": index * 2 + 5,
                "time_since_start_s": timestamp,
                "ego": {
                    "position_lcs_m": [x, 0.0, 0.0],
                    "heading_lcs_rad": heading,
                    "speed_mps": speed,
                    "acceleration_mps2": acceleration,
                    "velocity_lcs_mps": [
                        speed * math.cos(heading),
                        speed * math.sin(heading),
                        0.0,
                    ],
                    "yaw_rate_radps": 0.0,
                },
                "ld": {"nearby_feature_ids": {"roadmarks": nearby[index]}},
            }
        )
    return {
        "recording_id": "synthetic",
        "frames": frames,
        "ld_feature_store": {"roadmarks": roadmarks},
    }


def _relations(recording: dict) -> dict:
    return build_road_feature_relations(
        recording, load_config()["road_feature_relations"]
    )


def _events(recording: dict):
    config = load_config()
    relations = build_road_feature_relations(
        recording, config["road_feature_relations"]
    )
    events, _ = detect_events(
        recording["frames"], config, road_feature_relations=relations
    )
    return events


def _states(payload: dict, track_id: str, key: str = "crosswalk_relations"):
    return [
        next(
            item["state"]
            for item in frame[key]
            if item["track_id"] == track_id
        )
        for frame in payload["frames"]
    ]


def test_crosswalk_visible_but_not_on_ego_path():
    payload = _relations(
        _recording([0, 1, 2], roadmarks=[_roadmark("cw1", "crosswalk", 10, y=20)])
    )
    assert set(_states(payload, "crosswalk:cw1")) == {"far"}


def test_approaching_crosswalk_is_internal_state_only():
    payload = _relations(_recording([-10, -8, -6]))
    assert "approaching" in _states(payload, "crosswalk:cw1")
    assert not any(event.scenario == "approaching_crosswalk" for event in _events(_recording([-10, -8, -6])))


def test_clean_crosswalk_traversal():
    events = _events(_recording(list(range(0, 18))))
    traversal = [event for event in events if event.scenario == "traversing_crosswalk"]
    assert len(traversal) == 1
    assert traversal[0].evidence["crossing_progress_m"] >= 2.0


def test_driving_parallel_to_crosswalk():
    payload = _relations(
        _recording(
            [10.0] * 8,
            headings=[math.pi / 2] * 8,
        )
    )
    assert "on" not in _states(payload, "crosswalk:cw1")


def test_one_frame_crosswalk_detection_loss_does_not_break_static_track():
    nearby = [["cw1"]] * 8
    nearby[3] = []
    payload = _relations(_recording(list(range(4, 12)), nearby=nearby))
    assert len(payload["tracks"]) == 1
    assert payload["frames"][3]["crosswalk_relations"][0]["observed_this_frame"] is False
    assert payload["frames"][3]["crosswalk_relations"][0]["relation_valid"] is True


def test_duplicate_crosswalk_detections_are_merged_strictly():
    payload = _relations(
        _recording(
            [0],
            roadmarks=[
                _roadmark("cw1", "crosswalk", 10),
                _roadmark("cw1_alias", "crosswalk", 10.1),
            ],
        )
    )
    assert len(payload["tracks"]) == 1
    assert len(payload["tracks"][0]["source_feature_ids"]) == 2


def test_two_nearby_crosswalks_remain_distinct():
    payload = _relations(
        _recording(
            [0],
            roadmarks=[
                _roadmark("cw1", "crosswalk", 10),
                _roadmark("cw2", "crosswalk", 14),
            ],
        )
    )
    assert len(payload["tracks"]) == 2


def test_ego_stopping_before_crosswalk():
    speeds = [5, 5, 4, 3, 2, 1, 0.4, 0.2, 0.1, 0.1, 0.1]
    accelerations = [0, 0, -1, -1, -1, -1, -1, -1, 0, 0, 0]
    events = _events(
        _recording(
            [0, 1, 2, 3, 4, 5, 5.5, 5.8, 6, 6, 6],
            speeds=speeds,
            accelerations=accelerations,
        )
    )
    assert any(event.scenario == "stopping_at_crosswalk" for event in events)


def test_ego_stopping_too_far_before_crosswalk():
    events = _events(
        _recording(
            [-10] * 8,
            speeds=[3, 2, 1, 0.4, 0.2, 0.1, 0.1, 0.1],
            accelerations=[-1] * 5 + [0, 0, 0],
        )
    )
    assert not any(event.scenario == "stopping_at_crosswalk" for event in events)


def test_ego_stopping_after_crosswalk():
    events = _events(
        _recording(
            [16] * 8,
            speeds=[3, 2, 1, 0.4, 0.2, 0.1, 0.1, 0.1],
            accelerations=[-1] * 5 + [0, 0, 0],
        )
    )
    assert not any(event.scenario == "stopping_at_crosswalk" for event in events)


def test_ego_stationary_before_crosswalk():
    events = _events(_recording([6] * 7, speeds=[0.1] * 7))
    stationary = [event for event in events if event.scenario == "stationary_at_crosswalk"]
    assert stationary and stationary[0].evidence["stationary_relation"] == "before"


def test_ego_stationary_on_crosswalk():
    events = _events(_recording([10] * 7, speeds=[0.1] * 7))
    stationary = [event for event in events if event.scenario == "stationary_at_crosswalk"]
    assert stationary and stationary[0].evidence["stationary_relation"] == "on"


def test_ego_accelerating_from_rest_before_crosswalk():
    events = _events(
        _recording(
            [6, 6, 6.1, 6.3, 6.6, 7.0],
            speeds=[0.1, 0.2, 0.5, 0.9, 1.3, 1.7],
            accelerations=[0, 0.6, 0.8, 0.8, 0.7, 0.6],
        )
    )
    assert any(event.scenario == "accelerating_at_crosswalk" for event in events)


def test_ego_accelerating_immediately_after_crosswalk():
    events = _events(
        _recording(
            [14, 14, 14.1, 14.3, 14.6, 15.0],
            speeds=[0.1, 0.2, 0.5, 0.9, 1.3, 1.7],
            accelerations=[0, 0.6, 0.8, 0.8, 0.7, 0.6],
        )
    )
    accelerating = [event for event in events if event.scenario == "accelerating_at_crosswalk"]
    assert accelerating
    assert accelerating[0].evidence["acceleration_began_relation"] in {"leaving", "passed", "on"}


def test_stopline_associated_with_crosswalk():
    payload = _relations(
        _recording(
            [0],
            roadmarks=[
                _roadmark("cw1", "crosswalk", 10),
                _roadmark("sl1", "stopline", 7, longitudinal_width=0.2),
            ],
        )
    )
    association = payload["stopline_crosswalk_associations"][0]
    assert association["valid"] is True
    assert association["crosswalk_track_id"] == "crosswalk:cw1"


def test_unrelated_stopline_near_crosswalk_is_not_associated():
    payload = _relations(
        _recording(
            [0],
            roadmarks=[
                _roadmark("cw1", "crosswalk", 10),
                _roadmark("sl1", "stopline", 7, orientation="parallel"),
            ],
        )
    )
    assert payload["stopline_crosswalk_associations"][0]["valid"] is False


def test_stopline_overlap_emits_crosswalk_stopline_event():
    roadmarks = [
        _roadmark("cw1", "crosswalk", 10),
        _roadmark("sl1", "stopline", 7, longitudinal_width=0.2),
    ]
    events = _events(_recording([4.7, 4.8, 4.9], roadmarks=roadmarks))
    assert any(event.scenario == "on_stopline_crosswalk" for event in events)


def test_stopline_crossing_without_stopping_still_emits():
    roadmarks = [
        _roadmark("cw1", "crosswalk", 10),
        _roadmark("sl1", "stopline", 7, longitudinal_width=0.2),
    ]
    events = _events(_recording([3, 4, 5, 6, 7, 8, 9], roadmarks=roadmarks))
    assert any(event.scenario == "on_stopline_crosswalk" for event in events)


def test_irregular_timestamps_preserve_original_identity():
    timestamps = [0.0, 0.08, 0.21, 0.37, 0.52, 0.71, 0.9, 1.11, 1.31]
    recording = _recording(list(range(6, 15)), timestamps=timestamps)
    events = _events(recording)
    assert all(
        event.start_frame in {frame["frame_index"] for frame in recording["frames"]}
        and event.end_timestamp_s in timestamps
        for event in events
    )


def test_event_spanning_overlapping_windows_keeps_one_physical_identity():
    traversal = next(
        event
        for event in _events(_recording(list(range(0, 18))))
        if event.scenario == "traversing_crosswalk"
    )
    first = events_overlapping_window([traversal], 5, 25)
    second = events_overlapping_window([traversal], 15, 39)
    assert first[0]["evidence"]["road_feature_event_id"] == second[0]["evidence"]["road_feature_event_id"]


def test_missing_od_frames_do_not_bridge_invalid_ego_pose():
    recording = _recording([0, 1, 2])
    recording["frames"][1]["ego"]["position_lcs_m"] = [None, None, None]
    payload = _relations(recording)
    states = _states(payload, "crosswalk:cw1")
    assert states[1] == "unknown"


def test_empty_input():
    recording = {"recording_id": "empty", "frames": [], "ld_feature_store": {"roadmarks": []}}
    assert _relations(recording)["frames"] == []
    assert _events(recording) == []

