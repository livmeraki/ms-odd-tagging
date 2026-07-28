"""Focused synthetic coverage for shared object-to-ego-path crossings."""

from __future__ import annotations

import copy
import math

from ms_odd_tagging.features.object_path_crossing_relations import (
    build_object_path_crossing_relations,
)
from ms_odd_tagging.features.object_relations import build_object_relations
from ms_odd_tagging.tagger.rule_based.object_path_crossings import (
    detect_object_path_crossings,
)
from ms_odd_tagging.tagger.rule_based.registry import (
    detect_events,
    events_overlapping_window,
    load_config,
    merge_scenario_events,
)


def _object(
    object_id: str,
    class_name: str,
    x: float,
    y: float,
    *,
    confidence: float | None = None,
    heading_relative_rad: float = 0.0,
) -> dict:
    result = {
        "object_id": object_id,
        "class": class_name,
        "subclass": None,
        "annotation_type": "dynamic",
        "position_lcs_m": [x, y, 0.0],
        "dimensions_m": {"length": 2.0, "width": 0.8, "height": 1.5},
        "heading_relative_rad": heading_relative_rad,
        "velocity_lcs_mps": None,
        "velocity_source": None,
    }
    if confidence is not None:
        result["confidence"] = confidence
    return result


def _recording(
    object_frames: list[list[dict]],
    *,
    timestamps: list[float] | None = None,
    ego_points: list[tuple[float, float]] | None = None,
) -> dict:
    count = len(object_frames)
    timestamps = timestamps or [round(index * 0.1, 4) for index in range(count)]
    ego_points = ego_points or [(float(index), 0.0) for index in range(count)]
    frames = []
    for index, objects in enumerate(object_frames):
        if index + 1 < count:
            dx = ego_points[index + 1][0] - ego_points[index][0]
            dy = ego_points[index + 1][1] - ego_points[index][1]
        elif index:
            dx = ego_points[index][0] - ego_points[index - 1][0]
            dy = ego_points[index][1] - ego_points[index - 1][1]
        else:
            dx, dy = 1.0, 0.0
        heading = math.atan2(dy, dx)
        frames.append(
            {
                "frame_index": 5 + index * 2,
                "time_since_start_s": timestamps[index],
                "ego": {
                    "position_lcs_m": [*ego_points[index], 0.0],
                    "heading_lcs_rad": heading,
                    "speed_mps": 10.0,
                    "acceleration_mps2": 0.0,
                    "velocity_lcs_mps": [10.0, 0.0, 0.0],
                    "yaw_rate_radps": 0.0,
                },
                "objects": objects,
            }
        )
    return {"recording_id": "synthetic-crossing", "frames": frames}


def _clean_frames(
    class_name: str = "car",
    object_id: str = "o1",
    *,
    reverse: bool = False,
) -> list[list[dict]]:
    offsets = [5, 5, 5, 4, 3, 2, 1, 0, -1, -2, -3, -4, -4, -4]
    if reverse:
        offsets = [-value for value in offsets]
    heading = math.pi / 2 if reverse else -math.pi / 2
    return [
        [
            _object(
                object_id,
                class_name,
                6.0,
                value,
                heading_relative_rad=heading,
            )
        ]
        for value in offsets
    ]


def _payload(recording: dict, config: dict):
    objects = build_object_relations(recording, config["object_relations"])
    settings = {
        **config["object_path_crossing_interactions"],
        "maximum_plausible_object_speed_mps": config["object_relations"][
            "maximum_physically_plausible_object_speed_mps"
        ],
    }
    return build_object_path_crossing_relations(recording, objects, settings)


def _events(recording: dict, config: dict | None = None):
    config = config or load_config()
    payload = _payload(recording, config)
    events, _ = detect_events(
        recording["frames"],
        config,
        object_path_crossing_relations=payload,
    )
    return events, payload


def _scenario(events, name: str):
    return [event for event in events if event.scenario == name]


