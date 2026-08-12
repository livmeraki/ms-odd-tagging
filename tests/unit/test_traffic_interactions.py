from __future__ import annotations

import copy
from copy import deepcopy

from ms_odd_tagging.features.ego_motion import extract_ego_motion_features
from ms_odd_tagging.features.object_path_crossing_relations import build_object_path_crossing_relations
from ms_odd_tagging.features.object_relations import build_object_relations
from ms_odd_tagging.features.pedestrian_crosswalk_relations import build_pedestrian_crosswalk_relations
from ms_odd_tagging.features.road_feature_relations import build_road_feature_relations
from ms_odd_tagging.features.traffic_relations import build_traffic_relations
from ms_odd_tagging.tagger.rule_based.registry import (
    EXPLICITLY_EXCLUDED_SCENARIOS,
    RULE_BASED_SCENARIOS,
    detect_events,
    detector_summary,
    load_config,
)


def _object(
    object_id: str,
    class_name: str,
    x: float,
    y: float,
    *,
    length: float = 4.5,
    width: float = 1.8,
    velocity=(0.0, 0.0),
    annotation_type: str = "dynamic",
    subclass=None,
) -> dict:
    return {
        "object_id": object_id,
        "class": class_name,
        "subclass": subclass,
        "annotation_type": annotation_type,
        "position_lcs_m": [x, y, 0.0],
        "dimensions_m": {"length": length, "width": width, "height": 1.6},
        "heading_relative_rad": 0.0,
        "velocity_lcs_mps": [velocity[0], velocity[1], 0.0],
        "velocity_source": "measured",
    }


def _frames(speeds, objects_by_frame, *, accelerations=None, crossing_frame=None):
    accelerations = accelerations or [0.0] * len(speeds)
    frames = []
    for index, speed in enumerate(speeds):
        frames.append(
            {
                "frame_index": index,
                "time_since_start_s": round(index * 0.1, 6),
                "ego": {
                    "position_lcs_m": [0.0, 0.3 if crossing_frame is not None and index >= crossing_frame else 0.0, 0.0],
                    "heading_lcs_rad": 0.0,
                    "speed_mps": speed,
                    "acceleration_mps2": accelerations[index],
                    "velocity_lcs_mps": [speed, 0.0, 0.0],
                    "yaw_rate_radps": 0.0,
                },
                "objects": [copy.deepcopy(item) for item in objects_by_frame[index]],
            }
        )
    return frames


def _repeat(objects, count=8):
    return [[copy.deepcopy(item) for item in objects] for _ in range(count)]


def _crossing_pedestrian_track(
    object_id: str = "ped",
    *,
    x: float = 10.0,
    start_y: float = 7.0,
    step_y: float = -1.0,
    count: int = 15,
):
    return [
        [
            _object(
                object_id,
                "pedestrian",
                x,
                start_y + index * step_y,
                length=0.5,
                width=0.5,
                velocity=(0.0, step_y / 0.1),
            )
        ]
        for index in range(count)
    ]


def _lane_context(lanes, *, direction="left"):
    result = {}
    source, target = "lane-a", "lane-b"
    for index, lane in enumerate(lanes):
        item = {
            "logical_lane_id": lane,
            "left_logical_lane_id": target if lane == source and direction == "left" else source if lane == target and direction == "right" else None,
            "right_logical_lane_id": target if lane == source and direction == "right" else source if lane == target and direction == "left" else None,
            "topology_class": "normal",
            "topology_subtype": "normal",
            "ego_inside_topology_polygon": False,
            "distance_to_topology_polygon_m": 5.0,
            "topology_confidence": 0.0,
            "active_is_intersection": False,
            "left_boundary": {
                "edge_id": "lane-a-left",
                "points_lcs_m": [[-100.0, 0.1], [100.0, 0.1]],
                "attributes": {"source_kind": "lane_line", "intersection": False},
            },
            "component_geometry_confidence": 0.0,
        }
        result[index] = item
    return result


def _events(frames, *, frame_context=None, pedestrian_crosswalk=None):
    config = deepcopy(load_config())
    features = extract_ego_motion_features(
        frames,
        max_sample_gap_s=config["feature_extraction"]["max_sample_gap_s"],
        heading_change_horizon_s=config["feature_extraction"]["heading_change_horizon_s"],
        jerk_mode=config["jerk"]["calculation_mode"],
    )
    object_relations = build_object_relations(frames if isinstance(frames, dict) else {"recording_id": "synthetic", "frames": frames}, config["object_relations"])
    base_events, _ = detect_events(
        frames,
        config,
        frame_context=frame_context,
        object_relations=object_relations,
    )
    lane_changes = [event for event in base_events if event.scenario == "changing_lane"]
    pedestrian_payload = pedestrian_crosswalk
    crossing_settings = {
        **config["object_path_crossing_interactions"],
        "maximum_plausible_object_speed_mps": config["object_relations"]["maximum_physically_plausible_object_speed_mps"],
    }
    crossing_payload = build_object_path_crossing_relations(
        {"recording_id": "synthetic", "frames": frames},
        object_relations,
        crossing_settings,
    )
    traffic = build_traffic_relations(
        frames,
        features,
        object_relations,
        config,
        frame_context=frame_context,
        lane_change_events=lane_changes,
        pedestrian_crosswalk_relations=pedestrian_payload,
        object_path_crossing_relations=crossing_payload,
    )
    events, _ = detect_events(
        frames,
        config,
        frame_context=frame_context,
        object_relations=object_relations,
        traffic_relations=traffic,
    )
    return events


