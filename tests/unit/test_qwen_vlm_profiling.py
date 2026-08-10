from __future__ import annotations

import json
import time
from pathlib import Path

from ms_odd_tagging.qwen_vlm_poc.profiling import RunProfiler


def test_run_profiler_records_context_aggregates_and_json(tmp_path: Path):
    profiler = RunProfiler()

    with profiler.measure("candidate_generation", recording_id="rec-a"):
        time.sleep(0.001)
    profiler.record("vlm_inference", 1.25, recording_id="rec-a", candidate_id="cand-1")
    profiler.record("vlm_inference", 0.75, recording_id="rec-a", candidate_id="cand-2")

    summary = profiler.summary()
    assert summary["candidate_generation"]["count"] == 1
    assert summary["candidate_generation"]["total_s"] > 0
    assert summary["vlm_inference"] == {
        "count": 2,
        "total_s": 2.0,
        "avg_s": 1.0,
        "min_s": 0.75,
        "max_s": 1.25,
    }

    path = profiler.write(tmp_path / "timing.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "qwen-vlm-poc-timing-v1"
    assert payload["total_elapsed_s"] >= 0
    assert payload["samples"][1]["candidate_id"] == "cand-1"
    assert payload["samples"][2]["candidate_id"] == "cand-2"
