from ms_odd_tagging.experiments.lane_debug_v2.exact_touch_reconciliation import (
    reconcile_exact_touch_tracks,
)


def _lane(lane_id, start, end, *, width_start=3.0, width_end=3.0, left_edge="L", right_edge="R"):
    # Straight fixture; endpoint widths can differ from downstream/whole-lane width.
    return {
        "lane_id": str(lane_id),
        "centerline_lcs_m": [list(start), list(end)],
        "left_boundary_lcs_m": [
            [start[0], start[1] + width_start / 2.0],
            [end[0], end[1] + width_end / 2.0],
        ],
        "right_boundary_lcs_m": [
            [start[0], start[1] - width_start / 2.0],
            [end[0], end[1] - width_end / 2.0],
        ],
        "left_edge_id": left_edge,
        "right_edge_id": right_edge,
        "polygon_lcs_m": [],
    }


def _track(track_id, lane):
    return {
        "track_id": track_id,
        "logical_lane_id": track_id,
        "member_lane_ids": [lane["lane_id"]],
        "median_width_m": 6.0,  # deliberately misleading whole-track width
        "pieces": [
            {
                "kind": "observed_ld",
                "lane_id": lane["lane_id"],
                "centerline_lcs_m": lane["centerline_lcs_m"],
                "polygon_lcs_m": lane["polygon_lcs_m"],
            }
        ],
        "centerline_lcs_m": lane["centerline_lcs_m"],
    }


def test_merges_exact_touch_using_local_endpoint_width_and_preserves_source_track_id():
    touch = [177.7728, 19.71365]
    lane_1790 = _lane("1790", [170.0, 19.5], touch, width_start=3.1, width_end=3.03, left_edge="11", right_edge="12")
    lane_1348 = _lane("1348", touch, [186.0, 19.95], width_start=3.03, width_end=6.5, left_edge="11", right_edge="12")

    tracks, debug = reconcile_exact_touch_tracks(
        [_track("physical_track_0007", lane_1790), _track("physical_track_0008", lane_1348)],
        [lane_1790, lane_1348],
    )

    assert [t["track_id"] for t in tracks] == ["physical_track_0007"]
    assert tracks[0]["member_lane_ids"] == ["1790", "1348"]
    accepted = [r for r in debug if r.get("action") == "merge_exact_touch_tracks_preserve_source_id"]
    assert len(accepted) == 1
    assert accepted[0]["centerline_endpoint_gap_m"] == 0.0
    assert accepted[0]["local_width_difference_m"] == 0.0
    assert accepted[0]["same_left_edge_id"] is True
    assert accepted[0]["same_right_edge_id"] is True


def test_ambiguous_exact_touch_fork_is_not_merged_without_unique_boundary_identity():
    touch = [10.0, 0.0]
    source_lane = _lane("A", [0.0, 0.0], touch, left_edge="srcL", right_edge="srcR")
    # Two geometrically equivalent destinations, neither continues the same boundary IDs.
    dest_b = _lane("B", touch, [20.0, 0.0], left_edge="bL", right_edge="bR")
    dest_c = _lane("C", touch, [20.0, 0.05], left_edge="cL", right_edge="cR")

    tracks, debug = reconcile_exact_touch_tracks(
        [_track("source", source_lane), _track("dest_b", dest_b), _track("dest_c", dest_c)],
        [source_lane, dest_b, dest_c],
    )

    assert {t["track_id"] for t in tracks} == {"source", "dest_b", "dest_c"}
    assert any(
        "ambiguous_fork_multiple_exact_touch_destinations" in (row.get("rejection_reasons") or [])
        for row in debug
    )
