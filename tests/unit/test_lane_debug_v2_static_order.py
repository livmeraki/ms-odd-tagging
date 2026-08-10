from ms_odd_tagging.experiments.lane_debug_v2.raw_ld_gap_recovery import build_raw_ld_gap_tracks
from ms_odd_tagging.experiments.lane_debug_v2.static_lane_order import build_static_lane_order, classify_lane_roles


def _track(track_id, y):
    return {
        "track_id": track_id,
        "logical_lane_id": track_id,
        "member_lane_ids": [track_id],
        "centerline_lcs_m": [[0.0, y], [40.0, y]],
        "median_width_m": 3.5,
        "pieces": [{"kind": "observed_ld", "lane_id": track_id, "polygon_lcs_m": [[0, y+1.75], [40, y+1.75], [40, y-1.75], [0, y-1.75]]}],
    }


def test_static_order_keeps_immediate_neighbors_and_flips_old_ego_after_left_change():
    right = _track("A", -3.5)
    ego = _track("B", 0.0)
    left = _track("C", 3.5)
    tracks = [right, ego, left]
    topology = build_static_lane_order(tracks, sample_spacing_m=2.0)
    before = classify_lane_roles((20.0, 0.0), "B", tracks, topology)
    assert before["left"]["track_id"] == "C"
    assert before["right"]["track_id"] == "A"
    after = classify_lane_roles((20.0, 3.5), "C", tracks, topology)
    assert after["right"]["track_id"] == "B"


def test_static_order_does_not_skip_over_immediate_lane():
    tracks = [_track("E", 0.0), _track("L1", 3.5), _track("L2", 7.0)]
    topology = build_static_lane_order(tracks, sample_spacing_m=2.0)
    roles = classify_lane_roles((10.0, 0.0), "E", tracks, topology)
    assert roles["left"]["track_id"] == "L1"
    assert roles["left"]["track_id"] != "L2"


def test_raw_ld_cannot_create_standalone_lane_without_canonical_endpoint_anchors():
    recording = {
        "ld_feature_store": {
            "points": [
                {"point_id": "l0", "position_lcs_m": [0, 1.75]},
                {"point_id": "l1", "position_lcs_m": [20, 1.75]},
                {"point_id": "r0", "position_lcs_m": [0, -1.75]},
                {"point_id": "r1", "position_lcs_m": [20, -1.75]},
            ],
            "lane_lines": [
                {"line_id": "L", "point_ids": ["l0", "l1"]},
                {"line_id": "R", "point_ids": ["r0", "r1"]},
            ],
            "road_boundaries": [],
        }
    }
    tracks, debug = build_raw_ld_gap_tracks(recording, [], [])
    assert tracks == []
    assert debug == []
