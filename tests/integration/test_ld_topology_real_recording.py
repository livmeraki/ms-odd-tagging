from __future__ import annotations

import json
from pathlib import Path

import pytest

from ms_odd_tagging.ld_topology.pipeline import classify_recording


DATA_ROOT = Path("/media/stradvision/25eb199d-ae8a-49d6-b7e9-675eb144ddcd/ms-odd-tagging-data")
RECORDING = "Rec_Drv_GER_MACHET18_20260319_144819"


def test_ld_topology_real_recording_smoke():
    source = DATA_ROOT / "outputs" / "01_canonical" / f"{RECORDING}_canonical_odld_frames.json"
    if not source.is_file():
        pytest.skip(f"external canonical recording is not available: {source}")
    recording = json.loads(source.read_text(encoding="utf-8"))
    recording["frames"] = recording.get("frames", [])[:20]
    result = classify_recording(recording)
    assert result["parse"]["source_lane_count"] > 0
    assert result["parse"]["valid_lane_count"] > 0
    assert len(result["frames"]) == 20
    assert all(
        frame["topology_class"]
        in {"normal", "intersection_unknown", "x-intersection", "y-intersection", "t-intersection", "roundabout"}
        for frame in result["frames"]
    )
    assert result["intersection_geometry_source"].startswith("lanes.lines[]")
