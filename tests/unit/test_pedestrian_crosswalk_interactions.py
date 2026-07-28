"""Focused synthetic coverage for Phase 3B pedestrian-crosswalk events."""

from __future__ import annotations

import copy

from ms_odd_tagging.features.object_relations import build_object_relations
from ms_odd_tagging.features.pedestrian_crosswalk_relations import (
    build_pedestrian_crosswalk_relations,
)
from ms_odd_tagging.features.road_feature_relations import (
    build_road_feature_relations,
)
from ms_odd_tagging.tagger.rule_based.registry import (
    detect_events,
    events_overlapping_window,
    load_config,
    merge_scenario_events,
)


def _crosswalk(
    crosswalk_id: str,
    x: float,
    *,
    y: float = 0.0,
    valid: bool = True,
) -> dict:
    points = (
        [
            [x - 1.0, y - 3.0, 0.0],
            [x + 1.0, y - 3.0, 0.0],
            [x + 1.0, y + 3.0, 0.0],
            [x - 1.0, y + 3.0, 0.0],
        ]
        if valid
        else [[x, y, 0.0], [x + 1.0, y, 0.0]]
    )
    return {
        "roadmark_id": crosswalk_id,
        "class": "crosswalk",
        "subclass": None,
        "shape_type": "polygon",
        "points": [{"position_lcs_m": point} for point in points],
        "attributes": {},
        "ignored": False,
    }


def _pedestrian(
    object_id: str,
    x: float,
    *,
    y: float = 0.0,
    confidence: float | None = None,
) -> dict:
    result = {
        "object_id": object_id,
        "class": "pedestrian",
        "subclass": None,
        "annotation_type": "dynamic",
        "position_lcs_m": [x, y, 0.0],
        "dimensions_m": {"length": 0.6, "width": 0.6, "height": 1.7},
        "heading_relative_rad": 0.0,
        "velocity_lcs_mps": [0.0, 0.0, 0.0],
    }
    if confidence is not None:
        result["confidence"] = confidence
    return result


def _recording(
    pedestrian_frames: list[list[dict]],
    *,
    ego_x: list[float] | None = None,
    crosswalks: list[dict] | None = None,
    nearby: list[list[str]] | None = None,
) -> dict:
    count = len(pedestrian_frames)
    ego_x = ego_x or [0.0] * count
    crosswalks = (
        [_crosswalk("cw1", 10.0)] if crosswalks is None else crosswalks
    )
    ids = [str(item["roadmark_id"]) for item in crosswalks]
    nearby = nearby or [ids] * count
    return {
        "recording_id": "synthetic",
        "frames": [
            {
                "frame_index": index * 2 + 5,
                "time_since_start_s": round(index * 0.1, 3),
                "ego": {
                    "position_lcs_m": [ego_x[index], 0.0, 0.0],
                    "heading_lcs_rad": 0.0,
                    "speed_mps": 0.0,
                    "acceleration_mps2": 0.0,
                    "velocity_lcs_mps": [0.0, 0.0, 0.0],
                    "yaw_rate_radps": 0.0,
                },
                "objects": copy.deepcopy(pedestrian_frames[index]),
                "ld": {
                    "nearby_feature_ids": {"roadmarks": nearby[index]}
                },
            }
            for index in range(count)
        ],
        "ld_feature_store": {"roadmarks": crosswalks},
    }


def _repeat(*pedestrians: dict, count: int = 8):
    return [[copy.deepcopy(item) for item in pedestrians] for _ in range(count)]


def _payloads(recording: dict, config: dict | None = None):
    config = config or load_config()
    objects = build_object_relations(
        recording, config["object_relations"]
    )
    roads = build_road_feature_relations(
        recording, config["road_feature_relations"]
    )
    shared = build_pedestrian_crosswalk_relations(
        objects,
        roads,
        config["pedestrian_crosswalk_interactions"],
        config["object_relations"],
        config["road_feature_relations"],
    )
    return objects, roads, shared


