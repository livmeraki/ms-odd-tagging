from __future__ import annotations

import json
import inspect
import math
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts" / "odld_explorer"
sys.path.insert(0, str(SCRIPT_DIR))

import generate_odld_dataset_explorers_w_scenario_tag as explorer  # noqa: E402

from ms_odd_tagging.tagger.rule_based.scenario_event import ScenarioEvent  # noqa: E402


def _canonical() -> dict:
    roadmark = {
        "roadmark_id": "cw1",
        "class": "crosswalk",
        "subclass": None,
        "shape_type": "polygon",
        "points": [
            {"position_lcs_m": [9.0, -3.0, 0.0]},
            {"position_lcs_m": [11.0, -3.0, 0.0]},
            {"position_lcs_m": [11.0, 3.0, 0.0]},
            {"position_lcs_m": [9.0, 3.0, 0.0]},
        ],
        "attributes": {},
        "ignored": False,
    }
    frames = []
    for index, x in enumerate((0.0, 5.0, 10.0, 15.0)):
        frames.append(
            {
                "frame_index": index,
                "time_since_start_s": index * 0.1,
                "ego": {
                    "position_lcs_m": [x, 0.0, 0.0],
                    "heading_lcs_rad": 0.0,
                    "speed_mps": 5.0,
                    "acceleration_mps2": 0.0,
                    "velocity_lcs_mps": [5.0, 0.0, 0.0],
                    "yaw_rate_radps": 0.0,
                },
                "ld": {"nearby_feature_ids": {"roadmarks": ["cw1"]}},
            }
        )
    return {
        "recording_id": "sample",
        "frames": frames,
        "ld_feature_store": {"roadmarks": [roadmark]},
    }


def test_compact_evidence_keeps_phase2b_debug_values() -> None:
    compact = explorer.compact_tag_evidence(
        {
            "road_feature_event_id": "crosswalk-traversal:crosswalk:cw1:2",
            "crosswalk_id": "crosswalk:cw1",
            "entry_frame": 2,
            "crossing_progress_m": 8.5,
            "association_confidence": "high",
            "large_internal_payload": list(range(100)),
        }
    )
    assert compact["crosswalk_id"] == "crosswalk:cw1"
    assert compact["entry_frame"] == 2
    assert compact["crossing_progress_m"] == 8.5
    assert "large_internal_payload" not in compact


def test_stale_window_events_are_replaced_by_current_detection(
    tmp_path: Path, monkeypatch
) -> None:
    stale = {
        "rule_config_version": "phase2-basic-lane-change-v1",
        "rule_based_events": [
            {
                "scenario": "stationary",
                "start_frame": 0,
                "end_frame": 1,
                "start_timestamp_s": 0.0,
                "end_timestamp_s": 0.1,
            }
        ],
    }
    (tmp_path / "sample_motional_windows_odld.json").write_text(
        json.dumps(stale), encoding="utf-8"
    )
    current = ScenarioEvent(
        "traversing_crosswalk",
        2,
        3,
        0.2,
        0.3,
        0.1,
        detector_version="phase2b-crosswalk-v1",
        evidence={"crosswalk_id": "crosswalk:cw1"},
    )
    monkeypatch.setattr(
        explorer, "detect_recording_events", lambda canonical, config: ([current], {})
    )
    payload = explorer.build_tag_payload("sample", tmp_path, _canonical())
    assert payload["configVersion"] == "phase3c-forward-arc-crossing-v3"
    assert payload["sourceKind"] == (
        "canonical_per_frame_rule_events_stale_window_replaced"
    )
    assert payload["scenarios"] == ["traversing_crosswalk"]


def test_relation_payload_contains_geometry_states_and_footprint() -> None:
    payload = explorer.build_road_feature_payload(_canonical())
    assert payload["schemaVersion"] == "road-feature-relations-v1"
    assert payload["configVersion"] == "phase3c-forward-arc-crossing-v3"
    assert payload["egoFootprint"] == {"length_m": 4.8, "width_m": 2.0}
    assert payload["tracks"][0]["trackId"] == "crosswalk:cw1"
    assert payload["tracks"][0]["x"]
    assert [frame["frameIndex"] for frame in payload["frames"]] == [0, 1, 2, 3]
    assert "on" in {
        relation["state"]
        for frame in payload["frames"]
        for relation in frame["crosswalks"]
    }


def test_generator_contains_phase2b_controls_colors_and_overlay_hooks() -> None:
    assert 'id="showRoadFeatureRelations"' in explorer.TAG_CONTROLS_HTML
    assert 'id="roadFeatureContext"' in explorer.TAG_CONTROLS_HTML
    for label in (
        "traversing_crosswalk",
        "on_stopline_crosswalk",
        "stationary_at_crosswalk",
        "stopping_at_crosswalk",
        "accelerating_at_crosswalk",
    ):
        assert f"{label}:" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "roadFeatureRelationTraces()" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "egoRoadFeatureFootprintTrace()" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "roadFeatureAssociationTrace(relations)" in explorer.TAG_SCRIPT_FUNCTIONS