def test_clean_bicycle_left_to_right_crossing():
    events, _ = _events(_recording(_clean_frames("bicycle")))
    event = _scenario(events, "crossed_by_bike")[0]
    assert event.evidence["crossing_direction"] == "left_to_right"
    assert event.evidence["initial_side"] == "LEFT"
    assert event.evidence["final_side"] == "RIGHT"


def test_clean_motorcycle_right_to_left_crossing():
    events, _ = _events(_recording(_clean_frames("motorcycle", reverse=True)))
    event = _scenario(events, "crossed_by_motorcycle")[0]
    assert event.evidence["crossing_direction"] == "right_to_left"


def test_clean_vehicle_crossing():
    events, _ = _events(_recording(_clean_frames("car")))
    assert len(_scenario(events, "crossed_by_vehicle")) == 1


def test_parallel_object_does_not_cross():
    frames = [
        [_object("o1", "car", float(index), 5.0)] for index in range(14)
    ]
    events, _ = _events(_recording(frames))
    assert not _scenario(events, "crossed_by_vehicle")


def test_object_passing_beside_ego_does_not_cross():
    frames = [
        [
            _object(
                "o1",
                "car",
                float(index) + 4.0,
                4.0,
                heading_relative_rad=0.0,
            )
        ]
        for index in range(18)
    ]
    events, _ = _events(_recording(frames))
    assert not _scenario(events, "crossed_by_vehicle")


def test_crossing_behind_current_ego_is_rejected():
    offsets = [5, 5, 4, 3, 2, 1, 0, -1, -2, -3, -4, -4, -4]
    frames = [
        [
            _object(
                "o1",
                "car",
                -4.0,
                y,
                heading_relative_rad=-math.pi / 2,
            )
        ]
        for y in offsets
    ]
    events, _ = _events(_recording(frames))
    assert not _scenario(events, "crossed_by_vehicle")


def test_spatial_intersection_at_very_different_time_is_rejected():
    offsets = [5, 5, 5, 4, 3, 2, 1, 0, -1, -2, -3, -4, -4, -4]
    offsets.extend([-4] * 26)
    frames = [
        [
            _object(
                "o1",
                "car",
                30.0,
                y,
                heading_relative_rad=-math.pi / 2,
            )
        ]
        for y in offsets
    ]
    recording = _recording(frames)
    config = load_config()
    payload = _payload(recording, config)
    events, diagnostics = detect_object_path_crossings(
        recording["frames"], config, payload
    )
    assert not _scenario(events, "crossed_by_vehicle")
    assert any(
        item["reason"] == "time_to_intersection_incompatible"
        for item in diagnostics
    )


def test_crossing_motion_inconsistent_with_object_yaw_is_rejected():
    frames = _clean_frames("car")
    for frame in frames:
        frame[0]["heading_relative_rad"] = 0.0
    recording = _recording(frames)
    config = load_config()
    payload = _payload(recording, config)
    events, diagnostics = detect_object_path_crossings(
        recording["frames"], config, payload
    )
    assert not _scenario(events, "crossed_by_vehicle")
    assert any(
        item["reason"] == "object_heading_motion_disagreement"
        for item in diagnostics
    )


def test_object_approaching_but_stopping_before_path():
    offsets = [5, 5, 5, 4.5, 4, 3.5, 3, 2.5, 2.5, 2.5]
    events, _ = _events(
        _recording(
            [
                [_object("o1", "car", 6, y, heading_relative_rad=-math.pi / 2)]
                for y in offsets
            ]
        )
    )
    assert not _scenario(events, "crossed_by_vehicle")


def test_object_enters_corridor_then_returns():
    offsets = [5, 5, 5, 4, 3, 2, 1, 0, 1, 2, 3, 4, 5]
    recording = _recording(
        [
            [_object("o1", "car", 6, y, heading_relative_rad=-math.pi / 2)]
            for y in offsets
        ]
    )
    config = load_config()
    payload = _payload(recording, config)
    events, diagnostics = detect_object_path_crossings(
        recording["frames"], config, payload
    )
    assert not events
    assert any("returned" in item["reason"] for item in diagnostics)