def _events(recording: dict, config: dict | None = None):
    config = config or load_config()
    objects, roads, shared = _payloads(recording, config)
    events, _ = detect_events(
        recording["frames"],
        config,
        road_feature_relations=roads,
        object_relations=objects,
        pedestrian_crosswalk_relations=shared,
    )
    return events


def _scenario(events, label):
    return [event for event in events if event.scenario == label]


def test_pedestrian_far_from_crosswalk():
    recording = _recording(_repeat(_pedestrian("p1", 0.0)))
    shared = _payloads(recording)[2]
    assert all(
        not frame["interactions"]
        or frame["interactions"][0]["state"] == "outside"
        for frame in shared["frames"]
    )
    assert not _scenario(_events(recording), "near_pedestrian_on_crosswalk")


def test_pedestrian_beside_crosswalk():
    recording = _recording(_repeat(_pedestrian("p1", 10.0, y=4.0)))
    assert not _scenario(_events(recording), "near_pedestrian_on_crosswalk")


def test_pedestrian_on_crosswalk_and_near_ego():
    events = _events(_recording(_repeat(_pedestrian("p1", 10.0))))
    assert _scenario(events, "near_pedestrian_on_crosswalk")


def test_pedestrian_on_crosswalk_but_far_from_ego():
    recording = _recording(
        _repeat(_pedestrian("p1", 10.0)), ego_x=[-50.0] * 8
    )
    assert not _scenario(_events(recording), "near_pedestrian_on_crosswalk")


def test_ego_approaching_but_not_on_crosswalk():
    events = _events(_recording(_repeat(_pedestrian("p1", 10.0))))
    assert _scenario(events, "near_pedestrian_on_crosswalk")
    assert not _scenario(
        events, "near_pedestrian_on_crosswalk_with_ego"
    )


def test_ego_and_pedestrian_on_same_crosswalk():
    recording = _recording(
        _repeat(_pedestrian("p1", 10.0)), ego_x=[10.0] * 8
    )
    assert _scenario(
        _events(recording), "near_pedestrian_on_crosswalk_with_ego"
    )


def test_ego_and_pedestrian_on_different_crosswalks():
    recording = _recording(
        _repeat(_pedestrian("p1", 20.0)),
        ego_x=[10.0] * 8,
        crosswalks=[_crosswalk("cw1", 10.0), _crosswalk("cw2", 20.0)],
    )
    events = _events(recording)
    assert _scenario(events, "near_pedestrian_on_crosswalk")
    assert not _scenario(
        events, "near_pedestrian_on_crosswalk_with_ego"
    )


def test_multiple_pedestrians_on_one_crosswalk():
    event = _scenario(
        _events(
            _recording(
                _repeat(
                    _pedestrian("p1", 10.0, y=-1.0),
                    _pedestrian("p2", 10.0, y=1.0),
                )
            )
        ),
        "near_pedestrian_on_crosswalk",
    )[0]
    assert event.evidence["peak_pedestrian_count"] == 2


def test_duplicate_pedestrian_detections():
    event = _scenario(
        _events(
            _recording(
                _repeat(
                    _pedestrian("p1", 10.0),
                    _pedestrian("p1_alias", 10.1),
                )
            )
        ),
        "near_pedestrian_on_crosswalk",
    )[0]
    assert event.evidence["peak_pedestrian_count"] == 1


def test_one_frame_pedestrian_detection_loss():
    frames = _repeat(_pedestrian("p1", 10.0))
    frames[4] = []
    assert len(
        _scenario(_events(_recording(frames)), "near_pedestrian_on_crosswalk")
    ) == 1


def test_one_frame_crosswalk_detection_loss():
    nearby = [["cw1"] for _ in range(8)]
    nearby[4] = []
    assert _scenario(
        _events(
            _recording(
                _repeat(_pedestrian("p1", 10.0)), nearby=nearby
            )
        ),
        "near_pedestrian_on_crosswalk",
    )


def test_pedestrian_entering_crosswalk():
    xs = [7.0, 8.0, 9.0, 9.7, 10.0, 10.2, 10.4, 10.5]
    frames = [[_pedestrian("p1", x)] for x in xs]
    event = _scenario(
        _events(_recording(frames)), "near_pedestrian_on_crosswalk"
    )[0]
    assert event.start_frame > 5


