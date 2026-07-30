from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts" / "odld_explorer"
sys.path.insert(0, str(SCRIPT_DIR))

from add_gt_comparison_to_tagged_explorers import (  # noqa: E402
    inject,
    inject_authoring,
)


def test_inject_adds_gt_panel_without_replacing_existing_timeline(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    page = """<title>Original</title><style></style>
    <div class="panel"><div id="tagTimeline"></div></div>
    <div class="panel"><div id="laneTrackerTimeline"></div></div>
<script>
const DEBUG_BASE = `debug/${encodeURIComponent(DATA.summary.recording)}`;
const DATA = {};
function setFrame() {
  updateTagTimelineCursor();
}
renderTagTimeline();
</script>"""
    summary = {
        "exact_match_accuracy": 0.5,
        "label_metrics": [{"label": "stationary"}],
    }
    result = inject(
        page,
        "rec",
        [{"frameIndex": 10, "time": 1.0, "label": "stationary", "expected": True, "actual": True, "outcome": "tp"}],
        summary,
        {"status": "valid"},
        source_dir,
    )
    assert result.count('id="tagTimeline"') == 1
    assert result.count('id="gtComparisonTimeline"') == 1
    assert result.count('id="laneTrackerTimeline"') == 1
    assert "attachSharedTimeAxis('laneTrackerTimeline');" in result
    assert "renderGtComparison();" in result
    assert "updateGtComparisonCursor();" in result
    assert 'id="gtAuthoringPanel"' not in result


def test_inject_can_add_synchronized_gt_authoring_panel(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    page = """<title>Original</title><style></style>
    <div class="panel"><div id="laneTrackerTimeline"></div></div>
    <div class="panel"><div id="map"></div></div>
    <div class="panel"><div id="tagTimeline"></div></div>
<script>
const DEBUG_BASE = `debug/${encodeURIComponent(DATA.summary.recording)}`;
const DATA = {};
function setFrame() {
  updateTagTimelineCursor();
}
renderTagTimeline();
</script>"""
    summary = {
        "exact_match_accuracy": 0.5,
        "label_metrics": [{"label": "stationary"}],
    }
    authoring_payload = {
        "schema_version": "scenario-frame-gt-review-v1",
        "recording_id": "rec",
        "download_filename": "rec_frame_gt.json",
        "taxonomy": ["stationary", "low_magnitude_speed"],
        "scenario_groups": [
            {
                "id": "motion",
                "label": "motion",
                "implemented": True,
                "scenarios": ["stationary", "low_magnitude_speed"],
            }
        ],
        "minimum_scored_frame_index": 5,
        "gt": {
            "schema_version": "scenario-frame-gt-labels-v1",
            "recording_id": "rec",
            "formula_filled_label_fields": [],
            "frames": {
                "rec:frame-000005": {
                    "frame_index": 5,
                    "labels": {"stationary": None, "low_magnitude_speed": True},
                    "needs_review": True,
                    "excluded_from_evaluation": False,
                }
            },
        },
        "review_frames": [
            {
                "frame_id": "rec:frame-000005",
                "frame_index": 5,
                "derivation": {"active_labels": ["low_magnitude_speed"]},
            }
        ],
    }
    result = inject(
        page,
        "rec",
        [{"frameIndex": 10, "time": 1.0, "label": "stationary", "expected": True, "actual": True, "outcome": "tp"}],
        summary,
        {"status": "valid"},
        source_dir,
        authoring_payload,
    )
    assert 'id="gtAuthoringPanel"' in result
    assert 'class="gtAuthoringWorkspace"' in result
    assert result.index('id="map"') < result.index('id="gtAuthoringPanel"')
    assert result.index('id="gtAuthoringPanel"') < result.index('id="tagTimeline"')
    assert "const GT_AUTHORING =" in result
    assert "gtAuthoringByFrameIndex" in result
    assert "gtAuthoringInitialize();" in result
    assert "gtAuthoringRender();" in result
    assert "ms-odd-frame-gt:${GT_AUTHORING.recording_id}" in result
    assert "Download JSON" in result
    assert "Add current frame" in result
    assert "gtAuthoringAddCurrentFrame" in result
    assert "selectedScenarios" in result
    assert "groupOpen" in result
    assert "window.name" in result


def test_authoring_only_duplicate_preserves_recent_explorer_debugger(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    page = """<title>Original</title><style></style>
    <div class="panel"><div id="laneTrackerTimeline"></div></div>
    <div class="panel"><div id="map"></div></div>
    <div class="panel"><div id="tagTimeline"></div></div>
<script>
const DEBUG_BASE = `debug/${encodeURIComponent(DATA.summary.recording)}`;
const DATA = {};
function setFrame() {
  updateTagTimelineCursor();
}
renderTagTimeline();
</script>"""
    payload = {
        "recording_id": "rec",
        "download_filename": "rec_frame_gt.json",
        "taxonomy": ["stationary"],
        "scenario_groups": [
            {
                "id": "motion",
                "label": "motion",
                "implemented": True,
                "scenarios": ["stationary"],
            }
        ],
        "minimum_scored_frame_index": 5,
        "gt": {
            "schema_version": "scenario-frame-gt-labels-v1",
            "recording_id": "rec",
            "formula_filled_label_fields": ["stationary"],
            "frames": {},
        },
        "review_frames": [],
    }
    result = inject_authoring(page, "rec", payload, source_dir)
    assert result.count('id="tagTimeline"') == 1
    assert result.count('id="map"') == 1
    assert result.count('id="laneTrackerTimeline"') == 1
    assert 'class="panel gtRemovedLaneTrackerTimeline"' in result
    assert result.count('id="gtAuthoringPanel"') == 1
    assert 'class="gtAuthoringWorkspace"' in result
    assert result.index('id="map"') < result.index('id="gtAuthoringPanel"')
    assert result.index('id="gtAuthoringPanel"') < result.index('id="tagTimeline"')
    assert "GT comparison" not in result
    assert "gtAuthoringInitialize();" in result
    assert "Add current frame" in result
