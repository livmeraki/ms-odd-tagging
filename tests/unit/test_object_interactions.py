"""Focused synthetic coverage for Phase 3A object interaction scenarios."""

from __future__ import annotations

import copy

from ms_odd_tagging.features.object_relations import build_object_relations
from ms_odd_tagging.tagger.rule_based.registry import (
    detect_events,
    events_overlapping_window,
    load_config,
    merge_scenario_events,
)


def _object(
    object_id: str | None,
    class_name: str,
    x: float,
    y: float = 0.0,
    *,
    length: float | None = 1.0,
    width: float | None = 0.8,
    velocity: tuple[float, float] | None = None,
    velocity_source: str | None = None,
    confidence: float | None = None,
) -> dict:
    result = {
        "object_id": object_id,
        "class": class_name,
        "subclass": None,
        "annotation_type": "dynamic",
        "position_lcs_m": [x, y, 0.0],
        "dimensions_m": (
            {"length": length, "width": width, "height": 1.5}
            if length is not None and width is not None
            else {}
        ),
        "heading_relative_rad": 0.0,
        "velocity_lcs_mps": (
            [velocity[0], velocity[1], 0.0] if velocity else None
        ),
        "velocity_source": velocity_source,
    }
    if confidence is not None:
        result["confidence"] = confidence
    return result


def _recording(
    object_frames: list[list[dict]],
    *,
    timestamps: list[float] | None = None,
    ego_x: list[float] | None = None,
) -> dict:
    count = len(object_frames)
    timestamps = timestamps or [round(index * 0.1, 3) for index in range(count)]
    ego_x = ego_x or [0.0] * count
    frames = []
    for index, objects in enumerate(object_frames):
        frames.append(
            {
                "frame_index": index * 2 + 5,
                "time_since_start_s": timestamps[index],
                "ego": {
                    "position_lcs_m": [ego_x[index], 0.0, 0.0],
                    "heading_lcs_rad": 0.0,
                    "speed_mps": 0.0,
                    "acceleration_mps2": 0.0,
                    "velocity_lcs_mps": [0.0, 0.0, 0.0],
                    "yaw_rate_radps": 0.0,
                },
                "objects": objects,
            }
        )
    return {"recording_id": "synthetic", "frames": frames}


def _repeated(*objects: dict, count: int = 7) -> list[list[dict]]:
    return [[copy.deepcopy(item) for item in objects] for _ in range(count)]


def _relations(recording: dict, config: dict | None = None) -> dict:
    config = config or load_config()
    return build_object_relations(recording, config["object_relations"])


def _events(recording: dict, config: dict | None = None):
    config = config or load_config()
    relations = _relations(recording, config)
    events, _ = detect_events(
        recording["frames"], config, object_relations=relations
    )
    return events


def _scenario(events, name: str):
    return [event for event in events if event.scenario == name]


def test_one_nearby_pedestrian():
    events = _events(_recording(_repeated(_object("p1", "pedestrian", 5))))
    assert not _scenario(events, "near_multiple_pedestrians")


def test_multiple_nearby_pedestrians():
    events = _events(
        _recording(
            _repeated(
                _object("p1", "pedestrian", 5),
                _object("p2", "pedestrian", 7),
            )
        )
    )
    event = _scenario(events, "near_multiple_pedestrians")[0]
    assert event.evidence["peak_simultaneous_count"] == 2


def test_duplicate_pedestrian_boxes_do_not_inflate_count():
    recording = _recording(
        _repeated(
            _object("p1", "pedestrian", 5),
            _object("p1_alias", "pedestrian", 5.1),
        )
    )
    config = load_config()
    payload = _relations(recording, config)
    assert len(payload["tracks"]) == 1
    # Keep a detector-level guard even if an upstream/custom relation producer
    # accidentally repeats one normalized track in a frame.
    for frame in payload["frames"]:
        frame["objects"].append(copy.deepcopy(frame["objects"][0]))
    events, _ = detect_events(
        recording["frames"], config, object_relations=payload
    )
    assert not _scenario(events, "near_multiple_pedestrians")