def _scenario(events, name):
    return [event for event in events if event.scenario == name]


def test_following_lane_with_slow_lead_positive_and_normal_lead_negative():
    slow = _object("lead", "car", 12.0, 0.0, velocity=(2.0, 0.0))
    events = _events(_frames([8.0] * 8, _repeat([slow])))
    event = _scenario(events, "following_lane_with_slow_lead")[0]
    assert event.evidence["lead_object_id"] == "object:lead"
    assert event.evidence["relative_speed_mps"] < 0

    normal = _object("lead", "car", 12.0, 0.0, velocity=(7.5, 0.0))
    assert not _scenario(_events(_frames([8.0] * 8, _repeat([normal]))), "following_lane_with_slow_lead")


def test_slow_lead_missing_velocity_is_unknown_not_false_evidence():
    lead = _object("lead", "car", 12.0, 0.0, velocity=(2.0, 0.0))
    lead["velocity_lcs_mps"] = None
    assert not _scenario(_events(_frames([8.0] * 8, _repeat([lead]))), "following_lane_with_slow_lead")


def test_slow_lead_short_spike_rejected():
    lead = _object("lead", "car", 12.0, 0.0, velocity=(1.0, 0.0))
    objects = [[] for _ in range(8)]
    objects[3] = [lead]
    assert not _scenario(_events(_frames([8.0] * 8, objects)), "following_lane_with_slow_lead")


def test_lane_change_with_lead_uses_target_lane_not_current_lane():
    target_lead = _object("lead", "car", 12.0, 3.5, velocity=(9.0, 0.0))
    current_lead = _object("current", "car", 10.0, 0.0, velocity=(9.0, 0.0))
    lane_ids = ["lane-a"] * 15 + ["lane-b"] * 15
    frames = _frames([10.0] * 30, _repeat([target_lead], 30), crossing_frame=15)
    events = _events(frames, frame_context=_lane_context(lane_ids))
    assert _scenario(events, "changing_lane_with_lead")

    frames = _frames([10.0] * 30, _repeat([current_lead], 30), crossing_frame=15)
    assert not _scenario(_events(frames, frame_context=_lane_context(lane_ids)), "changing_lane_with_lead")


def test_lane_change_with_trail_distinguishes_rear_target_lane_from_side_vehicle():
    trail = _object("trail", "car", -8.0, 3.5, velocity=(12.0, 0.0))
    side = _object("side", "car", 0.0, 3.5, velocity=(10.0, 0.0))
    lane_ids = ["lane-a"] * 15 + ["lane-b"] * 15
    events = _events(_frames([10.0] * 30, _repeat([trail], 30), crossing_frame=15), frame_context=_lane_context(lane_ids))
    assert _scenario(events, "changing_lane_with_trail")
    assert not _scenario(_events(_frames([10.0] * 30, _repeat([side], 30), crossing_frame=15), frame_context=_lane_context(lane_ids)), "changing_lane_with_trail")


def test_stopping_with_lead_and_without_lead_are_mutually_exclusive():
    speeds = [5.0, 4.0, 2.0, 0.4, 0.2, 0.1, 0.1, 0.1]
    lead = _object("lead", "car", 8.0, 0.0, velocity=(0.0, 0.0))
    with_lead = _events(_frames(speeds, _repeat([lead])))
    assert _scenario(with_lead, "stopping_with_lead")
    assert not _scenario(with_lead, "stopping_without_lead")

    without_lead = _events(_frames(speeds, _repeat([])))
    assert _scenario(without_lead, "stopping_without_lead")
    assert not _scenario(without_lead, "stopping_with_lead")


def test_stationary_in_traffic_requires_nearby_traffic_not_isolated_stop():
    queue = [_object("lead", "car", 8.0, 0.0), _object("side", "car", -5.0, 3.0)]
    assert _scenario(_events(_frames([0.0] * 12, _repeat(queue, 12))), "stationary_in_traffic")
    assert not _scenario(_events(_frames([0.0] * 12, _repeat([], 12))), "stationary_in_traffic")


def test_behind_bike_is_not_crossed_by_bike_side_crossing():
    bike = _object("bike", "bicycle", 10.0, 0.0, length=1.8, width=0.6, velocity=(3.0, 0.0))
    events = _events(_frames([4.0] * 8, _repeat([bike])))
    assert _scenario(events, "behind_bike")
    crossing_bike = _object("bike", "bicycle", 0.0, 4.0, length=1.8, width=0.6, velocity=(0.0, -4.0))
    assert not _scenario(_events(_frames([4.0] * 8, _repeat([crossing_bike]))), "behind_bike")


