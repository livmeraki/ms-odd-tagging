import pytest

from ms_odd_tagging.lanelet2_poc.config import load_config
from ms_odd_tagging.lanelet2_poc.lanelet_backend import (
    available as lanelet2_available,
    build_routing_context,
    query_neighbors,
)
from ms_odd_tagging.lanelet2_poc.models import Boundary
from ms_odd_tagging.lanelet2_poc.models import LaneCandidate
from ms_odd_tagging.lanelet2_poc.runner import (
    boundaries_from_recording,
    run_frame,
    run_recording,
)


def boundary(boundary_id, y):
    return Boundary(boundary_id, tuple((float(x), y) for x in range(-20, 81, 5)))


def test_runner_outputs_ids_polygons_confidence_and_neighbor_existence():
    config = load_config(overrides={"feature_enabled": True, "require_lanelet2": False})
    result = run_frame(
        [
            boundary("outer_left", 5.25),
            boundary("left", 1.75),
            boundary("right", -1.75),
            boundary("outer_right", -5.25),
        ],
        (0.0, 0.0, 0.0),
        config,
        frame_index=7,
    )

    assert result["status"] == "matched"
    assert result["frame_index"] == 7
    assert result["ego_lane"]["boundary_ids"] == {"left": "left", "right": "right"}
    assert result["ego_lane"]["polygon_lcs_m"]
    assert result["ego_lane"]["confidence"] > 0
    assert result["left_adjacent"]["exists"] is True
    assert result["right_adjacent"]["exists"] is True
    assert set(result["routing"]["queries"]) == {
        "left",
        "right",
        "adjacentLeft",
        "adjacentRight",
    }


def test_missing_outer_boundaries_returns_no_adjacent_lanes():
    config = load_config(overrides={"feature_enabled": True, "require_lanelet2": False})
    result = run_frame(
        [boundary("left", 1.75), boundary("right", -1.75)],
        (0.0, 0.0, 0.0),
        config,
    )

    assert result["ego_lane"]["exists"] is True
    assert result["left_adjacent"]["exists"] is False
    assert result["right_adjacent"]["exists"] is False


def test_invalid_ego_pose_is_structured_not_an_exception():
    config = load_config(overrides={"feature_enabled": True, "require_lanelet2": False})
    result = run_frame([], (float("nan"), 0.0, 0.0), config)
    assert result["status"] == "invalid_input"
    assert result["rejection_reasons"] == ["ego_pose_must_be_finite_x_y_yaw"]


def test_disabled_recording_call_is_a_noop():
    result = run_recording({"recording_id": "unused"}, load_config())
    assert result["status"] == "disabled"
    assert result["frames"] == []


def test_virtual_lane_lines_are_excluded_from_lanelet2_poc_inputs():
    recording = {
        "ld_feature_store": {
            "points": [
                {"point_id": "p1", "position_lcs_m": [0.0, 1.0]},
                {"point_id": "p2", "position_lcs_m": [5.0, 1.0]},
                {"point_id": "p3", "position_lcs_m": [0.0, -1.0]},
                {"point_id": "p4", "position_lcs_m": [5.0, -1.0]},
            ],
            "lane_lines": [
                {
                    "line_id": "virtual_line",
                    "point_ids": ["p1", "p2"],
                    "attributes": {"pattern": "virtual", "intersection": False},
                },
                {
                    "line_id": "normal_line",
                    "point_ids": ["p3", "p4"],
                    "attributes": {"pattern": "dashed", "intersection": True},
                },
            ],
        }
    }

    filtered = boundaries_from_recording(recording, load_config())
    unfiltered = boundaries_from_recording(
        recording,
        load_config(overrides={"exclude_virtual_lane_lines": False}),
    )

    assert [boundary.boundary_id for boundary in filtered] == ["normal_line"]
    assert [boundary.boundary_id for boundary in unfiltered] == [
        "virtual_line",
        "normal_line",
    ]


@pytest.mark.skipif(not lanelet2_available(), reason="Lanelet2 bindings not installed")
def test_native_lanelet2_routing_uses_shared_boundaries_without_geometric_fallback():
    def line_points(y):
        return tuple((float(x), y) for x in range(-20, 81, 10))

    def candidate(lane_id, left_id, right_id, left_y, right_y):
        left = line_points(left_y)
        right = line_points(right_y)
        centerline = tuple((x, (left_y + right_y) / 2.0) for x, _ in left)
        return LaneCandidate(
            lane_id=lane_id,
            left_boundary_id=left_id,
            right_boundary_id=right_id,
            left=left,
            right=right,
            centerline=centerline,
            polygon=left + tuple(reversed(right)),
            pair_score=0.9,
            pair_metrics={},
        )

    boundaries = [
        Boundary("outer_left", line_points(5.25)),
        Boundary("left_shared", line_points(1.75)),
        Boundary("right_shared", line_points(-1.75)),
        Boundary("outer_right", line_points(-5.25)),
    ]
    lanes = [
        candidate("lane_left", "outer_left", "left_shared", 5.25, 1.75),
        candidate("lane_ego", "left_shared", "right_shared", 1.75, -1.75),
        candidate("lane_right", "right_shared", "outer_right", -1.75, -5.25),
    ]

    context = build_routing_context(
        lanes,
        {"location": "Germany", "participant": "Vehicle"},
        boundaries,
    )
    ego = context.lanelets_by_poc_id["lane_ego"]
    raw_results = {
        method: getattr(context.graph, method)(ego)
        for method in ("left", "right", "adjacentLeft", "adjacentRight")
        if hasattr(context.graph, method)
    }
    neighbors = query_neighbors(context, "lane_ego")

    assert set(raw_results) == {"left", "right", "adjacentLeft", "adjacentRight"}
    # Generic inferred boundaries do not encode lane-change permissions, so
    # legal left/right can be unavailable while geometric adjacency is routed.
    assert raw_results["left"] is None
    assert raw_results["right"] is None
    assert neighbors == {
        "left": None,
        "right": None,
        "adjacentLeft": "lane_left",
        "adjacentRight": "lane_right",
    }
