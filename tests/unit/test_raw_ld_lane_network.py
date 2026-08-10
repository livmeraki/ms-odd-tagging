from ms_odd_tagging.experiments.lane_debug_v2.raw_ld_lane_network import build_raw_ld_lane_tracks
from ms_odd_tagging.experiments.lane_debug_v2.strict_track_assignment import assign_point_to_track_strict


def test_parallel_raw_ld_lines_construct_lane_without_canonical_lane_entity():
    recording = {
        "ld_feature_store": {
            "points": [
                {"point_id": "l0", "position_lcs_m": [0.0, 1.75]},
                {"point_id": "l1", "position_lcs_m": [30.0, 1.75]},
                {"point_id": "r0", "position_lcs_m": [0.0, -1.75]},
                {"point_id": "r1", "position_lcs_m": [30.0, -1.75]},
            ],
            "lane_lines": [
                {"line_id": "LEFT", "point_ids": ["l0", "l1"]},
                {"line_id": "RIGHT", "point_ids": ["r0", "r1"]},
            ],
            "road_boundaries": [],
        }
    }
    tracks, debug = build_raw_ld_lane_tracks(recording, [])
    assert len(tracks) == 1
    assert tracks[0]["source"] == "raw_ld_boundary_pair"
    assert {tracks[0]["left_boundary_id"], tracks[0]["right_boundary_id"]} == {"LEFT", "RIGHT"}
    assert debug[0]["overlap_m"] >= 8.0
    assignment = assign_point_to_track_strict((15.0, 0.0), 0.0, tracks)
    assert assignment["track_id"] == tracks[0]["track_id"]
    assert assignment["matched_piece_kind"] == "raw_ld_boundary_pair"


def test_existing_canonical_boundary_pair_is_not_duplicated_as_raw_lane():
    recording = {
        "ld_feature_store": {
            "points": [
                {"point_id": "l0", "position_lcs_m": [0.0, 1.75]},
                {"point_id": "l1", "position_lcs_m": [30.0, 1.75]},
                {"point_id": "r0", "position_lcs_m": [0.0, -1.75]},
                {"point_id": "r1", "position_lcs_m": [30.0, -1.75]},
            ],
            "lane_lines": [
                {"line_id": "LEFT", "point_ids": ["l0", "l1"]},
                {"line_id": "RIGHT", "point_ids": ["r0", "r1"]},
            ],
            "road_boundaries": [],
        }
    }
    canonical = [{"lane_id": "C", "assignment_valid": True, "left_edge_id": "LEFT", "right_edge_id": "RIGHT"}]
    tracks, _ = build_raw_ld_lane_tracks(recording, canonical)
    assert tracks == []
