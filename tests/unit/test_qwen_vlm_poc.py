from __future__ import annotations

import json
import urllib.error

import ms_odd_tagging.qwen_vlm_poc.evidence as evidence_module
from ms_odd_tagging.qwen_vlm_poc.candidates import (
    generate_candidates,
    pedestrian_corridor_conflict,
)
from ms_odd_tagging.qwen_vlm_poc.client import VlmClient, cache_key, read_prompt
from ms_odd_tagging.qwen_vlm_poc.config import load_config
from ms_odd_tagging.qwen_vlm_poc.evidence import render_candidate_bevs, serialize_candidate_bundle
from ms_odd_tagging.qwen_vlm_poc.merging import merge_decisions
from ms_odd_tagging.qwen_vlm_poc.models import CandidateWindow, EvidenceItem, VlmDecision
from ms_odd_tagging.qwen_vlm_poc.validation import parse_and_validate_response


def _frame(index: int, *, speed=0.0, accel=0.0, objects=None, topology=None, roadmarks=None, lane_lines=None):
    frame = {
        "frame_index": index,
        "time_since_start_s": index * 0.5,
        "ego": {
            "position_lcs_m": [index * 0.1, 0.0, 0.0],
            "heading_lcs_rad": 0.0,
            "speed_mps": speed,
            "acceleration_mps2": accel,
        },
        "objects": objects or [],
        "ld": {"nearby_feature_ids": {"lane_lines": lane_lines or ["l", "r"], "roadmarks": roadmarks or []}},
    }
    if topology:
        frame.update(topology)
    return frame


def _ped(object_id="ped-1", x=12.0, y=2.0, vy=-0.5):
    return {
        "object_id": object_id,
        "class": "pedestrian",
        "position_lcs_m": [x, y, 0.0],
        "velocity_lcs_mps": [0.0, vy, 0.0],
    }


def _traffic_light(object_id="tl-1", x=15.0, y=3.0):
    return {
        "object_id": object_id,
        "class": "traffic_light_car",
        "position_lcs_m": [x, y, 0.0],
    }


def _vehicle(object_id="veh-1", x=8.0, y=0.2, *, same_lane=True):
    return {
        "object_id": object_id,
        "class": "vehicle",
        "position_lcs_m": [x, y, 0.0],
        "same_lane": same_lane,
    }


def _stopline_context(frame_index: int, distance: float, relation: str = "before_stopline", *, lead=None):
    return {
        "frame_index": frame_index,
        "is_traffic_light_intersection": False,
        "confidence": 0.0,
        "traffic_lights": [],
        "relevant_traffic_light_ids": [],
        "stopline": {
            "id": "stop-1",
            "distance_m": distance,
            "relation": relation,
            "association_confidence": "medium",
        },
        "ego_motion": {
            "speed_mps": 1.0,
            "acceleration_mps2": -0.5,
            "stationary": False,
            "stopping": True,
            "accelerating": False,
            "temporal_state": "stopping",
        },
        "lead": lead
        or {
            "exists": False,
            "object_id": None,
            "longitudinal_distance_m": None,
            "lateral_distance_m": None,
            "same_path_compatible": False,
            "confidence": "none",
        },
        "intersection_state": "approaching",
        "evidence": {
            "topology": {
                "is_intersection": False,
                "inside": False,
                "distance_m": None,
                "confidence": 0.0,
                "topology_class": None,
            }
        },
    }


def _recording(frames):
    return {"recording_id": "rec-a", "frames": frames, "ld_feature_store": {"points": []}}


def _candidate(scenario="on_intersection"):
    return CandidateWindow(
        candidate_id=f"rec-a_{scenario}_000000_000010",
        recording_id="rec-a",
        scenario=scenario,
        start_frame=0,
        end_frame=10,
        start_timestamp_s=0.0,
        end_timestamp_s=5.0,
        evidence=[EvidenceItem("ev-1", "kind", "summary", {"value": 1})],
        selected_frame_indices=[0, 5, 10],
        bev_paths=[],
        primary_object_ids=["ped-1"] if scenario == "waiting_for_pedestrian_to_cross" else [],
    )


