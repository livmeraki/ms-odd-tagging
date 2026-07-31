import json
from pathlib import Path

import pytest

from ms_odd_tagging.lanelet2_poc.config import load_config
from ms_odd_tagging.lanelet2_poc.runner import run_recording


REAL_RECORDING = Path(
    "outputs/01_canonical/"
    "Rec_Drv_GER_MACHET18_20260319_144819_canonical_odld_frames.json"
)


@pytest.mark.skipif(not REAL_RECORDING.is_file(), reason="real canonical recording not present")
def test_real_recording_frame_is_ingested_in_lcs():
    recording = json.loads(REAL_RECORDING.read_text(encoding="utf-8"))
    config = load_config(
        overrides={"feature_enabled": True, "require_lanelet2": False}
    )
    result = run_recording(recording, config, frame_indices={0})

    assert result["recording_id"] == "Rec_Drv_GER_MACHET18_20260319_144819"
    assert result["coordinate_system"] == "LCS"
    assert len(result["frames"]) == 1
    frame = result["frames"][0]
    assert frame["frame_index"] == 0
    assert frame["status"] == "matched"
    assert frame["ego_lane"]["exists"] is True
    assert frame["candidate_lanelets"]
    assert "rejections" in frame
