from ms_odd_tagging.experiments.lane_debug_v2.inferred_ego_route import InferredEgoRouteTracker
from ms_odd_tagging.experiments.lane_debug_v2.lane_network_roles import (
    build_constructed_lane_network,
    classify_all_lane_roles,
)


def _track(track_id, y):
    return {
        "track_id": track_id,
        "logical_lane_id": track_id,
        "member_lane_ids": [track_id + "_lane"],
        "centerline_lcs_m": [[0.0, y], [40.0, y]],
        "piece_count": 1,
        "observed_segment_count": 1,
        "inferred_gap_count": 0,
        "median_width_m": 3.5,
    }


def _relation(ego, adjacent, side, score=3.5):
    return {
        "ego_track_id": ego,
        "adjacent_track_id": adjacent,
        "side": side,
        "ego_s_start_m": 0.0,
        "ego_s_end_m": 40.0,
        "overlap_m": 40.0,
        "score": score,
        "confidence": "high",
    }


def test_all_constructed_lanes_exist_before_frame_role_assignment():
    tracks = [_track("A", 0.0), _track("B", 3.5), _track("C", 10.5)]
    graph = {"relations": [_relation("A", "B", "left")], "by_ego_track": {"A": {"left": [_relation("A", "B", "left")], "right": []}}}
    network = build_constructed_lane_network(tracks, graph)
    assert network["lane_count"] == 3
    assert {item["track_id"] for item in network["lanes"]} == {"A", "B", "C"}


def test_previous_ego_becomes_right_lane_after_left_lane_change_via_reciprocal_relation():
    tracks = [_track("A", 0.0), _track("B", 3.5)]
    relation = _relation("A", "B", "left")
    # Intentionally omit B->A. The classifier must derive the reciprocal role.
    graph = {"relations": [relation], "by_ego_track": {"A": {"left": [relation], "right": []}}}
    roles, _, _ = classify_all_lane_roles((20.0, 3.5), "B", tracks, graph, hysteresis_enabled=False)
    assert roles["right"]["track_id"] == "A"
    by_track = {item["track_id"]: item["role"] for item in roles["roles"]}
    assert by_track["B"] == "ego"
    assert by_track["A"] == "right_adjacent"


def test_nonselected_constructed_lane_remains_irrelevant_not_missing():
    tracks = [_track("A", 0.0), _track("B", 3.5), _track("C", 10.5)]
    relation = _relation("A", "B", "left")
    graph = {"relations": [relation], "by_ego_track": {"A": {"left": [relation], "right": []}}}
    roles, _, _ = classify_all_lane_roles((20.0, 0.0), "A", tracks, graph, hysteresis_enabled=False)
    by_track = {item["track_id"]: item["role"] for item in roles["roles"]}
    assert by_track == {"A": "ego", "B": "left_adjacent", "C": "irrelevant"}


def _corridor(x):
    return {
        "valid": True,
        "left_boundary_id": "L",
        "right_boundary_id": "R",
        "centerline_lcs_m": [[x - 5.0, 0.0], [x + 5.0, 0.0]],
        "polygon_lcs_m": [[x - 5.0, 1.75], [x + 5.0, 1.75], [x + 5.0, -1.75], [x - 5.0, -1.75]],
        "width_at_ego_m": 3.5,
    }


def test_consecutive_inferred_corridors_share_one_ego_route_and_bridge_observed_tracks():
    tracker = InferredEgoRouteTracker()
    tracker.observe_actual_track("A", 10)
    first = tracker.observe_corridor(_corridor(10.0), 11)
    second = tracker.observe_corridor(_corridor(12.0), 12)
    assert first["route_id"] == second["route_id"]
    tracker.observe_actual_track("B", 13)
    route = tracker.snapshot()[0]
    assert route["start_observed_track_id"] == "A"
    assert route["end_observed_track_id"] == "B"
    assert route["bridge_complete"] is True
