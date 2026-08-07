from __future__ import annotations

import copy
from copy import deepcopy

from ms_odd_tagging.features.ego_motion import extract_ego_motion_features
from ms_odd_tagging.features.object_relations import build_object_relations
from ms_odd_tagging.features.road_feature_relations import build_road_feature_relations
from ms_odd_tagging.features.traffic_light_context import build_traffic_light_context
from ms_odd_tagging.features.traffic_relations import build_traffic_relations
from ms_odd_tagging.tagger.rule_based.registry import detect_recording_events, load_config
from ms_odd_tagging.tagger.rule_based.traffic_light_behaviors import (
    TrafficLightBehaviorDetector,
)


def _traffic_light(object_id: str, x: float, y: float = 1.0) -> dict:
    return {
        "object_id": object_id,
        "class": "traffic_light_car",
        "annotation_type": "static",
        "position_lcs_m": [x, y, 0.0],
        "dimensions_m": {"length": 0.5, "width": 0.5, "height": 2.0},
    }


def _car(object_id: str, x: float, y: float = 0.0) -> dict:
    return {
        "object_id": object_id,
        "class": "car",
        "annotation_type": "dynamic",
        "position_lcs_m": [x, y, 0.0],
        "dimensions_m": {"length": 4.5, "width": 1.8, "height": 1.6},
        "heading_relative_rad": 0.0,
        "velocity_lcs_mps": [0.0, 0.0, 0.0],
        "velocity_source": "measured",
    }


def _stopline(stopline_id: str, x: float, y: float = 0.0) -> dict:
    return {
        "roadmark_id": stopline_id,
        "class": "stopline",
        "shape_type": "polygon",
        "points": [
            {"position_lcs_m": [x - 0.2, y - 3.0, 0.0]},
            {"position_lcs_m": [x + 0.2, y - 3.0, 0.0]},
            {"position_lcs_m": [x + 0.2, y + 3.0, 0.0]},
            {"position_lcs_m": [x - 0.2, y + 3.0, 0.0]},
        ],
        "attributes": {},
        "ignored": False,
    }


def _frame(
    index: int,
    ego_x: float,
    speed: float,
    acceleration: float,
    objects: list[dict],
) -> dict:
    return {
        "frame_index": index,
        "timestamp_unix_s": float(index),
        "time_since_start_s": round(index * 0.1, 6),
        "ego": {
            "position_lcs_m": [ego_x, 0.0, 0.0],
            "heading_lcs_rad": 0.0,
            "speed_mps": speed,
            "acceleration_mps2": acceleration,
            "velocity_lcs_mps": [speed, 0.0, 0.0],
            "yaw_rate_radps": 0.0,
        },
        "objects": [copy.deepcopy(item) for item in objects],
        "ld": {"nearby_feature_ids": {"roadmarks": ["sl1"]}},
    }


def _recording(
    *,
    speeds: list[float],
    accelerations: list[float],
    objects_by_frame: list[list[dict]] | None = None,
    ego_xs: list[float] | None = None,
    stoplines: list[dict] | None = None,
) -> dict:
    objects_by_frame = objects_by_frame or [
        [_traffic_light("tl1", 11.0)] for _ in speeds
    ]
    ego_xs = ego_xs or [0.0] * len(speeds)
    return {
        "recording_id": "synthetic-tl-behavior",
        "frames": [
            _frame(index, ego_xs[index], speeds[index], accelerations[index], objects)
            for index, objects in enumerate(objects_by_frame)
        ],
        "ld_feature_store": {
            "roadmarks": stoplines if stoplines is not None else [_stopline("sl1", 10.0)]
        },
    }


def _intersection_context(frames: list[dict], *, active: bool = True) -> dict[int, dict]:
    return {
        frame["frame_index"]: {
            "topology_class": "x-intersection" if active else "normal",
            "topology_subtype": "x-intersection" if active else "normal",
            "ego_inside_topology_polygon": False,
            "distance_to_topology_polygon_m": 5.0,
            "topology_confidence": 0.8 if active else 0.0,
            "active_is_intersection": False,
            "component_geometry_confidence": 0.8 if active else 0.0,
        }
        for frame in frames
    }


def _traffic_light_context(recording: dict, *, active_intersection: bool = True) -> dict:
    config = deepcopy(load_config())
    features = extract_ego_motion_features(
        recording["frames"],
        max_sample_gap_s=config["feature_extraction"]["max_sample_gap_s"],
        heading_change_horizon_s=config["feature_extraction"]["heading_change_horizon_s"],
        jerk_mode=config["jerk"]["calculation_mode"],
    )
    frame_context = _intersection_context(
        recording["frames"], active=active_intersection
    )
    roads = build_road_feature_relations(recording, config["road_feature_relations"])
    objects = build_object_relations(recording, config["object_relations"])
    traffic = build_traffic_relations(
        recording["frames"],
        features,
        objects,
        config,
        frame_context=frame_context,
    )
    return build_traffic_light_context(
        recording,
        features,
        roads,
        traffic,
        config,
        frame_context=frame_context,
    )


def _events(recording: dict, *, active_intersection: bool = True):
    config = deepcopy(load_config())
    context = _traffic_light_context(
        recording, active_intersection=active_intersection
    )
    return TrafficLightBehaviorDetector().detect(
        recording["frames"],
        config,
        context,
    )