def test_pedestrian_leaving_crosswalk():
    xs = [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 12.5, 13.0]
    frames = [[_pedestrian("p1", x)] for x in xs]
    event = _scenario(
        _events(_recording(frames)), "near_pedestrian_on_crosswalk"
    )[0]
    assert event.end_frame < 19


def test_ego_enters_while_pedestrian_remains():
    ego_x = [0.0, 2.0, 5.0, 8.0, 9.0, 10.0, 10.0, 10.0]
    event = _scenario(
        _events(
            _recording(
                _repeat(_pedestrian("p1", 10.0)), ego_x=ego_x
            )
        ),
        "near_pedestrian_on_crosswalk_with_ego",
    )[0]
    assert event.start_frame > 5


def test_ego_leaves_while_pedestrian_remains():
    ego_x = [10.0] * 6 + [13.8] * 4
    events = _events(
        _recording(
            _repeat(_pedestrian("p1", 10.0), count=10), ego_x=ego_x
        )
    )
    strict = _scenario(
        events, "near_pedestrian_on_crosswalk_with_ego"
    )[0]
    broad = _scenario(events, "near_pedestrian_on_crosswalk")[0]
    assert strict.end_frame < broad.end_frame


def test_low_confidence_pedestrian():
    config = copy.deepcopy(load_config())
    config["object_relations"]["minimum_object_confidence"] = 0.5
    recording = _recording(
        _repeat(_pedestrian("p1", 10.0, confidence=0.1))
    )
    assert not _scenario(
        _events(recording, config), "near_pedestrian_on_crosswalk"
    )


def test_invalid_crosswalk_geometry():
    recording = _recording(
        _repeat(_pedestrian("p1", 10.0)),
        crosswalks=[_crosswalk("cw1", 10.0, valid=False)],
    )
    assert not _scenario(_events(recording), "near_pedestrian_on_crosswalk")


def test_pedestrian_id_switch():
    frames = [
        [_pedestrian("p1" if index < 4 else "p2", 10.0)]
        for index in range(8)
    ]
    event = _scenario(
        _events(_recording(frames)), "near_pedestrian_on_crosswalk"
    )[0]
    assert {"p1", "p2"} <= set(event.evidence["pedestrian_ids"])


def test_crosswalk_id_switch_is_deduplicated():
    recording = _recording(
        _repeat(_pedestrian("p1", 10.0)),
        crosswalks=[
            _crosswalk("cw1", 10.0),
            _crosswalk("cw1_new", 10.1),
        ],
        nearby=[
            ["cw1"] if index < 4 else ["cw1_new"] for index in range(8)
        ],
    )
    event = _scenario(
        _events(recording), "near_pedestrian_on_crosswalk"
    )[0]
    assert len(event.evidence["crosswalk_ids"]) == 1


def test_event_spanning_overlapping_windows():
    event = _scenario(
        _events(_recording(_repeat(_pedestrian("p1", 10.0)))),
        "near_pedestrian_on_crosswalk",
    )[0]
    first = events_overlapping_window([event], 0, 13)
    second = events_overlapping_window([event], 9, 30)
    assert first[0]["evidence"]["pedestrian_crosswalk_event_id"] == second[0][
        "evidence"
    ]["pedestrian_crosswalk_event_id"]


def test_duplicate_window_event_merging():
    event = _scenario(
        _events(_recording(_repeat(_pedestrian("p1", 10.0)))),
        "near_pedestrian_on_crosswalk",
    )[0]
    assert len(merge_scenario_events([event, event])) == 1


def test_empty_input():
    recording = {"recording_id": "empty", "frames": []}
    assert _payloads(recording)[2]["frames"] == []
    assert _events(recording) == []


def test_no_pedestrians():
    recording = _recording([[] for _ in range(8)])
    assert not _scenario(_events(recording), "near_pedestrian_on_crosswalk")


def test_no_crosswalks():
    recording = _recording(
        _repeat(_pedestrian("p1", 10.0)), crosswalks=[]
    )
    assert not _scenario(_events(recording), "near_pedestrian_on_crosswalk")
