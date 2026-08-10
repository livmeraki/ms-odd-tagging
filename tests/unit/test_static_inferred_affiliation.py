from ms_odd_tagging.experiments.lane_debug_v2.static_inferred_affiliation import (
    assign_static_inferred_affiliations,
)


def _track(track_id, x0, x1, y=0.0, width=3.5):
    return {
        "track_id": track_id,
        "centerline_lcs_m": [[x0, y], [(x0 + x1) / 2.0, y], [x1, y]],
        "median_width_m": width,
        "pieces": [],
    }


def _inferred():
    return {
        "static_inferred_lane_id": "static_inferred_ego_route_0001",
        "route_id": "inferred_ego_route_0001",
        "start_observed_track_id": "wrong_temporal_track",
        "end_observed_track_id": "wrong_temporal_track",
        "bridge_complete": True,
        "centerline_lcs_m": [[10.0, 0.0], [15.0, 0.0], [20.0, 0.0]],
        "median_width_m": 3.5,
    }


def test_affiliation_selects_longitudinal_before_after_not_adjacent_parallel():
    tracks = [
        _track("back", 0.0, 9.0, 0.0),
        _track("front", 21.0, 30.0, 0.0),
        # These are spatially close but in the adjacent lane.  The 3.5 m
        # lateral offset must reject them for inferred-lane affiliation.
        _track("adjacent_back", 0.0, 9.5, 3.5),
        _track("adjacent_front", 20.5, 30.0, 3.5),
    ]
    resolved, debug = assign_static_inferred_affiliations(
        [_inferred()],
        tracks,
        maximum_endpoint_distance_m=10.0,
        maximum_lateral_error_m=2.0,
        maximum_heading_difference_deg=20.0,
    )
    lane = resolved[0]
    assert lane["start_observed_track_id"] == "back"
    assert lane["end_observed_track_id"] == "front"
    assert lane["affiliation_method"] == "longitudinal_endpoint_continuation_no_adjacency"
    assert lane["bridge_complete"] is True
    assert debug[0]["method"] == "longitudinal_endpoint_continuation_no_adjacency"
    rejected = debug[0]["back_candidates"] + debug[0]["front_candidates"]
    adjacent = [x for x in rejected if x["track_id"].startswith("adjacent")]
    assert adjacent
    assert any("lateral_error_adjacent_or_parallel" in x["rejection_reasons"] for x in adjacent)


def test_affiliation_does_not_trust_remembered_temporal_ids():
    resolved, debug = assign_static_inferred_affiliations(
        [_inferred()],
        [_track("back", 0.0, 9.0), _track("front", 21.0, 30.0)],
    )
    assert resolved[0]["start_observed_track_id"] == "back"
    assert resolved[0]["end_observed_track_id"] == "front"
    assert debug[0]["remembered_start_track_id"] == "wrong_temporal_track"
    assert debug[0]["remembered_end_track_id"] == "wrong_temporal_track"
