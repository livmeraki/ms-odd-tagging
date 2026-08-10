from ms_odd_tagging.experiments.lane_debug_v2.static_inferred_lane import (
    build_static_inferred_lanes,
    integrate_static_inferred_lanes,
)


def _box(frame_index, x, width=3.5):
    return {
        "frame_index": frame_index,
        "kind": "inferred_from_overlapping_corridor",
        "centerline_lcs_m": [[x - 2.0, 0.0], [x, 0.0], [x + 2.0, 0.0]],
        "polygon_lcs_m": [[x - 2.0, 1.75], [x + 2.0, 1.75], [x + 2.0, -1.75], [x - 2.0, -1.75]],
        "width_m": width,
    }


def _track(track_id, x0, x1):
    return {
        "track_id": track_id,
        "logical_lane_id": track_id,
        "member_lane_ids": [f"lane_{track_id}"],
        "centerline_lcs_m": [[x0, 0.0], [x1, 0.0]],
        "median_width_m": 3.5,
        "pieces": [{
            "kind": "observed_ld",
            "lane_id": f"lane_{track_id}",
            "centerline_lcs_m": [[x0, 0.0], [x1, 0.0]],
            "polygon_lcs_m": [[x0, 1.75], [x1, 1.75], [x1, -1.75], [x0, -1.75]],
        }],
        "piece_count": 1,
        "observed_segment_count": 1,
    }


def test_overlapping_box_chain_becomes_one_static_corridor():
    routes = [{
        "route_id": "inferred_ego_route_0001",
        "start_observed_track_id": "physical_track_0003",
        "end_observed_track_id": "physical_track_0008",
        "start_frame_index": 10,
        "end_frame_index": 13,
        "bridge_complete": True,
        "pieces": [_box(10, 10.0), _box(11, 12.0), _box(12, 14.0), _box(13, 16.0)],
    }]
    lanes = build_static_inferred_lanes(routes)
    assert len(lanes) == 1
    lane = lanes[0]
    assert lane["evidence_box_count"] == 4
    assert lane["bridge_complete"] is True
    assert len(lane["centerline_lcs_m"]) == 4
    assert len(lane["polygon_lcs_m"]) >= 4


def test_static_corridor_merges_supported_front_and_back_tracks():
    routes = [{
        "route_id": "inferred_ego_route_0001",
        "start_observed_track_id": "physical_track_0003",
        "end_observed_track_id": "physical_track_0008",
        "start_frame_index": 10,
        "end_frame_index": 13,
        "bridge_complete": True,
        "pieces": [_box(10, 10.0), _box(11, 12.0), _box(12, 14.0), _box(13, 16.0)],
    }]
    static = build_static_inferred_lanes(routes)
    tracks = [_track("physical_track_0003", 0.0, 8.0), _track("physical_track_0008", 18.0, 30.0)]
    alias = {"physical_track_0003": "physical_track_0003", "physical_track_0008": "physical_track_0008"}
    merged, debug = integrate_static_inferred_lanes(
        tracks,
        static,
        alias,
        maximum_endpoint_distance_m=5.0,
        maximum_heading_difference_deg=20.0,
    )
    assert len(merged) == 1
    assert debug[0]["accepted"] is True
    assert debug[0]["action"] == "merge_front_back_tracks"
    assert any(p.get("kind") == "static_inferred_corridor" for p in merged[0]["pieces"])
    assert set(merged[0]["merged_from_track_ids"]) == {"physical_track_0003", "physical_track_0008"}
