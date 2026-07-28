from pathlib import Path

from ms_odd_tagging.scenarios.following_lane.explorer_visualization import (
    render_original_explorer_with_lane_tracker,
)


def test_original_explorer_receives_synchronized_lane_tracker(tmp_path: Path):
    base = tmp_path / "original.html"
    base.write_text(
        """<!doctype html><html><head><style></style></head><body>
<main><aside>
<label><input id="followEgo" type="checkbox" /> Follow ego with current zoom</label>
<label><input id="showNearbyLd" type="checkbox" checked /> Highlight current nearby LD</label>
    <div id="animControls">
</aside><section>
    <div class="panel"><div id="map"></div></div>
</section></main><script>
const DATA = {};
const DEBUG_BASE = `debug/${encodeURIComponent(DATA.summary.recording)}`;
const traj = {rel_t:[0]};
let currentIndex = 0;
function setFrame(index) {
  updateLdTimelineCursor();
}
function ldTraces(){return [];}
const intersectionStyle = ['LD line: intersection=true', '#d946ef', 'solid', 4.2, 0.82];
function render() {
  const traces = [];
  traces.unshift(...ldTraces());
}
filter.addEventListener('change', render);
renderTimeline();
renderLdTimeline();
</script></body></html>""",
        encoding="utf-8",
    )
    result = {
        "recording_id": "sample",
        "lane_geometry": [],
        "probable_lane_bridges": [],
        "intervals": [],
        "frames": [
            {
                "frame_index": 0,
                "time_since_start_s": 0.0,
                "state": "following_lane_without_lead",
                "reason": "no_stable_lead_in_ego_route_lane",
                "ego_lane": {
                    "logical_lane_id": "route_lane_0001",
                    "confidence": "high",
                    "method": "polygon_and_heading",
                },
                "left_lane": {"logical_lane_id": None},
                "right_lane": {"logical_lane_id": None},
                "lead": None,
            }
        ],
    }
    output = tmp_path / "combined.html"
    render_original_explorer_with_lane_tracker(base, result, output)
    page = output.read_text(encoding="utf-8")

    assert "const LANE_TRACKER =" in page
    assert 'id="showLaneTracker"' in page
    assert 'id="laneTrackerTimeline"' in page
    assert "traces.unshift(...laneTrackerTraces());" in page
    assert "updateLaneTrackerTimelineCursor();" in page
    assert "renderLaneTrackerTimeline();" in page
    assert 'id="showLdGapExtensions"' in page
    assert "const LD_GAP_EXTENSION_RESULT = buildLdGapExtensions();" in page
    assert "traces.unshift(...ldGapExtensionTraces());" in page
    assert "Experimental LD gap extensions are visualization-only." in page
    assert "Lane identifiers remain internal and are not drawn." in page
    assert f"const DEBUG_BASE = `{base.parent.as_uri()}/debug/" in page
    assert '<input id="followEgo" type="checkbox" checked />' in page
    assert '<input id="showNearbyLd" type="checkbox" />' in page
    assert "'LD line: intersection=true', '#d946ef', 'solid', 2.0, 0.82" in page
