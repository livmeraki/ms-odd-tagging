from ms_odd_tagging.experiments.lane_debug_v2.continuous_tracks_observed_first import (
    build_continuous_tracks,
)
from ms_odd_tagging.experiments.lane_debug_v2.observed_local_affiliation import (
    build_observed_local_affiliation_graph,
)


def _lane(lane_id, x0, x1, y=0.0, left_edge=None, right_edge=None):
    return {
        "lane_id": str(lane_id),
        "assignment_valid": True,
        "intersection_connector": False,
        "centerline_lcs_m": [[x0, y], [x0 + 3.0, y], [x0 + 6.0, y], [x1, y]],
        "left_boundary_lcs_m": [[x0, y + 1.5], [x0 + 3.0, y + 1.5], [x0 + 6.0, y + 1.5], [x1, y + 1.5]],
        "right_boundary_lcs_m": [[x0, y - 1.5], [x0 + 3.0, y - 1.5], [x0 + 6.0, y - 1.5], [x1, y - 1.5]],
        "polygon_lcs_m": [[x0, y + 1.5], [x1, y + 1.5], [x1, y - 1.5], [x0, y - 1.5]],
        "left_edge_id": left_edge,
        "right_edge_id": right_edge,
        "curvature_continuations": [],
    }


def test_fragmented_observed_lanes_integrate_by_local_interior_affiliation():
    back = _lane("back", 0.0, 10.0, left_edge="L", right_edge="R")
    front = _lane("front", 14.0, 24.0, left_edge="L", right_edge="R")

    selected, debug = build_observed_local_affiliation_graph([back, front])

    assert selected["back"]["destination_lane_id"] == "front"
    assert selected["back"]["interior_geometry_method"] == "interior_only_3m_4p5m_6m_window"
    assert selected["back"]["center_gap_m"] == 4.0
    assert selected["back"]["eligible"] is True
    assert any(row.get("source_lane_id") == "back" and row.get("accepted") for row in debug)

    tracks, member_map, connection_debug = build_continuous_tracks([back, front], {"frames": []})

    assert len(tracks) == 1
    track = tracks[0]
    assert track["member_lane_ids"] == ["back", "front"]
    assert track["observed_local_affiliation_edge_count"] == 1
    stitches = [p for p in track["pieces"] if p.get("kind") == "canonical_track_stitch"]
    assert len(stitches) == 1
    assert stitches[0]["connection_method"] == "observed_fragment_local_interior_endpoint_affiliation"
    assert member_map["back"] == member_map["front"] == track["track_id"]
    assert any(
        row.get("debug_stage") == "observed_local_affiliation"
        and row.get("source_lane_id") == "back"
        for row in connection_debug
    )


def test_ambiguous_fragment_fork_is_not_integrated():
    source = _lane("source", 0.0, 10.0)
    candidate_a = _lane("candidate_a", 14.0, 24.0)
    candidate_b = _lane("candidate_b", 14.0, 24.0)

    selected, debug = build_observed_local_affiliation_graph(
        [source, candidate_a, candidate_b],
        minimum_unique_score_margin=0.75,
    )

    assert "source" not in selected
    source_rows = [row for row in debug if row.get("source_lane_id") == "source"]
    assert source_rows
    assert any(
        "ambiguous_multiple_local_continuations" in (row.get("rejection_reasons") or [])
        for row in source_rows
    )
