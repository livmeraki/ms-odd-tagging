from ms_odd_tagging.experiments.lane_debug_v2.continuous_tracks_observed_first import (
    build_continuous_tracks,
)
from ms_odd_tagging.experiments.lane_debug_v2.observed_touch_graph import (
    build_observed_touch_graph,
)


def _lane(lane_id, x0, x1, *, right_edge_id="2653", left_edge_id=None, curvature_destination=None):
    width = 3.0
    y = 0.0
    lane = {
        "lane_id": str(lane_id),
        "assignment_valid": True,
        "intersection_connector": False,
        "left_edge_id": str(left_edge_id or f"L-{lane_id}"),
        "right_edge_id": str(right_edge_id),
        "left_boundary_lcs_m": [[x0, y + width / 2], [x1, y + width / 2]],
        "right_boundary_lcs_m": [[x0, y - width / 2], [x1, y - width / 2]],
        "centerline_lcs_m": [[x0, y], [x1, y]],
        "polygon_lcs_m": [
            [x0, y + width / 2],
            [x1, y + width / 2],
            [x1, y - width / 2],
            [x0, y - width / 2],
        ],
        "curvature_continuations": [],
    }
    if curvature_destination is not None:
        lane["curvature_continuations"] = [{
            "destination_lane_id": str(curvature_destination),
            "projected_centerline_lcs_m": [[x1, y], [x1 + 5.0, y]],
            "inferred_gap_polygon_lcs_m": [],
            "accepted_candidate": {
                "score": 1.0,
                "gap_m": 5.0,
                "rejection_reasons": [],
            },
        }]
    return lane


def test_observed_exact_touches_beat_leapfrog_inferred_gaps():
    lanes = [
        _lane("3502", 0.0, 10.0, curvature_destination="2779"),
        _lane("2777", 10.05, 20.0, curvature_destination="2716"),
        _lane("2779", 20.0, 30.0),
        _lane("2716", 30.0, 40.0),
    ]
    # Make the small 3502→2777 boundary gaps match the center touch closely.
    lanes[0]["left_boundary_lcs_m"][-1] = [10.0, 1.5]
    lanes[0]["right_boundary_lcs_m"][-1] = [10.0, -1.5]
    lanes[1]["left_boundary_lcs_m"][0] = [10.05, 1.5]
    lanes[1]["right_boundary_lcs_m"][0] = [10.05, -1.5]

    tracks, member_map, debug = build_continuous_tracks(lanes, {"frames": []})

    assert len(tracks) == 1
    track = tracks[0]
    assert track["member_lane_ids"] == ["3502", "2777", "2779", "2716"]
    assert track["inferred_gap_count"] == 0
    assert track["observed_exact_touch_edge_count"] == 3
    assert len(set(member_map.values())) == 1
    assert any(
        row.get("source") == "3502"
        and row.get("destination") == "2779"
        and row.get("rejection_reason") == "observed_exact_touch_has_priority"
        for row in debug
    )
    assert any(
        row.get("source") == "2777"
        and row.get("destination") == "2716"
        and row.get("rejection_reason") == "observed_exact_touch_has_priority"
        for row in debug
    )


def test_ambiguous_exact_touch_fork_is_not_selected():
    source = _lane("A", 0.0, 10.0, right_edge_id="shared", left_edge_id="left-source")
    b = _lane("B", 10.0, 20.0, right_edge_id="shared", left_edge_id="left-b")
    c = _lane("C", 10.0, 20.0, right_edge_id="shared", left_edge_id="left-c")

    selected, debug = build_observed_touch_graph([source, b, c])

    assert "A" not in selected
    rows = [r for r in debug if r.get("source_lane_id") == "A"]
    assert len([r for r in rows if "ambiguous_fork_multiple_observed_touch_destinations" in r.get("rejection_reasons", [])]) == 2