def test_pedestrian_corridor_conflict_requires_path_relation():
    config = load_config()
    assert pedestrian_corridor_conflict(_frame(0), _ped(x=12.0, y=2.0), config)["conflict"]
    assert not pedestrian_corridor_conflict(_frame(0), _ped(x=-20.0, y=12.0), config)["conflict"]


def test_pedestrian_corridor_conflict_handles_relative_velocity_dict():
    config = load_config()
    ped = {
        "object_id": "1059",
        "class": "pedestrian",
        "position_lcs_m": [8.0, 5.4, 0.0],
        "relative_velocity_ego_mps": {"longitudinal": 0.1, "lateral": -1.5},
    }
    conflict = pedestrian_corridor_conflict(_frame(0), ped, config)
    assert conflict["conflict"]
    assert conflict["moving_toward_corridor"]
    assert conflict["lateral_speed_mps"] == -1.5


def test_waiting_candidate_generation_uses_pedestrian_conflict_and_ego_response():
    config = load_config(overrides={"window_seconds": 5.0, "candidate_stride_seconds": 5.0, "max_bev_images": 6})
    rec = _recording([_frame(i, speed=0.4, accel=-0.5, objects=[_ped()]) for i in range(12)])
    candidates = generate_candidates(rec, "waiting_for_pedestrian_to_cross", config)
    assert candidates
    assert candidates[0].primary_object_ids == ["ped-1"]
    assert "pedestrian_corridor_conflict" in candidates[0].recall_reasons


def test_waiting_candidate_negative_for_proximity_without_response():
    config = load_config(overrides={"window_seconds": 5.0})
    rec = _recording([_frame(i, speed=8.0, accel=0.0, objects=[_ped()]) for i in range(12)])
    assert generate_candidates(rec, "waiting_for_pedestrian_to_cross", config) == []


def test_waiting_candidate_includes_1059_corridor_entry_motion_regression():
    config = load_config(
        overrides={
            "window_seconds": 5.0,
            "candidate_stride_seconds": 5.0,
            "max_bev_images": 6,
        }
    )
    frames = []
    for frame_index in range(532, 583):
        progress = frame_index - 532
        x = 52.0047 + (55.4299 - 52.0047) * (progress / 50.0)
        y = 31.8958 + (25.4577 - 31.8958) * (progress / 50.0)
        lateral = 11.6727 + (4.3972 - 11.6727) * (progress / 50.0)
        ped = {
            "object_id": "1059",
            "class": "pedestrian",
            "position_lcs_m": [x, y, 0.0],
            "position_ego_m": {"longitudinal": 8.0, "lateral": lateral},
            "relative_velocity_ego_mps": {"longitudinal": 0.0, "lateral": -1.45},
        }
        frame = _frame(frame_index, speed=0.0, accel=0.0, objects=[ped])
        frame["time_since_start_s"] = (frame_index - 532) * 0.1
        frames.append(frame)

    rec = {"recording_id": "Rec_Drv_GER_MACHET18_20260319_151819", "frames": frames, "ld_feature_store": {"points": []}}
    candidates = generate_candidates(rec, "waiting_for_pedestrian_to_cross", config)
    candidate = candidates[0]
    assert 578 in candidate.selected_frame_indices
    assert 582 in candidate.selected_frame_indices
    assert max(candidate.selected_frame_indices) >= 582

    conflict_evidence = next(item for item in candidate.evidence if item.kind == "pedestrian_corridor_conflict")
    track = conflict_evidence.data["tracks"]["1059"]
    motion = conflict_evidence.data["motion"]["1059"]
    assert track[0]["conflict"]["moving_toward_corridor"]
    assert any(item["frame_index"] == 578 for item in track)
    assert motion["corridor_entry_frame"] == 578
    assert motion["pedestrian_motion_state"] == "moving"
    assert motion["pedestrian_speed_mps"] > 1.0
    assert motion["pedestrian_displacement_m"] > 7.0
    assert motion["moving_toward_corridor"]
    assert motion["lateral_velocity_mps"] < 0.0