def test_two_pedestrians_with_one_frame_detection_loss():
    frames = _repeated(
        _object("p1", "pedestrian", 5),
        _object("p2", "pedestrian", 7),
        count=8,
    )
    frames[4] = []
    assert _scenario(
        _events(_recording(frames)), "near_multiple_pedestrians"
    )


def test_bicycles_and_motorcycles_are_separate_categories():
    payload = _relations(
        _recording(
            _repeated(
                _object("b1", "bicycle", 5),
                _object("m1", "motorcycle", 6),
            )
        )
    )
    assert {track["normalized_category"] for track in payload["tracks"]} == {
        "bicycle",
        "motorcycle",
    }


def test_multiple_bicycles():
    events = _events(
        _recording(
            _repeated(
                _object("b1", "bicycle", 5),
                _object("b2", "bicycle", 7),
            )
        )
    )
    assert _scenario(events, "near_multiple_bikes")


def test_multiple_motorcycles():
    events = _events(
        _recording(
            _repeated(
                _object("m1", "motorcycle", 5),
                _object("m2", "motorcycle", 7),
            )
        )
    )
    assert _scenario(events, "near_multiple_motorcycle")


def test_mixed_bicycle_and_motorcycle_does_not_satisfy_either_multiple_count():
    events = _events(
        _recording(
            _repeated(
                _object("b1", "bicycle", 5),
                _object("m1", "motorcycle", 7),
            )
        )
    )
    assert not _scenario(events, "near_multiple_bikes")
    assert not _scenario(events, "near_multiple_motorcycle")


def test_multiple_motorized_vehicles():
    events = _events(
        _recording(
            _repeated(
                _object("c1", "car", 5, length=4.5, width=1.8),
                _object("c2", "car", 8, length=4.5, width=1.8),
            )
        )
    )
    assert _scenario(events, "near_multiple_vehicles")


def test_object_outside_proximity_region():
    events = _events(
        _recording(
            _repeated(
                _object("p1", "pedestrian", 100),
                _object("p2", "pedestrian", 101),
            )
        )
    )
    assert not _scenario(events, "near_multiple_pedestrians")


def test_object_near_for_only_one_frame():
    frames = [[] for _ in range(7)]
    frames[3] = [
        _object("p1", "pedestrian", 5),
        _object("p2", "pedestrian", 7),
    ]
    assert not _scenario(
        _events(_recording(frames)), "near_multiple_pedestrians"
    )


def test_long_vehicle_by_explicit_class_and_minimum_length():
    recording = _recording(
        _repeated(_object("t1", "truck", 8, length=6.5, width=2.2))
    )
    relations = _relations(recording)
    assert "long_vehicle" in relations["frames"][-1]["objects"][0][
        "normalized_categories"
    ]
    events = _events(recording)
    event = _scenario(events, "near_long_vehicle")[0]
    assert event.evidence["classification_reason"] == (
        "explicit_class_and_minimum_length"
    )


def test_long_vehicle_by_dimensions():
    events = _events(
        _recording(
            _repeated(_object("c1", "car", 8, length=8.0, width=2.0))
        )
    )
    event = _scenario(events, "near_long_vehicle")[0]
    assert event.evidence["classification_reason"] == "bbox_length_threshold"


def test_ordinary_vehicle_below_length_threshold():
    events = _events(
        _recording(
            _repeated(_object("c1", "car", 8, length=4.5, width=1.8))
        )
    )
    assert not _scenario(events, "near_long_vehicle")


def test_high_speed_vehicle_with_valid_measured_velocity():
    events = _events(
        _recording(
            _repeated(
                _object(
                    "c1",
                    "car",
                    8,
                    length=4.5,
                    width=1.8,
                    velocity=(20, 0),
                    velocity_source="measured",
                )
            )
        )
    )
    event = _scenario(events, "near_high_speed_vehicle")[0]
    assert event.evidence["velocity_sources"] == ["measured"]
    assert event.evidence["speed_definition"] == "absolute_ground_relative_lcs"


