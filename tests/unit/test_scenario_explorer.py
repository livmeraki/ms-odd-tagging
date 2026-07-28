from __future__ import annotations

import json
from pathlib import Path

from ms_odd_tagging.visualization.scenario_explorer import (
    build_explorer_payload,
    generate_explorer,
)


def synthetic_source() -> dict:
    frames = []
    for index in range(21):
        frames.append(
            {
                "frame_index": index,
                "time_since_start_s": index * 0.1,
                "ego": {
                    "position_lcs_m": [index * 0.01, 0.0, 0.0],
                    "velocity_lcs_mps": [0.1, 0.0, 0.0],
                    "speed_mps": 0.1,
                    "acceleration_mps2": 0.0,
                    "heading_lcs_rad": 0.0,
                    "yaw_rate_radps": 0.0,
                },
                "objects": [],
            }
        )
    return {"recording_id": "synthetic", "frames": frames}


def test_build_explorer_payload_runs_rules() -> None:
    payload = build_explorer_payload(synthetic_source())
    assert payload["recording"] == "synthetic"
    assert payload["frameCount"] == 21
    assert [event["scenario"] for event in payload["events"]] == ["stationary"]


def test_generate_explorer_replaces_template(tmp_path: Path) -> None:
    payload = build_explorer_payload(synthetic_source())
    output = generate_explorer(payload, tmp_path / "explorer.html")
    page = output.read_text(encoding="utf-8")
    assert "<!doctype html>" in page
    assert "__SCENARIO_DATA__" not in page
    assert '"scenario":"stationary"' in page
    assert json.dumps(payload["recording"])[1:-1] in page
