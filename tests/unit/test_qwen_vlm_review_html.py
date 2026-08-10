from __future__ import annotations

import json
from pathlib import Path

from ms_odd_tagging.qwen_vlm_poc.review_html import build_review_html


def test_review_html_renders_waiting_candidate_and_vlm_decision(tmp_path: Path):
    bev = tmp_path / "bev" / "frame_000010.png"
    bev.parent.mkdir(parents=True)
    bev.write_bytes(b"png")

    candidate_id = "rec_waiting_for_pedestrian_to_cross_ped-1_000005_000020"
    bundle = tmp_path / "candidate.json"
    bundle.write_text(
        json.dumps(
            {
                "candidate": {
                    "candidate_id": candidate_id,
                    "recording_id": "rec",
                    "scenario": "waiting_for_pedestrian_to_cross",
                    "start_frame": 5,
                    "end_frame": 20,
                    "start_timestamp_s": 0.5,
                    "end_timestamp_s": 2.0,
                    "selected_frame_indices": [10],
                    "bev_paths": [str(bev)],
                    "primary_object_ids": ["ped-1"],
                    "recall_reasons": ["event_driven_pedestrian_corridor_conflict"],
                    "metadata": {
                        "candidate_strategy": "event-driven",
                        "pedestrian_id": "ped-1",
                        "raw_trigger_start_frame": 8,
                        "raw_trigger_end_frame": 18,
                        "landmark_roles": {"strongest_conflict": 10},
                    },
                    "evidence": [
                        {
                            "evidence_id": "ev-conflict",
                            "kind": "pedestrian_corridor_conflict",
                            "summary": "conflict",
                            "data": {
                                "motion": {
                                    "ped-1": {
                                        "pedestrian_motion_state": "moving",
                                        "pedestrian_speed_mps": 1.2,
                                        "pedestrian_displacement_m": 3.0,
                                        "lateral_velocity_mps": -0.8,
                                    }
                                }
                            },
                        },
                        {
                            "evidence_id": "ev-landmarks",
                            "kind": "event_landmarks",
                            "summary": "landmarks",
                            "data": {"roles": {"strongest_conflict": 10}},
                        },
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    manifest = tmp_path / "manifest_waiting.json"
    manifest.write_text(
        json.dumps(
            {
                "candidate_strategy": "event-driven",
                "candidate_bundles": [str(bundle)],
                "validation": [
                    {
                        "candidate_id": candidate_id,
                        "accepted": False,
                        "review_required": False,
                        "reasons": [],
                        "decision": {
                            "decision": False,
                            "confidence": 0.91,
                            "event_start_frame": None,
                            "event_end_frame": None,
                            "reason": "Pedestrian is nearby but ego response is not causally linked.",
                            "ambiguities": [],
                            "insufficient_evidence": False,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    output = build_review_html(manifest)
    text = output.read_text(encoding="utf-8")

    assert output.name == "manifest_waiting_review.html"
    assert "Waiting for pedestrian to cross" not in text  # adapter title is structural, candidate ID drives card heading
    assert candidate_id in text
    assert "strongest_conflict" in text
    assert "REJECTED" in text
    assert "0.910" in text
    assert "causally linked" in text
    assert "bev/frame_000010.png" in text
