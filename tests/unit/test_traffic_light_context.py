from __future__ import annotations

import copy

from ms_odd_tagging.features.ego_motion import extract_ego_motion_features
from ms_odd_tagging.features.object_relations import build_object_relations
from ms_odd_tagging.features.road_feature_relations import build_road_feature_relations
from ms_odd_tagging.features.traffic_light_context import build_traffic_light_context
from ms_odd_tagging.features.traffic_relations import build_traffic_relations
from ms_odd_tagging.tagger.rule_based.registry import detect_recording_events, load_config


def _traffic_light(object_id: str, x: float, y: float = 1.0) -> dict:
    return {
        "object_id": object_id,
        "class": "traffic_light_car",
        "subclass": None,
        "annotation_type": "static",
        "position_lcs_m": [x, y, 0.0],
        "dimensions_m": {"length": 0.5, "width": 0.5, "height": 2.0},
    }


def _car(object_id: str, x: float, y: float = 0.0) -> dict:
    return {
        "object_id": object_id,
        "class": "car",
        "subclass": None,
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
        "subclass": None,
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


def _frame(index: int, ego_x: float, *, objects: list[dict] | None = None) -> dict:
    return {
        "frame_index": index,
        "timestamp_unix_s": float(index),
        "time_since_start_s": round(index * 0.1, 3),
        "ego": {
            "position_lcs_m": [ego_x, 0.0, 0.0],
            "heading_lcs_rad": 0.0,
            "speed_mps": 4.0,
            "acceleration_mps2": 0.0,
            "velocity_lcs_mps": [4.0, 0.0, 0.0],
            "yaw_rate_radps": 0.0,
        },
        "objects": copy.deepcopy(objects or []),
        "ld": {"nearby_feature_ids": {"roadmarks": ["sl1", "sl2"]}},
    }


def _recording(
    *,
    ego_xs: list[float] | None = None,
    objects: list[dict] | None = None,
    stoplines: list[dict] | None = None,
) -> dict:
    ego_xs = ego_xs or [0.0] * 8
    return {
        "recording_id": "synthetic-tl",
        "frames": [_frame(index, x, objects=objects) for index, x in enumerate(ego_xs)],
        "ld_feature_store": {"roadmarks": stoplines if stoplines is not None else [_stopline("sl1", 10.0)]},
    }


def _intersection_context(
    frames: list[dict],
    *,
    active: bool = True,
    distances: list[float] | None = None,
) -> dict[int, dict]:
    distances = distances or [5.0] * len(frames)
    return {
        frame["frame_index"]: {
            "topology_class": "x-intersection" if active else "normal",
            "topology_subtype": "x-intersection" if active else "normal",
            "ego_inside_topology_polygon": False,
            "distance_to_topology_polygon_m": distances[index],
            "topology_confidence": 0.8 if active else 0.0,
            "active_is_intersection": False,
            "component_geometry_confidence": 0.8 if active else 0.0,
        }
        for index, frame in enumerate(frames)
    }


def _context(recording: dict, *, frame_context: dict[int, dict] | None = None) -> dict:
    config = load_config()
    features = extract_ego_motion_features(
        recording["frames"],
        max_sample_gap_s=config["feature_extraction"]["max_sample_gap_s"],
        heading_change_horizon_s=config["feature_extraction"]["heading_change_horizon_s"],
        jerk_mode=config["jerk"]["calculation_mode"],
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


def test_normal_traffic_light_intersection_context():
    recording = _recording(objects=[_traffic_light("tl1", 11.0)])
    payload = _context(recording, frame_context=_intersection_context(recording["frames"]))
    frame = payload["frames"][0]
    assert frame["is_traffic_light_intersection"] is True
    assert frame["relevant_traffic_light_ids"] == ["tl1"]
    assert frame["stopline"]["id"] == "stopline:sl1"
    assert frame["stopline"]["before_stopline"] is True
    assert frame["intersection_state"] == "approaching"


def test_missing_ld_does_not_make_traffic_light_controlled_intersection():
    recording = _recording(objects=[_traffic_light("tl1", 11.0)], stoplines=[])
    payload = _context(recording)
    frame = payload["frames"][0]
    assert frame["is_traffic_light_intersection"] is False
    assert frame["stopline"]["id"] is None
    assert frame["evidence"]["topology"]["is_intersection"] is False


def test_unrelated_traffic_light_is_not_relevant_or_controlled():
    recording = _recording(objects=[_traffic_light("tl-side", 11.0, y=25.0)])
    payload = _context(recording, frame_context=_intersection_context(recording["frames"]))
    frame = payload["frames"][0]
    assert frame["is_traffic_light_intersection"] is False
    assert frame["relevant_traffic_light_ids"] == []
    assert frame["traffic_lights"][0]["association_confidence_label"] == "low"


def test_multiple_traffic_lights_selects_path_associated_ids():
    recording = _recording(
        objects=[_traffic_light("tl-main", 11.0), _traffic_light("tl-side", 11.0, y=25.0)]
    )
    payload = _context(recording, frame_context=_intersection_context(recording["frames"]))
    frame = payload["frames"][0]
    assert frame["relevant_traffic_light_ids"] == ["tl-main"]
    assert {light["object_id"] for light in frame["traffic_lights"]} == {"tl-main", "tl-side"}


def test_multiple_stoplines_prefers_stopline_associated_with_relevant_light():
    recording = _recording(
        objects=[_traffic_light("tl-main", 18.0)],
        stoplines=[_stopline("sl1", 6.0), _stopline("sl2", 18.0)],
    )
    payload = _context(recording, frame_context=_intersection_context(recording["frames"]))
    assert payload["frames"][0]["stopline"]["id"] == "stopline:sl2"


def test_lead_and_no_lead_are_exposed_from_path_compatible_relation():
    with_lead = _recording(objects=[_traffic_light("tl1", 11.0), _car("lead", 8.0)])
    payload = _context(with_lead, frame_context=_intersection_context(with_lead["frames"]))
    assert payload["frames"][0]["lead"]["exists"] is True
    assert payload["frames"][0]["lead"]["object_id"] == "object:lead"
    assert payload["frames"][0]["lead"]["same_path_compatible"] is True

    no_lead = _recording(objects=[_traffic_light("tl1", 11.0), _car("side", 8.0, y=5.0)])
    payload = _context(no_lead, frame_context=_intersection_context(no_lead["frames"]))
    assert payload["frames"][0]["lead"]["exists"] is False


def test_intersection_entry_inside_exit_progression():
    ego_xs = [-40.0, -10.0, -2.0, 2.0, 8.0, 14.0, 20.0]
    recording = _recording(ego_xs=ego_xs, objects=[_traffic_light("tl1", 11.0)])
    frame_context = _intersection_context(
        recording["frames"],
        distances=[40.0, 20.0, 2.0, 0.0, 0.0, 2.0, 40.0],
    )
    for index in (3, 4):
        frame_context[index]["ego_inside_topology_polygon"] = True
    payload = _context(recording, frame_context=frame_context)
    assert [frame["intersection_state"] for frame in payload["frames"]] == [
        "outside",
        "approaching",
        "approaching",
        "entry",
        "exit",
        "approaching",
        "outside",
    ]


def test_detect_recording_events_adds_summary_without_neutral_motion_tag():
    recording = _recording(objects=[_traffic_light("tl1", 11.0)])
    for frame in recording["frames"]:
        frame.update(
            {
                "topology_class": "x-intersection",
                "ego_inside_topology_polygon": False,
                "distance_to_topology_polygon_m": 5.0,
                "topology_confidence": 0.8,
                "active_is_intersection": False,
            }
        )
    events, quality = detect_recording_events(recording)
    assert "traffic_light_context" in quality
    assert quality["traffic_light_context"]["traffic_light_intersection_frame_count"] == 8
    assert not any("traffic_light" in event.scenario for event in events)
