from __future__ import annotations

import json
from pathlib import Path

from ms_odd_tagging.simplified_taxonomy.gt_workspace import (
    _dashboard_html,
    _prediction_tags,
)


def test_prediction_tags_supports_prediction_container_and_tag_variants(tmp_path: Path) -> None:
    path = tmp_path / "prediction.json"
    path.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "scenarios": ["starting_left_turn", {"scenario": "stationary"}],
                        "simplified_tags": {
                            "interaction_tags": ["pedestrian_crossing"],
                            "source_scenarios": ["near_multiple_pedestrians"],
                            "unmapped_scenarios": ["custom_scene"],
                        },
                    },
                    {"tagged_scenarios": [{"name": "following_lane_with_lead"}]},
                ]
            }
        ),
        encoding="utf-8",
    )

    assert _prediction_tags(path) == [
        "custom_scene",
        "following_lane_with_lead",
        "near_multiple_pedestrians",
        "pedestrian_crossing",
        "starting_left_turn",
        "stationary",
    ]


def test_dashboard_has_bulk_recording_selection_and_download() -> None:
    page = _dashboard_html()

    assert 'id="selectionCount"' in page
    assert 'id="selectVisible"' in page
    assert "decorateRecordingSelections" in page
    assert "recording-select" in page
    assert 'id="clearSelection"' in page
    assert 'id="exportRecordings"' in page
    assert "selectedRecordings=new Set" in page
    assert "selected_recordings.json" in page
    assert "setTimeout(()=>URL.revokeObjectURL(url),1000)" in page
