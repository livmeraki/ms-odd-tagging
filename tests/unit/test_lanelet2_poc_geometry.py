import math

from ms_odd_tagging.lanelet2_poc.config import load_config
from ms_odd_tagging.lanelet2_poc.geometry import (
    filter_local_boundaries,
    match_ego,
    pair_boundaries,
)
from ms_odd_tagging.lanelet2_poc.models import Boundary


def line(boundary_id, lateral, *, start=-20, stop=80, step=5):
    return Boundary(
        boundary_id,
        tuple((float(x), float(lateral)) for x in range(start, stop + 1, step)),
    )


def test_straight_boundaries_form_ego_and_both_adjacent_lanes():
    config = load_config(overrides={"feature_enabled": True, "require_lanelet2": False})
    boundaries = [
        line("outer_left", 5.25),
        line("left_shared", 1.75),
        line("right_shared", -1.75),
        line("outer_right", -5.25),
    ]
    local, rejected = filter_local_boundaries(boundaries, (0.0, 0.0, 0.0), config)
    lanes, pair_rejections = pair_boundaries(local, (0.0, 0.0, 0.0), config)
    match = match_ego(lanes, (0.0, 0.0, 0.0), config)

    assert not rejected
    assert len(lanes) == 3
    assert match["lane_id"] is not None
    ego = next(lane for lane in lanes if lane.lane_id == match["lane_id"])
    assert (ego.left_boundary_id, ego.right_boundary_id) == (
        "left_shared",
        "right_shared",
    )
    assert any("lane_too_wide" in item["reasons"] for item in pair_rejections)


def test_curved_boundaries_pair_and_heading_selects_lane():
    config = load_config(overrides={"feature_enabled": True, "require_lanelet2": False})

    def curve(boundary_id, offset):
        return Boundary(
            boundary_id,
            tuple((float(x), offset + 0.003 * x * x) for x in range(-10, 51, 3)),
        )

    boundaries = [curve("left", 1.75), curve("right", -1.75)]
    local, _ = filter_local_boundaries(boundaries, (0.0, 0.0, 0.0), config)
    lanes, _ = pair_boundaries(local, (0.0, 0.0, 0.0), config)
    match = match_ego(lanes, (0.0, 0.0, 0.0), config)

    assert len(lanes) == 1
    assert match["lane_id"] == lanes[0].lane_id
    assert match["confidence"] > 0.5


def test_fragmented_boundary_and_intersection_branch_are_rejected():
    config = load_config(overrides={"feature_enabled": True, "require_lanelet2": False})
    fragmented = Boundary("fragmented", ((-10.0, 1.75), (30.0, 1.75)))
    horizontal = line("horizontal", -1.75)
    vertical = Boundary(
        "vertical", tuple((0.0, float(y)) for y in range(-20, 21, 5))
    )

    local, rejected = filter_local_boundaries(
        [fragmented, horizontal, vertical], (0.0, 0.0, 0.0), config
    )
    lanes, pair_rejections = pair_boundaries(local, (0.0, 0.0, 0.0), config)

    assert any(
        item["boundary_id"] == "fragmented"
        and "boundary_discontinuity" in item["reasons"]
        for item in rejected
    )
    assert not lanes
    assert any("heading_mismatch" in item["reasons"] for item in pair_rejections)


def test_near_shared_boundary_reports_ambiguity_without_crashing():
    config = load_config(
        overrides={
            "feature_enabled": True,
            "require_lanelet2": False,
            "ambiguity_score_margin": 0.2,
        }
    )
    boundaries = [line("left", 3.5), line("shared", 0.0), line("right", -3.5)]
    local, _ = filter_local_boundaries(boundaries, (0.0, 0.0, 0.0), config)
    lanes, _ = pair_boundaries(local, (0.0, 0.0, 0.0), config)
    match = match_ego(lanes, (0.0, 0.0, 0.0), config)

    assert len(match["candidates"]) == 2
    assert match["ambiguous"] is True
    assert math.isfinite(match["confidence"])