def test_phase3a_object_payload_and_overlay_hooks() -> None:
    canonical = _canonical()
    canonical["frames"][0]["objects"] = [
        {
            "object_id": "p1",
            "class": "pedestrian",
            "subclass": None,
            "annotation_type": "dynamic",
            "position_lcs_m": [5.0, 0.0, 0.0],
            "dimensions_m": {"length": 0.6, "width": 0.6, "height": 1.7},
                    "heading_relative_rad": -math.pi / 2,
            "velocity_lcs_mps": [3.0, 4.0, 0.0],
            "velocity_source": "measured",
        }
    ]
    payload = explorer.build_object_relation_payload(canonical)
    assert payload["schemaVersion"] == "ego-object-relations-v1"
    assert payload["configVersion"] == "phase3c-forward-arc-crossing-v3"
    assert payload["frames"][0]["objects"][0]["category"] == "pedestrian"
    assert payload["frames"][0]["objects"][0]["annotationType"] == "dynamic"
    assert payload["frames"][0]["objects"][0]["speedMps"] == 5.0
    assert payload["frames"][0]["objects"][0]["velocityX"] == 3.0
    assert payload["frames"][0]["objects"][0]["velocityY"] == 4.0
    assert 'id="showObjectRelations"' in explorer.TAG_CONTROLS_HTML
    assert 'id="showDynamicObjectVelocities"' in explorer.TAG_CONTROLS_HTML
    assert 'id="objectRelationContext"' in explorer.TAG_CONTROLS_HTML
    assert "objectRelationTraces()" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "dynamicObjectVelocityTraces()" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "all dynamic-object speeds" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "name: 'ego speed'" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "traj.speed[currentIndex]" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "textposition: 'top center'" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "`${id} ·" not in explorer.TAG_SCRIPT_FUNCTIONS
    assert "item.trackId.replace('object:', '')" not in (
        explorer.TAG_SCRIPT_FUNCTIONS
    )
    for label in (
        "near_high_speed_vehicle",
        "near_long_vehicle",
        "near_multiple_bikes",
        "near_multiple_motorcycle",
        "near_multiple_pedestrians",
        "near_multiple_vehicles",
    ):
        assert f"{label}:" in explorer.TAG_SCRIPT_FUNCTIONS
    for label in (
        "near_pedestrian_on_crosswalk",
        "near_pedestrian_on_crosswalk_with_ego",
    ):
        assert f"{label}:" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "event.evidence.pedestrian_track_ids" in (
        explorer.TAG_SCRIPT_FUNCTIONS
    )


def test_phase3c_path_crossing_payload_controls_and_colors() -> None:
    canonical = _canonical()
    for index, frame in enumerate(canonical["frames"]):
        frame["objects"] = [
            {
                "object_id": "bike1",
                "class": "bicycle",
                "subclass": None,
                "annotation_type": "dynamic",
                "position_lcs_m": [7.5, 4.0 - index * 2.5, 0.0],
                "dimensions_m": {
                    "length": 1.8,
                    "width": 0.6,
                    "height": 1.4,
                },
                "heading_relative_rad": 0.0,
                "velocity_lcs_mps": [0.0, -25.0, 0.0],
                "velocity_source": "measured",
            }
        ]
    payload = explorer.build_object_path_crossing_payload(canonical)
    assert payload["schemaVersion"] == (
        "object-ego-forward-arc-crossing-relations-v3"
    )
    assert payload["configVersion"] == "phase3c-forward-arc-crossing-v3"
    assert payload["arc"]["outer_radius_m"] == 30.0
    assert payload["arc"]["half_angle_deg"] == 30.0
    assert payload["egoPath"]
    assert payload["frames"][0]["objects"][0]["category"] == "bicycle"
    assert 'id="showPathCrossingRelations"' in explorer.TAG_CONTROLS_HTML
    assert 'id="showConfirmedCrossingsOnly"' in explorer.TAG_CONTROLS_HTML
    assert 'id="pathCrossingObjectFilter"' in explorer.TAG_CONTROLS_HTML
    assert 'id="pathCrossingContext"' in explorer.TAG_CONTROLS_HTML
    assert "pathCrossingArcTraces()" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "crossingArcPolygon" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "currentPathCrossingFrame()" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "visibleConfirmedCrossingEvents()" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "crossingRelationObjects()" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "crossingTrajectoryPoints(item)" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "setFrame(event.evidence.arc_entry_frame" in inspect.getsource(
        explorer.scene_html
    )
    for label in (
        "crossed_by_bike",
        "crossed_by_motorcycle",
        "crossed_by_vehicle",
    ):
        assert f"{label}:" in explorer.TAG_SCRIPT_FUNCTIONS
