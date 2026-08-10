from __future__ import annotations

import json
from pathlib import Path

from ms_odd_tagging.qwen_vlm_poc.candidate_explorer import build_candidate_explorer


def test_candidate_explorer_renders_merged_scene(tmp_path: Path):
    bev1 = tmp_path / "bev" / "frame_000010.png"
    bev2 = tmp_path / "bev" / "frame_000020.png"
    bev1.parent.mkdir(parents=True)
    bev1.write_bytes(b"png")
    bev2.write_bytes(b"png")

    bundle = tmp_path / "candidate.json"
    bundle.write_text(
        json.dumps(
            {
                "candidate": {
                    "candidate_id": "rec_waiting_scene_000005_000025",
                    "recording_id": "rec",
                    "scenario": "waiting_for_pedestrian_to_cross",
                    "start_frame": 5,
                    "end_frame": 25,
                    "start_timestamp_s": 0.5,
                    "end_timestamp_s": 2.5,
                    "selected_frame_indices": [10, 20],
                    "bev_paths": [str(bev1), str(bev2)],
                    "primary_object_ids": ["ped-1", "ped-2"],
                    "recall_reasons": ["scene_level_event_candidate"],
                    "evidence": [],
                    "metadata": {
                        "candidate_strategy": "event-driven",
                        "scene_merged": True,
                        "raw_trigger_start_frame": 8,
                        "raw_trigger_end_frame": 22,
                        "source_candidate_count": 2,
                        "source_candidate_ids": ["source-a", "source-b"],
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    manifest = tmp_path / "manifest_candidate_only_waiting.json"
    manifest.write_text(
        json.dumps(
            {
                "candidate_strategy": "event-driven",
                "candidate_bundles": [str(bundle)],
            }
        ),
        encoding="utf-8",
    )

    output = build_candidate_explorer(manifest)
    text = output.read_text(encoding="utf-8")

    assert output.name == "manifest_candidate_only_waiting_candidates.html"
    assert "Candidate Explorer" in text
    assert "MERGED SCENE" in text
    assert "raw 8–22" in text
    assert "ped-1, ped-2" in text
    assert "Source candidates (2)" in text
    assert "bev/frame_000010.png" in text
