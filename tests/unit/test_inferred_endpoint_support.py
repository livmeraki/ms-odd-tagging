from ms_odd_tagging.experiments.lane_debug_v2.static_inferred_affiliation import (
    assign_static_inferred_affiliations,
)


def _lane(lane_id, x0, x1, half_width=1.5):
    return {
        "lane_id": str(lane_id),
        "assignment_valid": True,
        "centerline_lcs_m": [[x0, 0.0], [x1, 0.0]],
        "left_boundary_lcs_m": [[x0, half_width], [x1, half_width]],
        "right_boundary_lcs_m": [[x0, -half_width], [x1, -half_width]],
        "polygon_lcs_m": [[x0, half_width], [x1, half_width], [x1, -half_width], [x0, -half_width]],
    }


def _track(track_id, lane, bogus_median_width=8.0):
    return {
        "track_id": track_id,
        "logical_lane_id": track_id,
        "member_lane_ids": [lane["lane_id"]],
        "centerline_lcs_m": lane["centerline_lcs_m"],
        "median_width_m": bogus_median_width,
        "pieces": [{
            "kind": "observed_ld",
            "lane_id": lane["lane_id"],
            "centerline_lcs_m": lane["centerline_lcs_m"],
            "polygon_lcs_m": lane["polygon_lcs_m"],
        }],
    }


def test_affiliation_uses_local_endpoint_width_not_track_median_width():
    back_lane = _lane("back", 0.0, 9.0)
    front_lane = _lane("front", 21.0, 30.0)
    tracks = [
        _track("physical_track_back", back_lane, bogus_median_width=8.0),
        _track("physical_track_front", front_lane, bogus_median_width=8.0),
    ]
    inferred = {
        "static_inferred_lane_id": "static_route_1",
        "route_id": "route_1",
        "centerline_lcs_m": [[10.0, 0.0], [15.0, 0.0], [20.0, 0.0]],
        "left_boundary_lcs_m": [[10.0, 1.5], [15.0, 1.5], [20.0, 1.5]],
        "right_boundary_lcs_m": [[10.0, -1.5], [15.0, -1.5], [20.0, -1.5]],
        "polygon_lcs_m": [[10.0, 1.5], [20.0, 1.5], [20.0, -1.5], [10.0, -1.5]],
        "median_width_m": 3.0,
    }

    resolved, debug = assign_static_inferred_affiliations(
        [inferred],
        tracks,
        [back_lane, front_lane],
        maximum_endpoint_distance_m=5.0,
        maximum_boundary_endpoint_distance_m=5.0,
        maximum_lateral_error_m=1.0,
        maximum_heading_difference_deg=10.0,
        maximum_curvature_difference_per_m=0.05,
        maximum_width_difference_m=0.25,
        minimum_unique_score_margin=0.5,
    )

    lane = resolved[0]
    assert lane["bridge_complete"] is True
    assert lane["start_observed_track_id"] == "physical_track_back"
    assert lane["end_observed_track_id"] == "physical_track_front"
    assert lane["back_affiliation"]["candidate_local_width_m"] == 3.0
    assert lane["back_affiliation"]["inferred_local_width_m"] == 3.0
    assert lane["back_affiliation"]["local_width_difference_m"] == 0.0
    assert lane["front_affiliation"]["candidate_local_width_m"] == 3.0
    assert debug[0]["accepted"] is True


