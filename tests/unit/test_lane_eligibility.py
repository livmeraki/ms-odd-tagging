from ms_odd_tagging.experiments.lane_debug_v2.lane_eligibility import (
    exclude_curved_intersection_lanes,
)


def _lane(lane_id, centerline, intersection):
    return {
        "lane_id": lane_id,
        "assignment_valid": True,
        "invalid_reason": None,
        "intersection_connector": intersection,
        "intersection_evidence": ["left_boundary_attribute"] if intersection else [],
        "centerline_lcs_m": centerline,
        "polygon_lcs_m": [],
    }


def test_curved_intersection_lane_is_rejected_but_straight_intersection_remains():
    lanes = [
        _lane("straight_intersection", [[0, 0], [5, 0], [10, 0]], True),
        _lane("curved_intersection", [[0, 0], [5, 0], [9, 2], [12, 6]], True),
        _lane("curved_regular", [[0, 0], [5, 0], [9, 2], [12, 6]], False),
    ]
    filtered, debug = exclude_curved_intersection_lanes(
        lanes,
        maximum_heading_change_deg=10.0,
        maximum_abs_curvature_per_m=0.02,
    )
    by_id = {x["lane_id"]: x for x in filtered}
    assert by_id["straight_intersection"]["assignment_valid"] is True
    assert by_id["curved_intersection"]["assignment_valid"] is False
    assert by_id["curved_intersection"]["invalid_reason"] == "excluded_curved_intersection_lane"
    assert by_id["curved_regular"]["assignment_valid"] is True
    rejected = [x["lane_id"] for x in debug if x["rejected"]]
    assert rejected == ["curved_intersection"]