def test_static_object_inside_corridor_while_ego_passes():
    frames = [[_object("o1", "car", 6, 0)] for _ in range(14)]
    events, _ = _events(_recording(frames))
    assert not _scenario(events, "crossed_by_vehicle")


def test_object_first_appearing_inside_corridor():
    offsets = [0, 0, -1, -2, -3, -4, -4, -4]
    recording = _recording([[_object("o1", "car", 6, y)] for y in offsets])
    config = load_config()
    payload = _payload(recording, config)
    events, diagnostics = detect_object_path_crossings(
        recording["frames"], config, payload
    )
    assert not events
    assert any(item["reason"] == "first_appears_inside_corridor" for item in diagnostics)


def test_one_frame_path_overlap():
    offsets = [5, 5, 5, 0, 5, 5, 5]
    events, _ = _events(
        _recording([[_object("o1", "car", 6, y)] for y in offsets])
    )
    assert not _scenario(events, "crossed_by_vehicle")


def test_curved_ego_path_crossing():
    count = 14
    ego_points = [
        (10 * math.cos(0.04 * index), 10 * math.sin(0.04 * index))
        for index in range(count)
    ]
    anchor = ego_points[7]
    tangent_angle = 0.04 * 7 + math.pi / 2
    normal = (-math.sin(tangent_angle), math.cos(tangent_angle))
    offsets = [5, 5, 5, 4, 3, 2, 1, 0, -1, -2, -3, -4, -4, -4]
    frames = [
        [
            _object(
                "o1",
                "car",
                anchor[0] + normal[0] * offset,
                anchor[1] + normal[1] * offset,
                heading_relative_rad=-math.pi / 2,
            )
        ]
        for offset in offsets
    ]
    events, _ = _events(_recording(frames, ego_points=ego_points))
    assert _scenario(events, "crossed_by_vehicle")


def test_ego_turning_while_object_static():
    count = 20
    ego_points = [
        (10 * math.cos(0.08 * index), 10 * math.sin(0.08 * index))
        for index in range(count)
    ]
    frames = [[_object("o1", "car", 8, 5)] for _ in range(count)]
    events, _ = _events(_recording(frames, ego_points=ego_points))
    assert not _scenario(events, "crossed_by_vehicle")


def test_missing_object_frame_during_crossing():
    frames = _clean_frames("car")
    frames[7] = []
    events, _ = _events(_recording(frames))
    assert _scenario(events, "crossed_by_vehicle")


def test_reconciled_id_switch_during_crossing():
    frames = _clean_frames("car")
    for index in range(7, len(frames)):
        frames[index][0]["object_id"] = "o2"
    events, payload = _events(_recording(frames))
    event = _scenario(events, "crossed_by_vehicle")[0]
    assert len(event.evidence["source_object_ids"]) == 2
    assert len(
        {
            item["track_id"]
            for frame in payload["frames"]
            for item in frame["objects"]
        }
    ) == 1


def test_duplicate_object_boxes_do_not_duplicate_event():
    frames = _clean_frames("car")
    for frame in frames:
        duplicate = copy.deepcopy(frame[0])
        duplicate["object_id"] = "duplicate"
        duplicate["position_lcs_m"][0] += 0.1
        frame.append(duplicate)
    events, _ = _events(_recording(frames))
    assert len(_scenario(events, "crossed_by_vehicle")) == 1


def test_low_confidence_object_is_filtered():
    config = copy.deepcopy(load_config())
    config["object_relations"]["minimum_object_confidence"] = 0.5
    frames = _clean_frames("car")
    for frame in frames:
        frame[0]["confidence"] = 0.1
    events, _ = _events(_recording(frames), config)
    assert not _scenario(events, "crossed_by_vehicle")


def test_insufficient_lateral_displacement():
    config = copy.deepcopy(load_config())
    config["object_path_crossing_interactions"][
        "minimum_lateral_displacement_m"
    ] = 12.0
    events, _ = _events(_recording(_clean_frames("car")), config)
    assert not _scenario(events, "crossed_by_vehicle")


