from ms_odd_tagging.experiments.lane_debug_v2.detector_static_order_integrated_piece_local import (
    _recompute_frames_piece_local,
)
from ms_odd_tagging.experiments.lane_debug_v2.static_lane_order_piece_local import (
    build_static_lane_order,
)


def _lane(lane_id, x0, x1):
    return {
        "lane_id": lane_id,
        "centerline_lcs_m": [[x0, 0.0], [x1, 0.0]],
        "polygon_lcs_m": [[x0, 1.5], [x1, 1.5], [x1, -1.5], [x0, -1.5]],
    }


def _integrated_track():
    return {
        "track_id": "physical_track_0001",
        "logical_lane_id": "physical_track_0001",
        "member_lane_ids": ["back", "front"],
        "centerline_lcs_m": [[0.0, 0.0], [10.0, 0.0], [20.0, 0.0], [30.0, 0.0]],
        "pieces": [
            {
                "kind": "observed_ld",
                "lane_id": "back",
                "centerline_lcs_m": [[0.0, 0.0], [10.0, 0.0]],
                "polygon_lcs_m": [[0.0, 1.5], [10.0, 1.5], [10.0, -1.5], [0.0, -1.5]],
            },
            {
                "kind": "static_inferred_corridor",
                "static_inferred_lane_id": "static_route_1",
                "route_id": "route_1",
                "centerline_lcs_m": [[10.0, 0.0], [20.0, 0.0]],
                "polygon_lcs_m": [[10.0, 1.5], [20.0, 1.5], [20.0, -1.5], [10.0, -1.5]],
            },
            {
                "kind": "observed_ld",
                "lane_id": "front",
                "centerline_lcs_m": [[20.0, 0.0], [30.0, 0.0]],
                "polygon_lcs_m": [[20.0, 1.5], [30.0, 1.5], [30.0, -1.5], [20.0, -1.5]],
            },
        ],
    }


def test_ego_and_lead_inside_integrated_inferred_corridor_follow_same_lane():
    track = _integrated_track()
    tracks = [track]
    lanes = [_lane("back", 0.0, 10.0), _lane("front", 20.0, 30.0)]
    lane_order = build_static_lane_order(tracks)
    recording = {
        "frames": [{
            "frame_index": 1,
            "ego": {"position_lcs_m": [15.0, 0.0], "heading_lcs_rad": 0.0},
        }]
    }
    result = {
        "lane_geometry": lanes,
        "frames": [{
            "frame_index": 1,
            "timestamp_unix_s": 1000.0,
            "time_since_start_s": 1.0,
            "speed_mps": 5.0,
            "objects": [{
                "object_id": "lead",
                "class": "car",
                "annotation_type": "dynamic",
                "position_lcs_m": [17.0, 0.0],
                "longitudinal_m": 2.0,
                "lane_id": None,
            }],
        }],
    }

    _recompute_frames_piece_local(
        recording,
        result,
        tracks,
        lane_order,
        {
            "continuous_track_maximum_heading_difference_deg": 60.0,
            "continuous_track_outside_tolerance_m": 1.0,
            "minimum_moving_speed_mps": 0.5,
            "maximum_lead_distance_m": 80.0,
            "lead_annotation_types": ["dynamic"],
        },
    )

    frame = result["frames"][0]
    assert frame["continuous_ego_track"]["track_id"] == "physical_track_0001"
    assert frame["continuous_ego_track"]["matched_piece_kind"] == "static_inferred_corridor"
    assert frame["continuous_ego_track"]["matched_static_inferred_lane_id"] == "static_route_1"
    assert frame["ego_lane"]["lane_id"] == "static_route_1"
    assert frame["ego_lane"]["continuous_track_id"] == "physical_track_0001"
    assert frame["ego_lane"]["continuous_track_member_lane_ids"] == ["back", "front"]
    assert frame["ego_lane"]["whole_integrated_track_is_ego_lane"] is True
    assert next(r for r in frame["lane_roles"]["roles"] if r["track_id"] == "physical_track_0001")["role"] == "ego"

    obj = frame["objects"][0]
    assert obj["lane_id"] == "static_route_1"
    assert obj["continuous_track_id"] == "physical_track_0001"
    assert obj["final_track_matched_piece_kind"] == "static_inferred_corridor"
    assert obj["final_following_lane_same_track_as_ego"] is True
    assert frame["lead"]["object_id"] == "lead"
    assert frame["state"] == "following_lane_with_lead"
    assert result["intervals"][0]["scenario"] == "following_lane_with_lead"


def test_moving_ego_inside_integrated_inferred_corridor_without_lead_is_following_lane():
    track = _integrated_track()
    tracks = [track]
    lane_order = build_static_lane_order(tracks)
    recording = {
        "frames": [{
            "frame_index": 2,
            "ego": {"position_lcs_m": [15.0, 0.0], "heading_lcs_rad": 0.0},
        }]
    }
    result = {
        "lane_geometry": [_lane("back", 0.0, 10.0), _lane("front", 20.0, 30.0)],
        "frames": [{
            "frame_index": 2,
            "timestamp_unix_s": 1001.0,
            "time_since_start_s": 2.0,
            "speed_mps": 5.0,
            "objects": [],
        }],
    }

    _recompute_frames_piece_local(recording, result, tracks, lane_order, {})

    frame = result["frames"][0]
    assert frame["ego_lane"]["lane_id"] == "static_route_1"
    assert frame["ego_lane"]["continuous_track_id"] == "physical_track_0001"
    assert frame["state"] == "following_lane_without_lead"
    assert result["intervals"][0]["scenario"] == "following_lane_without_lead"
