from __future__ import annotations

import json
from pathlib import Path

from ms_odd_tagging.frame_inputs.recording_analysis_cache import get_recording_analysis
from ms_odd_tagging.tagger.rule_based.scenario_event import ScenarioEvent


def test_recording_analysis_cache_reuses_expensive_results(tmp_path: Path) -> None:
    canonical = tmp_path / "rec.json"
    canonical.write_text(json.dumps({"recording_id": "rec", "frames": []}), encoding="utf-8")
    recording = {"recording_id": "rec", "frames": []}
    recording_dir = tmp_path / "out" / "rec"
    calls = {"rules": 0, "lane": 0}

    def fake_rules(recording, config):
        calls["rules"] += 1
        return (
            [
                ScenarioEvent(
                    scenario="stationary",
                    start_frame=0,
                    end_frame=0,
                    start_timestamp_s=0.0,
                    end_timestamp_s=0.0,
                    duration_s=0.0,
                )
            ],
            {"ok": True},
        )

    def fake_lane(recording):
        calls["lane"] += 1
        return {"recording_id": "rec", "frames": []}

    first = get_recording_analysis(
        canonical_path=canonical,
        recording=recording,
        recording_dir=recording_dir,
        config={"config_version": "test"},
        detect_recording_events=fake_rules,
        run_following_lane=fake_lane,
    )
    second = get_recording_analysis(
        canonical_path=canonical,
        recording=recording,
        recording_dir=recording_dir,
        config={"config_version": "test"},
        detect_recording_events=fake_rules,
        run_following_lane=fake_lane,
    )

    assert first[3] is False
    assert second[3] is True
    assert calls == {"rules": 1, "lane": 1}
    assert second[0][0].scenario == "stationary"


def test_recording_analysis_cache_invalidates_when_canonical_content_changes(tmp_path: Path) -> None:
    canonical = tmp_path / "rec.json"
    canonical.write_text(json.dumps({"recording_id": "rec", "frames": []}), encoding="utf-8")
    recording_dir = tmp_path / "out" / "rec"
    calls = {"rules": 0, "lane": 0}

    def fake_rules(recording, config):
        calls["rules"] += 1
        return [], {}

    def fake_lane(recording):
        calls["lane"] += 1
        return {"recording_id": "rec", "frames": []}

    get_recording_analysis(
        canonical_path=canonical,
        recording={"recording_id": "rec", "frames": []},
        recording_dir=recording_dir,
        config={"config_version": "test"},
        detect_recording_events=fake_rules,
        run_following_lane=fake_lane,
    )

    canonical.write_text(
        json.dumps({"recording_id": "rec", "frames": [{"frame_index": 0}]}),
        encoding="utf-8",
    )
    get_recording_analysis(
        canonical_path=canonical,
        recording={"recording_id": "rec", "frames": [{"frame_index": 0}]},
        recording_dir=recording_dir,
        config={"config_version": "test"},
        detect_recording_events=fake_rules,
        run_following_lane=fake_lane,
    )

    assert calls == {"rules": 2, "lane": 2}