def test_intersection_candidate_uses_intersection_true_lane_lines_not_topology():
    config = load_config(overrides={"window_seconds": 5.0, "candidate_stride_seconds": 5.0, "max_bev_images": 6})
    topology = {"topology_class": "normal", "topology_confidence": 0.0, "arm_count": 0}
    rec = _recording([_frame(i, speed=3.0, topology=topology, lane_lines=["i1", "i2", "r"]) for i in range(12)])
    rec["ld_feature_store"] = {
        "points": [],
        "lane_lines": [
            {"line_id": "i1", "intersection": True},
            {"line_id": "i2", "intersection": True},
            {"line_id": "r", "intersection": False},
        ],
    }
    candidates = generate_candidates(rec, "on_intersection", config)
    assert candidates
    assert candidates[0].recall_reasons == ["ld_intersection_true_lane_lines"]
    assert candidates[0].metadata["topology_class_not_used_for_recall"]
    assert candidates[0].end_frame in candidates[0].selected_frame_indices
    assert len(candidates[0].selected_frame_indices) == 6
    evidence = next(item for item in candidates[0].evidence if item.kind == "intersection_true_lane_lines")
    assert evidence.data["unique_lane_line_ids_sample"] == ["i1", "i2"]
    assert evidence.data["unique_lane_line_id_count"] == 2
    assert evidence.data["frame_count_with_intersection_true_lane_lines"] > 0
    assert "Multiple intersection=True lane lines" in evidence.data["warning"]


def test_intersection_candidate_does_not_use_topology_or_corridor_count_for_recall():
    config = load_config(overrides={"window_seconds": 5.0, "candidate_stride_seconds": 5.0})
    topology = {"topology_class": "x-intersection", "topology_confidence": 0.9, "arm_count": 4}
    rec = _recording([_frame(i, speed=3.0, topology=topology) for i in range(12)])
    rec["ld_feature_store"] = {
        "points": [],
        "lane_lines": [
            {"line_id": "l", "intersection": False},
            {"line_id": "r", "intersection": False},
        ],
    }
    assert generate_candidates(rec, "on_intersection", config) == []


def test_intersection_candidate_negative_for_ordinary_curve_and_merge_split():
    config = load_config(overrides={"window_seconds": 5.0})
    curve = _recording([_frame(i, topology={"topology_class": "normal", "arm_count": 0}) for i in range(12)])
    split = _recording([_frame(i, topology={"topology_class": "normal", "arm_count": 2}) for i in range(12)])
    assert generate_candidates(curve, "on_intersection", config) == []
    assert generate_candidates(split, "on_intersection", config) == []


def test_starting_u_turn_candidate_positive_uses_heading_change_and_six_frames():
    config = load_config(overrides={"window_seconds": 5.0, "candidate_stride_seconds": 5.0, "max_bev_images": 6})
    frames = []
    for i in range(12):
        frame = _frame(i, speed=2.0)
        frame["ego"]["heading_lcs_rad"] = i * 0.18
        frames.append(frame)
    candidates = generate_candidates(_recording(frames), "starting_u_turn", config)
    assert candidates
    candidate = candidates[0]
    assert candidate.recall_reasons == ["large_ego_heading_change"]
    assert len(candidate.selected_frame_indices) == 6
    assert candidate.selected_frame_indices == sorted(candidate.selected_frame_indices)
    assert any(item.kind == "ego_heading_change" for item in candidate.evidence)


def test_starting_u_turn_candidate_negative_for_ordinary_curve():
    config = load_config(overrides={"window_seconds": 5.0})
    frames = []
    for i in range(12):
        frame = _frame(i, speed=4.0)
        frame["ego"]["heading_lcs_rad"] = i * 0.03
        frames.append(frame)
    assert generate_candidates(_recording(frames), "starting_u_turn", config) == []


def test_starting_u_turn_borderline_below_threshold_is_not_sent_to_vlm():
    config = load_config(
        overrides={
            "window_seconds": 5.0,
            "u_turn_min_heading_change_rad": 1.0,
            "u_turn_min_cumulative_heading_change_rad": 1.2,
        }
    )
    frames = []
    for i in range(12):
        frame = _frame(i, speed=2.0)
        frame["ego"]["heading_lcs_rad"] = i * 0.08
        frames.append(frame)
    assert generate_candidates(_recording(frames), "starting_u_turn", config) == []