def test_behind_long_vehicle_reuses_lead_geometry_and_class_or_length():
    truck = _object("truck", "truck", 14.0, 0.0, length=7.0, width=2.4, velocity=(5.0, 0.0))
    event = _scenario(_events(_frames([6.0] * 8, _repeat([truck]))), "behind_long_vehicle")[0]
    assert event.evidence["lead_class"] == "truck"
    car = _object("car", "car", 14.0, 0.0, length=4.5, width=1.8, velocity=(5.0, 0.0))
    assert not _scenario(_events(_frames([6.0] * 8, _repeat([car]))), "behind_long_vehicle")


def test_behind_pedestrian_on_driveable_excludes_crosswalk_pedestrian():
    ped = _object("ped", "pedestrian", 8.0, 0.3, length=0.5, width=0.5, velocity=(1.0, 0.0))
    events = _events(_frames([2.0] * 8, _repeat([ped])))
    assert _scenario(events, "behind_pedestrian_on_driveable")
    pedestrian_crosswalk = {
        "frames": [
            {"frame_index": index, "interactions": [{"pedestrian_track_id": "object:ped", "state": "on_crosswalk", "near_ego": True}]}
            for index in range(8)
        ]
    }
    assert not _scenario(_events(_frames([2.0] * 8, _repeat([ped])), pedestrian_crosswalk=pedestrian_crosswalk), "behind_pedestrian_on_driveable")


def test_waiting_for_pedestrian_requires_response_not_unrelated_stationary():
    objects = _crossing_pedestrian_track()
    speeds = [4.0, 4.0, 3.0, 2.0, 1.0, 0.3, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]
    accel = [-0.5] * len(speeds)
    event = _scenario(
        _events(_frames(speeds, objects, accelerations=accel)),
        "waiting_for_pedestrian_to_cross",
    )[0]
    assert event.evidence["pedestrian_id"] == "object:ped"
    assert event.evidence["path_conflict_geometry"] == "pedestrian_crosses_ego_future_path_corridor"
    assert event.evidence["minimum_path_distance_m"] <= 1.5
    assert event.evidence["lateral_displacement_m"] >= 3.0

    stationary = _frames([0.0] * len(objects), objects)
    assert not _scenario(_events(stationary), "waiting_for_pedestrian_to_cross")


def test_waiting_for_pedestrian_rejects_crossing_without_ego_response():
    objects = _crossing_pedestrian_track()
    speeds = [4.0] * len(objects)
    assert not _scenario(
        _events(_frames(speeds, objects)),
        "waiting_for_pedestrian_to_cross",
    )


def test_waiting_for_pedestrian_rejects_near_parallel_pedestrian():
    ped = _object("ped", "pedestrian", 8.0, 0.4, length=0.5, width=0.5, velocity=(1.0, 0.0))
    speeds = [4.0, 4.0, 3.0, 2.0, 1.0, 0.3, 0.1, 0.1, 0.1, 0.1]
    accel = [-0.5] * len(speeds)
    assert not _scenario(
        _events(_frames(speeds, _repeat([ped], len(speeds)), accelerations=accel)),
        "waiting_for_pedestrian_to_cross",
    )


def test_waiting_for_pedestrian_outputs_only_accepted_pedestrian_id():
    crossing = _crossing_pedestrian_track("crossing")
    parallel = [
        _object("parallel", "pedestrian", 12.0, 0.8, length=0.5, width=0.5, velocity=(1.0, 0.0))
        for _ in crossing
    ]
    objects = [row + [parallel[index]] for index, row in enumerate(crossing)]
    speeds = [4.0, 4.0, 3.0, 2.0, 1.0, 0.3, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]
    accel = [-0.5] * len(speeds)
    events = _scenario(
        _events(_frames(speeds, objects, accelerations=accel)),
        "waiting_for_pedestrian_to_cross",
    )
    assert [event.evidence["pedestrian_id"] for event in events] == ["object:crossing"]


def test_barrier_on_driveable_not_roadside_guardrail():
    barrier = _object("b1", "barrier", 8.0, 0.8, length=2.0, width=0.5, velocity=(0.0, 0.0), annotation_type="static")
    guardrail = _object("g1", "barrier", 8.0, 4.0, length=8.0, width=0.5, velocity=(0.0, 0.0), annotation_type="static")
    assert _scenario(_events(_frames([2.0] * 8, _repeat([barrier]))), "near_barrier_on_driveable")
    assert not _scenario(_events(_frames([2.0] * 8, _repeat([guardrail]))), "near_barrier_on_driveable")


def test_excluded_tags_are_not_registered_or_emitted():
    assert not (set(EXPLICITLY_EXCLUDED_SCENARIOS) & set(RULE_BASED_SCENARIOS))
    summary = detector_summary()
    assert set(EXPLICITLY_EXCLUDED_SCENARIOS) == set(summary["explicitly_excluded"])