def _scenario(events, name):
    return [event for event in events if event.scenario == name]


def test_all_six_direct_traffic_light_behavior_tags():
    cases = [
        (
            [2.0] * 4,
            [0.8] * 4,
            True,
            "accelerating_at_traffic_light_with_lead",
        ),
        (
            [2.0] * 4,
            [0.8] * 4,
            False,
            "accelerating_at_traffic_light_without_lead",
        ),
        (
            [0.0] * 4,
            [0.0] * 4,
            True,
            "stationary_at_traffic_light_with_lead",
        ),
        (
            [0.0] * 4,
            [0.0] * 4,
            False,
            "stationary_at_traffic_light_without_lead",
        ),
        (
            [3.0] * 4,
            [-0.8] * 4,
            True,
            "stopping_at_traffic_light_with_lead",
        ),
        (
            [3.0] * 4,
            [-0.8] * 4,
            False,
            "stopping_at_traffic_light_without_lead",
        ),
    ]
    for speeds, accelerations, has_lead, scenario in cases:
        objects = [_traffic_light("tl1", 11.0)]
        if has_lead:
            objects.append(_car("lead", 8.0))
        recording = _recording(
            speeds=speeds,
            accelerations=accelerations,
            objects_by_frame=[[copy.deepcopy(item) for item in objects] for _ in speeds],
        )
        events = _events(recording)
        assert _scenario(events, scenario), scenario


def test_unrelated_nearby_traffic_light_does_not_tag():
    recording = _recording(
        speeds=[2.0] * 4,
        accelerations=[0.8] * 4,
        objects_by_frame=[[_traffic_light("tl-side", 11.0, y=25.0)] for _ in range(4)],
    )
    assert not _events(recording)


def test_motion_outside_traffic_light_context_does_not_tag():
    recording = _recording(speeds=[2.0] * 4, accelerations=[0.8] * 4)
    assert not _events(recording, active_intersection=False)


def test_adjacent_lane_vehicle_is_rejected_as_lead_for_without_variant():
    recording = _recording(
        speeds=[2.0] * 4,
        accelerations=[0.8] * 4,
        objects_by_frame=[
            [_traffic_light("tl1", 11.0), _car("side", 8.0, y=5.0)]
            for _ in range(4)
        ],
    )
    events = _events(recording)
    assert _scenario(events, "accelerating_at_traffic_light_without_lead")
    assert not _scenario(events, "accelerating_at_traffic_light_with_lead")


def test_with_and_without_lead_are_mutually_exclusive():
    recording = _recording(
        speeds=[0.0] * 4,
        accelerations=[0.0] * 4,
        objects_by_frame=[
            [_traffic_light("tl1", 11.0), _car("lead", 8.0)]
            for _ in range(4)
        ],
    )
    events = _events(recording)
    assert _scenario(events, "stationary_at_traffic_light_with_lead")
    assert not _scenario(events, "stationary_at_traffic_light_without_lead")


def test_brief_lead_disappearance_does_not_create_without_lead_flicker():
    objects = [[_traffic_light("tl1", 11.0), _car("lead", 8.0)] for _ in range(5)]
    objects[2] = [_traffic_light("tl1", 11.0)]
    recording = _recording(
        speeds=[2.0] * 5,
        accelerations=[0.8] * 5,
        objects_by_frame=objects,
    )
    events = _events(recording)
    with_lead = _scenario(events, "accelerating_at_traffic_light_with_lead")
    assert len(with_lead) == 1
    assert with_lead[0].start_frame == 0
    assert with_lead[0].end_frame == 4
    assert not _scenario(events, "accelerating_at_traffic_light_without_lead")


def test_stopline_passed_transition_suppresses_direct_behavior_tag():
    recording = _recording(
        speeds=[2.0] * 5,
        accelerations=[0.8] * 5,
        ego_xs=[0.0, 9.7, 10.0, 13.0, 16.0],
    )
    context = _traffic_light_context(recording)
    relations = [frame["stopline"]["relation"] for frame in context["frames"]]
    assert "before_stopline" in relations
    assert "on_stopline" in relations
    assert "passed_stopline" in relations
    events = TrafficLightBehaviorDetector().detect(
        recording["frames"], deepcopy(load_config()), context
    )
    assert events
    assert all(event.end_frame < 4 for event in events)


def test_one_frame_traffic_light_motion_spike_is_rejected():
    recording = _recording(
        speeds=[2.0] * 5,
        accelerations=[0.0, 0.0, 0.8, 0.0, 0.0],
    )
    assert not _events(recording)


def test_detect_recording_events_keeps_phase1_context_without_rule_based_tl_tags():
    recording = _recording(speeds=[2.0] * 4, accelerations=[0.8] * 4)
    for frame in recording["frames"]:
        frame.update(
            {
                "topology_class": "x-intersection",
                "topology_subtype": "x-intersection",
                "ego_inside_topology_polygon": False,
                "distance_to_topology_polygon_m": 5.0,
                "topology_confidence": 0.8,
                "active_is_intersection": False,
                "component_geometry_confidence": 0.8,
            }
        )
    events, quality = detect_recording_events(recording)
    assert quality["traffic_light_context"]["traffic_light_intersection_frame_count"] == 4
    assert not _scenario(events, "accelerating_at_traffic_light_without_lead")