def test_starting_u_turn_candidate_deduplicates_overlapping_windows():
    config = load_config(overrides={"window_seconds": 5.0, "candidate_stride_seconds": 1.0})
    frames = []
    for i in range(16):
        frame = _frame(i, speed=2.0)
        frame["ego"]["heading_lcs_rad"] = i * 0.17
        frames.append(frame)
    candidates = generate_candidates(_recording(frames), "starting_u_turn", config)
    assert len(candidates) == 1


def test_traffic_light_episode_candidate_positive_uses_topology_and_signal():
    config = load_config(overrides={"window_seconds": 5.0, "candidate_stride_seconds": 5.0, "max_bev_images": 6})
    topology = {"topology_class": "x-intersection", "topology_confidence": 0.8, "arm_count": 4}
    frames = [_frame(i, speed=2.0, objects=[_traffic_light()], topology=topology) for i in range(12)]
    candidates = generate_candidates(_recording(frames), "traffic_light_episode", config)
    assert candidates
    candidate = candidates[0]
    assert len(candidate.selected_frame_indices) == 6
    assert candidate.selected_frame_indices == sorted(candidate.selected_frame_indices)
    assert "relevant_od_traffic_light" in candidate.recall_reasons
    assert "derived_intersection_topology" in candidate.recall_reasons
    assert any(item.kind == "traffic_light_context" for item in candidate.evidence)


def test_traffic_light_episode_positive_without_topology_when_stopline_and_signal_are_relevant():
    config = load_config(overrides={"window_seconds": 5.0})
    frames = []
    for i in range(12):
        frame = _frame(i, speed=1.0, accel=-0.5, objects=[_traffic_light(x=18.0, y=0.5)], topology={"topology_class": "normal", "arm_count": 0})
        frame["traffic_light_context"] = _stopline_context(i, distance=12.0 - i)
        frames.append(frame)
    candidates = generate_candidates(_recording(frames), "traffic_light_episode", config)
    assert candidates
    evidence = next(item for item in candidates[0].evidence if item.kind == "traffic_light_context")
    assert any(item["topology"]["topology_missing"] for item in evidence.data["frames"])
    assert "associated_or_nearby_stopline" in candidates[0].recall_reasons


def test_traffic_light_episode_negative_for_unrelated_signal_without_path_or_stopline():
    config = load_config(overrides={"window_seconds": 5.0})
    frames = [_frame(i, speed=2.0, objects=[_traffic_light(x=15.0, y=30.0)], topology={"topology_class": "normal", "arm_count": 0}) for i in range(12)]
    assert generate_candidates(_recording(frames), "traffic_light_episode", config) == []


def test_traffic_light_episode_candidate_merges_adjacent_evidence_frames():
    config = load_config(overrides={"traffic_light_episode_merge_gap_s": 1.0})
    topology = {"topology_class": "x-intersection", "topology_confidence": 0.8, "arm_count": 4}
    frames = [_frame(i, speed=2.0, objects=[_traffic_light()], topology=topology) for i in range(16)]
    candidates = generate_candidates(_recording(frames), "traffic_light_episode", config)
    assert len(candidates) == 1


def test_traffic_light_episode_rejects_adjacent_lane_vehicle_as_lead():
    config = load_config(overrides={"window_seconds": 5.0})
    frame = _frame(0, speed=0.0, objects=[_traffic_light(x=18.0, y=0.5), _vehicle(y=3.5, same_lane=False)])
    frame["traffic_light_context"] = _stopline_context(0, distance=7.0)
    candidates = generate_candidates(_recording([frame]), "traffic_light_episode", config)
    evidence = next(item for item in candidates[0].evidence if item.kind == "traffic_light_context")
    assert evidence.data["frames"][0]["lead"]["exists"] is False


def test_traffic_light_episode_records_lead_when_same_path_evidence_exists():
    config = load_config(overrides={"window_seconds": 5.0})
    frame = _frame(0, speed=0.0, objects=[_traffic_light(x=18.0, y=0.5), _vehicle()])
    frame["traffic_light_context"] = _stopline_context(0, distance=7.0)
    candidates = generate_candidates(_recording([frame]), "traffic_light_episode", config)
    evidence = next(item for item in candidates[0].evidence if item.kind == "traffic_light_context")
    assert evidence.data["frames"][0]["lead"]["exists"] is True
    assert evidence.data["frames"][0]["lead"]["object_id"] == "veh-1"


