from __future__ import annotations

import json
import urllib.error

from ms_odd_tagging.qwen_vlm_poc.candidates import (
    generate_candidates,
    pedestrian_corridor_conflict,
)
from ms_odd_tagging.qwen_vlm_poc.client import VlmClient, cache_key
from ms_odd_tagging.qwen_vlm_poc.config import load_config
from ms_odd_tagging.qwen_vlm_poc.evidence import serialize_candidate_bundle
from ms_odd_tagging.qwen_vlm_poc.merging import merge_decisions
from ms_odd_tagging.qwen_vlm_poc.models import CandidateWindow, EvidenceItem, VlmDecision
from ms_odd_tagging.qwen_vlm_poc.validation import parse_and_validate_response


def _frame(index: int, *, speed=0.0, accel=0.0, objects=None, topology=None, roadmarks=None):
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
        "ld": {"nearby_feature_ids": {"lane_lines": ["l", "r"], "roadmarks": roadmarks or []}},
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


def test_waiting_candidate_generation_uses_pedestrian_conflict_and_ego_response():
    config = load_config(overrides={"window_seconds": 5.0, "candidate_stride_seconds": 5.0})
    rec = _recording([_frame(i, speed=0.4, accel=-0.5, objects=[_ped()]) for i in range(12)])
    candidates = generate_candidates(rec, "waiting_for_pedestrian_to_cross", config)
    assert candidates
    assert candidates[0].primary_object_ids == ["ped-1"]
    assert "pedestrian_corridor_conflict" in candidates[0].recall_reasons


def test_waiting_candidate_negative_for_proximity_without_response():
    config = load_config(overrides={"window_seconds": 5.0})
    rec = _recording([_frame(i, speed=8.0, accel=0.0, objects=[_ped()]) for i in range(12)])
    assert generate_candidates(rec, "waiting_for_pedestrian_to_cross", config) == []


def test_intersection_candidate_uses_footprint_connectivity():
    config = load_config(overrides={"window_seconds": 5.0, "candidate_stride_seconds": 5.0})
    topology = {"topology_class": "x-intersection", "topology_confidence": 0.8, "arm_count": 4}
    rec = _recording([_frame(i, speed=3.0, topology=topology) for i in range(12)])
    candidates = generate_candidates(rec, "on_intersection", config)
    assert candidates
    evidence = candidates[0].evidence[1].data["frames"]
    assert evidence[0]["topology_class"] == "x-intersection"
    assert evidence[0]["external_corridor_count"] == 4


def test_intersection_candidate_negative_for_ordinary_curve_and_merge_split():
    config = load_config(overrides={"window_seconds": 5.0})
    curve = _recording([_frame(i, topology={"topology_class": "normal", "arm_count": 0}) for i in range(12)])
    split = _recording([_frame(i, topology={"topology_class": "normal", "arm_count": 2}) for i in range(12)])
    assert generate_candidates(curve, "on_intersection", config) == []
    assert generate_candidates(split, "on_intersection", config) == []


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

