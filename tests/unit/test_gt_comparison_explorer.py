from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts" / "odld_explorer"
sys.path.insert(0, str(SCRIPT_DIR))

from add_gt_comparison_to_tagged_explorers import inject  # noqa: E402


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