def test_evidence_serialization_is_stable_shape():
    bundle = serialize_candidate_bundle(_candidate())
    assert bundle["schema_version"] == "qwen-vlm-poc-candidate-v1"
    assert bundle["candidate"]["evidence"][0]["evidence_id"] == "ev-1"
    json.dumps(bundle, sort_keys=True)


def test_response_validation_accepts_strict_positive():
    candidate = _candidate("waiting_for_pedestrian_to_cross")
    raw = {
        "recording_id": "rec-a",
        "window_start_frame": 0,
        "window_end_frame": 10,
        "scenario": "waiting_for_pedestrian_to_cross",
        "decision": True,
        "confidence": 0.9,
        "event_start_frame": 1,
        "event_end_frame": 8,
        "primary_object_ids": ["ped-1"],
        "evidence_ids": ["ev-1"],
        "reason": "Pedestrian conflicts with ego corridor and ego slows.",
        "ambiguities": [],
        "insufficient_evidence": False,
        "review_required": False,
    }
    result = parse_and_validate_response(json.dumps(raw), candidate, load_config())
    assert result.accepted
    assert result.decision is not None
    assert result.decision.primary_object_ids == ["ped-1"]


def test_response_validation_accepts_new_scenario_schema():
    for scenario in ("starting_u_turn",):
        candidate = _candidate(scenario)
        raw = {
            "recording_id": "rec-a",
            "window_start_frame": 0,
            "window_end_frame": 10,
            "scenario": scenario,
            "decision": True,
            "confidence": 0.9,
            "event_start_frame": 1,
            "event_end_frame": 8,
            "primary_object_ids": [],
            "evidence_ids": ["ev-1"],
            "reason": "Supplied evidence supports the scenario.",
            "ambiguities": [],
            "insufficient_evidence": False,
            "review_required": False,
        }
        result = parse_and_validate_response(json.dumps(raw), candidate, load_config())
        assert result.accepted


def _traffic_light_multilabel_raw(candidate, *, labels=None):
    all_labels = {
        "on_traffic_light_intersection": False,
        "on_stopline_traffic_light": False,
        "accelerating_at_traffic_light": False,
        "accelerating_at_traffic_light_with_lead": False,
        "accelerating_at_traffic_light_without_lead": False,
        "stationary_at_traffic_light_with_lead": False,
        "stationary_at_traffic_light_without_lead": False,
        "stopping_at_traffic_light_with_lead": False,
        "stopping_at_traffic_light_without_lead": False,
        "traversing_traffic_light_intersection": False,
        "starting_straight_traffic_light_intersection_traversal": False,
    }
    all_labels.update(labels or {})
    return {
        "recording_id": candidate.recording_id,
        "window_start_frame": candidate.start_frame,
        "window_end_frame": candidate.end_frame,
        "scenario": "traffic_light_episode",
        "traffic_light_context": True,
        "labels": all_labels,
        "confidence_by_label": {label: (0.9 if active else 0.0) for label, active in all_labels.items()},
        "event_frame_ranges": {
            label: {"start_frame": candidate.start_frame, "end_frame": candidate.end_frame}
            for label, active in all_labels.items()
            if active
        },
        "reason_by_label": {
            label: "Structured traffic-light episode evidence supports this label."
            for label, active in all_labels.items()
            if active
        },
        "evidence_ids_by_label": {
            label: ["ev-1"]
            for label, active in all_labels.items()
            if active
        },
        "ambiguities": [],
        "insufficient_evidence": False,
        "review_required": False,
    }


def test_traffic_light_episode_validation_accepts_multiple_output_tags():
    candidate = _candidate("traffic_light_episode")
    raw = _traffic_light_multilabel_raw(
        candidate,
        labels={
            "on_traffic_light_intersection": True,
            "stopping_at_traffic_light_with_lead": True,
        },
    )
    result = parse_and_validate_response(json.dumps(raw), candidate, load_config())
    assert result.accepted
    assert [decision.scenario for decision in result.decisions] == [
        "on_traffic_light_intersection",
        "stopping_at_traffic_light_with_lead",
    ]


