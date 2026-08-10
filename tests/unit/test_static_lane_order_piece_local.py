from ms_odd_tagging.experiments.lane_debug_v2.static_lane_order_piece_local import (
    build_static_lane_order,
    classify_lane_roles,
)


def test_static_inferred_piece_can_be_immediate_left_even_if_merged_centerline_is_bad():
    ego = {
        "track_id": "ego_track",
        "member_lane_ids": ["ego_lane"],
        "centerline_lcs_m": [[0.0, 0.0], [30.0, 0.0]],
        "pieces": [{"kind": "observed_ld", "centerline_lcs_m": [[0.0, 0.0], [30.0, 0.0]]}],
    }
    inferred = {
        "track_id": "inferred_track",
        "member_lane_ids": ["old_lane"],
        # Deliberately unusable as a local neighbor. The inferred piece itself
        # is the correct local geometry at +3.5 m lateral offset.
        "centerline_lcs_m": [[0.0, 40.0], [30.0, 40.0]],
        "pieces": [{
            "kind": "static_inferred_corridor",
            "centerline_lcs_m": [[0.0, 3.5], [30.0, 3.5]],
            "polygon_lcs_m": [[0.0, 5.25], [30.0, 5.25], [30.0, 1.75], [0.0, 1.75]],
        }],
    }
    tracks = [ego, inferred]
    topology = build_static_lane_order(tracks)
    roles = classify_lane_roles((10.0, 0.0), "ego_track", tracks, topology)

    assert roles["left"]["track_id"] == "inferred_track"
    assert roles["left"]["projection_piece_kind"] == "static_inferred_corridor"
    by_id = {item["track_id"]: item["role"] for item in roles["roles"]}
    assert by_id["inferred_track"] == "left_adjacent"