def test_affiliation_rejects_boundary_endpoint_mismatch_even_when_center_matches():
    back_lane = _lane("back", 0.0, 9.0)
    front_lane = _lane("front", 21.0, 30.0)
    # Keep the centerline close but move both physical boundaries sideways.
    front_lane["left_boundary_lcs_m"] = [[21.0, 5.0], [30.0, 5.0]]
    front_lane["right_boundary_lcs_m"] = [[21.0, 2.0], [30.0, 2.0]]
    tracks = [
        _track("physical_track_back", back_lane, bogus_median_width=3.0),
        _track("physical_track_front", front_lane, bogus_median_width=3.0),
    ]
    inferred = {
        "static_inferred_lane_id": "static_route_2",
        "route_id": "route_2",
        "centerline_lcs_m": [[10.0, 0.0], [20.0, 0.0]],
        "left_boundary_lcs_m": [[10.0, 1.5], [20.0, 1.5]],
        "right_boundary_lcs_m": [[10.0, -1.5], [20.0, -1.5]],
        "polygon_lcs_m": [[10.0, 1.5], [20.0, 1.5], [20.0, -1.5], [10.0, -1.5]],
        "median_width_m": 3.0,
    }

    resolved, debug = assign_static_inferred_affiliations(
        [inferred], tracks, [back_lane, front_lane],
        maximum_endpoint_distance_m=5.0,
        maximum_boundary_endpoint_distance_m=2.0,
        maximum_lateral_error_m=1.0,
        maximum_heading_difference_deg=10.0,
        maximum_curvature_difference_per_m=0.05,
        maximum_width_difference_m=0.25,
        minimum_unique_score_margin=0.5,
    )

    assert resolved[0]["end_observed_track_id"] is None
    assert resolved[0]["bridge_complete"] is False
    front_rows = [
        row for row in debug[0]["front_candidates"]
        if row.get("track_id") == "physical_track_front"
    ]
    assert front_rows
    assert any(
        "left_boundary_endpoint_distance" in row["rejection_reasons"]
        or "right_boundary_endpoint_distance" in row["rejection_reasons"]
        for row in front_rows
    )


def test_affiliation_ignores_short_inferred_union_endpoint_hooks():
    back_lane = _lane("back", 0.0, 10.2)
    front_lane = _lane("front", 19.8, 30.0)
    tracks = [
        _track("physical_track_back", back_lane, bogus_median_width=8.0),
        _track("physical_track_front", front_lane, bogus_median_width=8.0),
    ]

    # Literal first/last segments hook sideways, but the 3-6 m interior road
    # direction is straight. This matches the smoothed-union terminal artifact
    # that caused affiliation to regress after the local-boundary refactor.
    inferred = {
        "static_inferred_lane_id": "static_route_hooked",
        "route_id": "route_hooked",
        "centerline_lcs_m": [
            [10.0, 0.8], [10.3, 0.0], [13.0, 0.0], [17.0, 0.0], [19.7, 0.0], [20.0, 0.8]
        ],
        "left_boundary_lcs_m": [
            [10.0, 2.3], [10.3, 1.5], [13.0, 1.5], [17.0, 1.5], [19.7, 1.5], [20.0, 2.3]
        ],
        "right_boundary_lcs_m": [
            [10.0, -0.7], [10.3, -1.5], [13.0, -1.5], [17.0, -1.5], [19.7, -1.5], [20.0, -0.7]
        ],
        "polygon_lcs_m": [
            [9.7, -1.5], [20.3, -1.5], [20.3, 2.3], [9.7, 2.3]
        ],
        "median_width_m": 3.0,
    }

    resolved, debug = assign_static_inferred_affiliations(
        [inferred], tracks, [back_lane, front_lane],
        maximum_endpoint_distance_m=5.0,
        maximum_boundary_endpoint_distance_m=5.0,
        maximum_lateral_error_m=2.0,
        maximum_heading_difference_deg=15.0,
        maximum_curvature_difference_per_m=0.08,
        maximum_width_difference_m=0.5,
        minimum_unique_score_margin=0.5,
    )

    lane = resolved[0]
    assert lane["bridge_complete"] is True
    assert lane["start_observed_track_id"] == "physical_track_back"
    assert lane["end_observed_track_id"] == "physical_track_front"
    assert lane["back_affiliation"]["inferred_heading_method"] == "robust_3m_6m_interior_window"
    assert lane["front_affiliation"]["inferred_heading_method"] == "robust_3m_6m_interior_window"
    assert debug[0]["accepted"] is True