def test_traffic_light_episode_validation_rejects_with_and_without_lead_together():
    candidate = _candidate("traffic_light_episode")
    raw = _traffic_light_multilabel_raw(
        candidate,
        labels={
            "stopping_at_traffic_light_with_lead": True,
            "stopping_at_traffic_light_without_lead": True,
        },
    )
    result = parse_and_validate_response(json.dumps(raw), candidate, load_config())
    assert not result.accepted
    assert any(reason.startswith("mutually_exclusive_labels") for reason in result.reasons)


def test_response_validation_rejects_wrong_new_scenario():
    candidate = _candidate("starting_u_turn")
    raw = {
        "recording_id": "rec-a",
        "window_start_frame": 0,
        "window_end_frame": 10,
        "scenario": "on_traffic_light_intersection",
        "decision": True,
        "confidence": 0.9,
        "event_start_frame": 1,
        "event_end_frame": 8,
        "primary_object_ids": [],
        "evidence_ids": ["ev-1"],
        "reason": "Wrong scenario.",
        "ambiguities": [],
        "insufficient_evidence": False,
        "review_required": False,
    }
    result = parse_and_validate_response(json.dumps(raw), candidate, load_config())
    assert not result.accepted
    assert "wrong_scenario" in result.reasons


def test_response_validation_rejects_malformed_wrong_evidence_and_missing_ped():
    malformed = parse_and_validate_response("not json", _candidate(), load_config())
    assert not malformed.accepted
    assert malformed.review_required
    candidate = _candidate("waiting_for_pedestrian_to_cross")
    raw = {
        "recording_id": "rec-a",
        "window_start_frame": 0,
        "window_end_frame": 10,
        "scenario": "waiting_for_pedestrian_to_cross",
        "decision": True,
        "confidence": 0.91,
        "event_start_frame": 0,
        "event_end_frame": 10,
        "primary_object_ids": [],
        "evidence_ids": ["missing"],
        "reason": "Unsupported.",
        "ambiguities": [],
        "insufficient_evidence": False,
        "review_required": False,
    }
    invalid = parse_and_validate_response(json.dumps(raw), candidate, load_config())
    assert not invalid.accepted
    assert "missing_pedestrian_ids" in invalid.reasons
    assert any(reason.startswith("nonexistent_evidence_ids") for reason in invalid.reasons)


def test_waiting_prompt_interprets_stationary_as_stopped():
    _, prompt = read_prompt("waiting_for_pedestrian_to_cross")
    assert '"stationary" MUST be interpreted as "stopped"' in prompt
    assert '"stationary" alone is NOT sufficient for a positive decision' in prompt
    assert "Ego is stationary, which satisfies the stopped condition" in prompt


def test_waiting_validation_reviews_stationary_not_stopped_contradiction():
    candidate = _candidate("waiting_for_pedestrian_to_cross")
    raw = {
        "recording_id": "rec-a",
        "window_start_frame": 0,
        "window_end_frame": 10,
        "scenario": "waiting_for_pedestrian_to_cross",
        "decision": False,
        "confidence": 0.8,
        "event_start_frame": None,
        "event_end_frame": None,
        "primary_object_ids": [],
        "evidence_ids": ["ev-1"],
        "reason": "Ego is stationary and not stopped or moving slowly.",
        "ambiguities": [],
        "insufficient_evidence": False,
        "review_required": False,
    }
    result = parse_and_validate_response(json.dumps(raw), candidate, load_config())
    assert not result.accepted
    assert result.review_required
    assert "inconsistent_negative_reason" in result.reasons


def test_on_intersection_validation_allows_clear_negative_not_inside_reason():
    candidate = _candidate("on_intersection")
    raw = {
        "recording_id": "rec-a",
        "window_start_frame": 0,
        "window_end_frame": 10,
        "scenario": "on_intersection",
        "decision": False,
        "confidence": 0.9,
        "event_start_frame": None,
        "event_end_frame": None,
        "primary_object_ids": [],
        "evidence_ids": ["ev-1"],
        "reason": "Ego is not inside the effective intersection footprint and is on an exit corridor.",
        "ambiguities": [],
        "insufficient_evidence": False,
        "review_required": False,
    }
    result = parse_and_validate_response(json.dumps(raw), candidate, load_config())
    assert "inconsistent_negative_reason" not in result.reasons