def test_high_speed_vehicle_with_derived_global_velocity():
    frames = [
        [_object("c1", "car", index * 2.0, length=4.5, width=1.8)]
        for index in range(7)
    ]
    events = _events(_recording(frames))
    event = _scenario(events, "near_high_speed_vehicle")[0]
    assert event.evidence["velocity_sources"] == ["derived_global"]


def test_false_velocity_spike_from_id_switch_is_rejected():
    frames = [
        [_object("old", "car", 5, length=4.5, width=1.8)] for _ in range(3)
    ] + [
        [_object("new", "car", 25, length=4.5, width=1.8)] for _ in range(4)
    ]
    assert not _scenario(
        _events(_recording(frames)), "near_high_speed_vehicle"
    )


def test_large_timestamp_gap_rejects_derived_velocity():
    frames = [
        [_object("c1", "car", 5, length=4.5, width=1.8)],
        [_object("c1", "car", 25, length=4.5, width=1.8)],
    ]
    payload = _relations(_recording(frames, timestamps=[0.0, 1.0]))
    second = payload["frames"][1]["objects"][0]
    assert second["velocity_source"] == "unavailable"


def test_ego_motion_is_not_mistaken_for_object_ground_speed():
    frames = [
        [_object("c1", "car", 10, length=4.5, width=1.8)]
        for _ in range(7)
    ]
    payload = _relations(
        _recording(frames, ego_x=[float(index) for index in range(7)])
    )
    speeds = [
        item["object_speed_mps"]
        for frame in payload["frames"]
        for item in frame["objects"]
        if item["object_speed_mps"] is not None
    ]
    assert speeds and max(speeds) == 0.0


def test_event_across_overlapping_windows_keeps_identity():
    event = _scenario(
        _events(
            _recording(
                _repeated(
                    _object("p1", "pedestrian", 5),
                    _object("p2", "pedestrian", 7),
                )
            )
        ),
        "near_multiple_pedestrians",
    )[0]
    first = events_overlapping_window([event], 0, 13)
    second = events_overlapping_window([event], 9, 30)
    assert first[0]["evidence"]["object_interaction_event_id"] == second[0][
        "evidence"
    ]["object_interaction_event_id"]


def test_duplicate_window_event_merging():
    event = _scenario(
        _events(
            _recording(
                _repeated(
                    _object("p1", "pedestrian", 5),
                    _object("p2", "pedestrian", 7),
                )
            )
        ),
        "near_multiple_pedestrians",
    )[0]
    merged = merge_scenario_events([event, event])
    assert len(merged) == 1


def test_empty_input():
    recording = {"recording_id": "empty", "frames": []}
    assert _relations(recording)["tracks"] == []
    assert _events(recording) == []


def test_missing_bbox_dimensions_are_not_counted():
    events = _events(
        _recording(
            _repeated(
                _object("p1", "pedestrian", 5, length=None, width=None),
                _object("p2", "pedestrian", 7),
            )
        )
    )
    assert not _scenario(events, "near_multiple_pedestrians")


def test_low_confidence_object_is_filtered():
    config = copy.deepcopy(load_config())
    config["object_relations"]["minimum_object_confidence"] = 0.5
    events = _events(
        _recording(
            _repeated(
                _object("p1", "pedestrian", 5, confidence=0.1),
                _object("p2", "pedestrian", 7, confidence=0.9),
            )
        ),
        config,
    )
    assert not _scenario(events, "near_multiple_pedestrians")


def test_participating_identities_can_change_during_one_event():
    frames = []
    for index in range(8):
        first_id = "p1" if index < 4 else "p3"
        frames.append(
            [
                _object(first_id, "pedestrian", 5),
                _object("p2", "pedestrian", 8),
            ]
        )
    event = _scenario(
        _events(_recording(frames)), "near_multiple_pedestrians"
    )[0]
    assert set(event.evidence["source_object_ids"]) == {"p1", "p2", "p3"}
    assert event.evidence["peak_simultaneous_count"] == 2
