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
                    "lane_id": "ego-physical",
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
    assert 'id="showLaneTrackerAdjacent" type="checkbox" checked />' in page
    assert 'id="showLaneTrackerRoutes"' in page
    assert 'id="laneTrackerTimeline"' not in page
    assert "traces.unshift(...laneTrackerTraces());" in page
    assert "function trackerPhysicalPolygonTrace" in page
    assert "lane.lane_id !== assignment.lane_id" in page
    assert "showLaneTrackerAdjacent" in page
    assert "roles.unshift(['left', frame.left_lane]);" in page
    assert "function trackerEgoRouteTrace" in page
    assert "ego logical route context" in page
    assert "updateLaneTrackerTimelineCursor();" not in page
    assert "renderLaneTrackerTimeline();" not in page
    assert 'id="showLdGapExtensions"' in page
    assert "const LD_GAP_EXTENSION_RESULT = buildLdGapExtensions();" in page
    assert "traces.unshift(...ldGapExtensionTraces());" in page
    assert "Experimental LD gap extensions are visualization-only." in page
    assert "Lane identifiers remain internal and are not drawn." in page
    assert f"const DEBUG_BASE = `{base.parent.as_uri()}/debug/" in page
    assert '<input id="followEgo" type="checkbox" checked />' in page
    assert '<input id="showNearbyLd" type="checkbox" />' in page
    assert "'LD line: intersection=true', '#d946ef', 'solid', 2.0, 0.82" in page


def test_lane_tracker_active_highlight_uses_physical_lane_id(tmp_path: Path):
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
        "lane_geometry": [
            {
                "lane_id": "ego-physical",
                "logical_lane_id": "route_lane_0001",
                "polygon_lcs_m": [[0, 0], [1, 0], [1, 1]],
                "centerline_lcs_m": [[0, 0], [1, 1]],
            },
            {
                "lane_id": "rejected-right",
                "logical_lane_id": "route_lane_0001",
                "polygon_lcs_m": [[0, -2], [1, -2], [1, -1]],
                "centerline_lcs_m": [[0, -2], [1, -1]],
            },
            {
                "lane_id": "left-physical",
                "logical_lane_id": "route_lane_0002",
                "polygon_lcs_m": [[0, 2], [1, 2], [1, 3]],
                "centerline_lcs_m": [[0, 2], [1, 3]],
            },
        ],
        "probable_lane_bridges": [
            {"logical_lane_id": "route_lane_0001", "polygon_lcs_m": [[2, 0], [3, 0], [3, 1]]}
        ],
        "intervals": [],
        "frames": [
            {
                "frame_index": 0,
                "time_since_start_s": 0.0,
                "state": "following_lane_without_lead",
                "reason": "no_stable_lead_in_ego_route_lane",
                "ego_lane": {
                    "lane_id": "ego-physical",
                    "logical_lane_id": "route_lane_0001",
                    "confidence": "high",
                    "method": "polygon_and_heading",
                },
                "left_lane": {
                    "lane_id": "left-physical",
                    "logical_lane_id": "route_lane_0002",
                },
                "right_lane": {
                    "lane_id": None,
                    "logical_lane_id": None,
                    "rejected_lane_id": "rejected-right",
                    "method": "same_route_lane_as_ego_rejected",
                    "confidence": "unknown",
                },
                "lead": None,
            }
        ],
    }
    output = tmp_path / "combined.html"
    render_original_explorer_with_lane_tracker(base, result, output)
    page = output.read_text(encoding="utf-8")

    assert "lane.lane_id !== assignment.lane_id" in page
    assert "lane.logical_lane_id !== assignment.logical_lane_id" in page
    assert "lane.lane_id === assignment.lane_id" in page
    assert "showLaneTrackerRoutes" in page
    assert "showLaneTrackerAdjacent" in page
    assert "active ego physical:" in page
    assert "same_route_lane_as_ego_rejected" in page
