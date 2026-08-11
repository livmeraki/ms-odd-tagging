from ms_odd_tagging.experiments.lane_debug_v2.static_inferred_affiliation import (
    assign_static_inferred_affiliations,
)


def _lane(lane_id, x0, x1, y=0.0, width=3.5):
    half = width / 2.0
    return {
        "lane_id": lane_id,
        "assignment_valid": True,
        "centerline_lcs_m": [[x0, y], [(x0 + x1) / 2.0, y], [x1, y]],
        "left_boundary_lcs_m": [[x0, y + half], [x1, y + half]],
        "right_boundary_lcs_m": [[x0, y - half], [x1, y - half]],
        "polygon_lcs_m": [[x0, y + half], [x1, y + half], [x1, y - half], [x0, y - half]],
    }


def _track(track_id, lane, median_width=3.5):
    return {
        "track_id": track_id,
        "centerline_lcs_m": lane["centerline_lcs_m"],
        "median_width_m": median_width,
        "member_lane_ids": [lane["lane_id"]],
        "pieces": [{
            "kind": "observed_ld",
            "lane_id": lane["lane_id"],
            "centerline_lcs_m": lane["centerline_lcs_m"],
            "polygon_lcs_m": lane["polygon_lcs_m"],
        }],
    }


def _inferred():
    return {
        "static_inferred_lane_id": "static_inferred_ego_route_0001",
        "route_id": "inferred_ego_route_0001",
        "start_observed_track_id": "wrong_temporal_track",
        "end_observed_track_id": "wrong_temporal_track",
        "bridge_complete": True,
        "centerline_lcs_m": [[10.0, 0.0], [15.0, 0.0], [20.0, 0.0]],
        "left_boundary_lcs_m": [[10.0, 1.75], [15.0, 1.75], [20.0, 1.75]],
        "right_boundary_lcs_m": [[10.0, -1.75], [15.0, -1.75], [20.0, -1.75]],
        "polygon_lcs_m": [[10.0, 1.75], [20.0, 1.75], [20.0, -1.75], [10.0, -1.75]],
        "median_width_m": 3.5,
    }


def test_affiliation_selects_longitudinal_before_after_not_adjacent_parallel():
    back = _lane("back_lane", 0.0, 9.0, 0.0)
    front = _lane("front_lane", 21.0, 30.0, 0.0)
    adjacent_back = _lane("adjacent_back_lane", 0.0, 9.5, 3.5)
    adjacent_front = _lane("adjacent_front_lane", 20.5, 30.0, 3.5)
    lanes = [back, front, adjacent_back, adjacent_front]
    tracks = [
        _track("back", back),
        _track("front", front),
        _track("adjacent_back", adjacent_back),
        _track("adjacent_front", adjacent_front),
    ]
    resolved, debug = assign_static_inferred_affiliations(
        [_inferred()],
        tracks,
        lanes,
        maximum_endpoint_distance_m=10.0,
        maximum_boundary_endpoint_distance_m=10.0,
        maximum_lateral_error_m=2.0,
        maximum_heading_difference_deg=20.0,
    )
    lane = resolved[0]
    assert lane["start_observed_track_id"] == "back"
    assert lane["end_observed_track_id"] == "front"
    assert lane["affiliation_method"] == "local_boundary_aware_longitudinal_endpoint_continuation_no_adjacency"
    assert lane["bridge_complete"] is True
    assert debug[0]["method"] == "local_boundary_aware_longitudinal_endpoint_continuation_no_adjacency"
    rejected = debug[0]["back_candidates"] + debug[0]["front_candidates"]
    adjacent = [x for x in rejected if x["track_id"].startswith("adjacent")]
    assert adjacent
    assert any("lateral_error_adjacent_or_parallel" in x["rejection_reasons"] for x in adjacent)


def test_affiliation_does_not_trust_remembered_temporal_ids():
    back = _lane("back_lane", 0.0, 9.0)
    front = _lane("front_lane", 21.0, 30.0)
    resolved, debug = assign_static_inferred_affiliations(
        [_inferred()],
        [_track("back", back), _track("front", front)],
        [back, front],
    )
    assert resolved[0]["start_observed_track_id"] == "back"
    assert resolved[0]["end_observed_track_id"] == "front"
    assert debug[0]["remembered_start_track_id"] == "wrong_temporal_track"
    assert debug[0]["remembered_end_track_id"] == "wrong_temporal_track"