def test_on_intersection_prompt_forbids_false_with_inside_intersection_reason():
    _, prompt = read_prompt("on_intersection")
    assert "If your reason says ego is inside the effective intersection footprint" in prompt
    assert "decision MUST be true" in prompt
    assert "Never return decision=false with a reason that describes ego as inside an intersection" in prompt
    assert "blue/cyan circle around ego" in prompt
    assert "NOT an intersection footprint" in prompt
    assert "normal outbound corridors" in prompt
    assert "early/mid window" in prompt
    assert "inside/outside boundary is uncertain" in prompt
    assert "Do not reject the whole window only because later frames are exiting" in prompt
    assert "all selected BEV frames show ego outside" in prompt


def test_on_intersection_bev_rendering_omits_generic_proximity_circle(monkeypatch, tmp_path):
    calls = []

    def fake_render(*args, **kwargs):
        calls.append(kwargs)
        args[2].parent.mkdir(parents=True, exist_ok=True)
        args[2].write_bytes(b"png")

    monkeypatch.setattr(evidence_module, "render_revised_bev_png", fake_render)
    candidate = _candidate("on_intersection")
    candidate = CandidateWindow(
        **{
            **candidate.to_dict(),
            "evidence": candidate.evidence,
            "selected_frame_indices": [0],
        }
    )
    recording = _recording([_frame(0)])
    render_candidate_bevs(recording, candidate, tmp_path, load_config())
    assert calls[0]["proximity_radius_m"] == 0.0


def test_cache_key_includes_model_prompt_scenario_evidence_images_and_settings(tmp_path):
    image = tmp_path / "a.png"
    image.write_bytes(b"image-a")
    candidate = _candidate()
    candidate = CandidateWindow(**{**candidate.to_dict(), "evidence": candidate.evidence, "bev_paths": [str(image)]})
    config = load_config()
    key1 = cache_key(candidate, config)
    key2 = cache_key(candidate, load_config(overrides={"model": "other"}))
    image.write_bytes(b"image-b")
    key3 = cache_key(candidate, config)
    assert key1 != key2
    assert key1 != key3


def test_vlm_client_timeout_failure_does_not_raise(monkeypatch, tmp_path):
    def _raise(*args, **kwargs):
        raise urllib.error.URLError("timeout")

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    client = VlmClient(load_config(overrides={"retries": 0, "timeout_s": 0.01}), cache_dir=tmp_path)
    result = client.infer(_candidate())
    assert result["ok"] is False
    assert "timeout" in result["error"]


def test_temporal_merging_combines_overlapping_windows():
    rec = _recording([_frame(i) for i in range(20)])
    c1 = _candidate()
    c2 = CandidateWindow(**{**_candidate().to_dict(), "evidence": _candidate().evidence, "candidate_id": "c2", "start_frame": 8, "end_frame": 16})
    d1 = VlmDecision("rec-a", 0, 10, "on_intersection", True, 0.8, 1, 9, [], ["ev-1"], "a", [], False, False)
    d2 = VlmDecision("rec-a", 8, 16, "on_intersection", True, 0.9, 8, 15, [], ["ev-1"], "b", [], False, False)
    events = merge_decisions(rec, [(c1, d1), (c2, d2)], load_config())
    assert len(events) == 1
    assert events[0].start_frame == 1
    assert events[0].end_frame == 15
    assert events[0].confidence == 0.9


def test_traffic_light_episode_merging_emits_output_label_not_candidate_scenario():
    rec = _recording([_frame(i) for i in range(20)])
    candidate = _candidate("traffic_light_episode")
    decision = VlmDecision(
        "rec-a",
        0,
        10,
        "stopping_at_traffic_light_with_lead",
        True,
        0.91,
        2,
        9,
        [],
        ["ev-1"],
        "traffic light context, stopline, stopping ego, and same-path lead",
        [],
        False,
        False,
    )
    events = merge_decisions(rec, [(candidate, decision)], load_config())
    assert len(events) == 1
    assert events[0].scenario == "stopping_at_traffic_light_with_lead"
    assert events[0].evidence["candidate_ids"] == [candidate.candidate_id]