def test_non_adjacent_position_jump_is_rejected():
    offsets = [5, 5, 5, 4, 3, 0, -5, -5, -5]
    recording = _recording(
        [
            [_object("o1", "car", 6, y, heading_relative_rad=-math.pi / 2)]
            for y in offsets
        ]
    )
    config = copy.deepcopy(load_config())
    config["object_relations"]["maximum_physically_plausible_object_speed_mps"] = 30
    payload = _payload(recording, config)
    events, diagnostics = detect_object_path_crossings(
        recording["frames"], config, payload
    )
    assert not events
    assert any(
        item["reason"] in {"opposite_side_not_stable", "impossible_position_jump"}
        for item in diagnostics
    )


def test_bicycle_and_motorcycle_categories_are_separate():
    bike, _ = _events(_recording(_clean_frames("bicycle")))
    moto, _ = _events(_recording(_clean_frames("motorcycle")))
    assert _scenario(bike, "crossed_by_bike")
    assert not _scenario(bike, "crossed_by_motorcycle")
    assert _scenario(moto, "crossed_by_motorcycle")
    assert not _scenario(moto, "crossed_by_bike")


def test_motorcycle_is_excluded_from_crossed_by_vehicle():
    events, _ = _events(_recording(_clean_frames("motorcycle")))
    assert not _scenario(events, "crossed_by_vehicle")


def test_multiple_simultaneous_crossings_stay_separate():
    first = _clean_frames("car", "a")
    second = _clean_frames("car", "b", reverse=True)
    frames = [left + right for left, right in zip(first, second)]
    events, _ = _events(_recording(frames))
    vehicle_events = _scenario(events, "crossed_by_vehicle")
    assert len(vehicle_events) == 2
    assert {event.evidence["object_track_id"] for event in vehicle_events} == {
        "object:a",
        "object:b",
    }


def test_event_spanning_overlapping_windows_keeps_identity():
    event = _scenario(
        _events(_recording(_clean_frames("car")))[0],
        "crossed_by_vehicle",
    )[0]
    first = events_overlapping_window([event], 5, 23)
    second = events_overlapping_window([event], 19, 40)
    assert first[0]["evidence"]["object_path_crossing_event_id"] == second[0][
        "evidence"
    ]["object_path_crossing_event_id"]


def test_duplicate_window_event_merging_and_distinct_object_preservation():
    events, _ = _events(
        _recording(
            [
                left + right
                for left, right in zip(
                    _clean_frames("car", "a"),
                    _clean_frames("car", "b", reverse=True),
                )
            ]
        )
    )
    vehicle_events = _scenario(events, "crossed_by_vehicle")
    merged = merge_scenario_events(
        [vehicle_events[0], vehicle_events[0], vehicle_events[1]]
    )
    assert len(merged) == 2


def test_irregular_timestamps():
    timestamps = [
        0.0, 0.09, 0.21, 0.31, 0.42, 0.5, 0.62,
        0.71, 0.83, 0.92, 1.04, 1.13, 1.25, 1.34,
    ]
    events, _ = _events(
        _recording(_clean_frames("car"), timestamps=timestamps)
    )
    assert _scenario(events, "crossed_by_vehicle")


def test_invalid_trajectory():
    frames = _clean_frames("car")
    recording = _recording(frames, ego_points=[(0.0, 0.0)] * len(frames))
    events, payload = _events(recording)
    assert not _scenario(events, "crossed_by_vehicle")
    assert (
        payload["invalid_relation_counts"][
            "invalid_or_short_forward_ego_path"
        ]
        > 0
    )


def test_empty_input():
    recording = {"recording_id": "empty", "frames": []}
    events, payload = _events(recording)
    assert events == []
    assert payload["frames"] == []


def test_single_frame_input():
    recording = _recording([[_object("o1", "car", 0, 0)]])
    events, _ = _events(recording)
    assert not _scenario(events, "crossed_by_vehicle")
