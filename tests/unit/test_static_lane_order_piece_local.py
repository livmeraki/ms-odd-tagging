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




def _parallel_track(track_id, y):
    return {
        "track_id": track_id,
        "member_lane_ids": [track_id],
        "centerline_lcs_m": [[0.0, y], [40.0, y]],
        "pieces": [{
            "kind": "observed_ld",
            "lane_id": track_id,
            "centerline_lcs_m": [[0.0, y], [40.0, y]],
            "polygon_lcs_m": [[0.0, y + 1.7], [40.0, y + 1.7], [40.0, y - 1.7], [0.0, y - 1.7]],
        }],
    }


def test_valid_local_inferred_piece_wins_over_closer_crossing_piece_on_same_track():
    ego = _parallel_track("ego", 0.0)
    candidate = _parallel_track("candidate", 3.5)
    candidate["centerline_lcs_m"] = [[10.0, -20.0], [10.0, 20.0]]
    candidate["pieces"].insert(0, {
        "kind": "observed_ld",
        "lane_id": "crossing_fragment",
        "centerline_lcs_m": [[10.0, -5.0], [10.0, 5.0]],
        "polygon_lcs_m": [[8.5, -5.0], [11.5, -5.0], [11.5, 5.0], [8.5, 5.0]],
    })
    candidate["pieces"][1]["kind"] = "static_inferred_corridor"
    topology = build_static_lane_order([ego, candidate])
    roles = classify_lane_roles((10.0, 0.0), "ego", [ego, candidate], topology, 0.0)
    assert roles["left"]["track_id"] == "candidate"
    assert roles["left"]["projection_piece_kind"] == "static_inferred_corridor"
    crossing = [x for x in roles["cross_section"]["candidate_evaluations"] if x["projection_piece_lane_id"] == "crossing_fragment"]
    assert crossing and "heading_difference" in crossing[0]["rejection_reasons"]


def test_crossing_turning_lane_is_rejected_with_explicit_heading_evidence():
    ego = _parallel_track("ego", 0.0)
    crossing = {
        "track_id": "crossing",
        "member_lane_ids": ["crossing"],
        "centerline_lcs_m": [[10.0, -4.0], [10.0, 4.0]],
        "pieces": [{"kind": "observed_ld", "lane_id": "crossing", "centerline_lcs_m": [[10.0, -4.0], [10.0, 4.0]]}],
    }
    topology = build_static_lane_order([ego, crossing])
    roles = classify_lane_roles((10.0, 0.0), "ego", [ego, crossing], topology, 0.0)
    assert roles["left"]["track_id"] is None
    evidence = roles["cross_section"]["candidate_evaluations"]
    assert any(x["track_id"] == "crossing" and "heading_difference" in x["rejection_reasons"] for x in evidence)


def test_farther_second_left_is_not_immediate_and_exposes_rejection():
    tracks = [_parallel_track("ego", 0.0), _parallel_track("left_1", 3.5), _parallel_track("left_2", 7.0)]
    topology = build_static_lane_order(tracks)
    roles = classify_lane_roles((10.0, 0.0), "ego", tracks, topology, 0.0)
    assert roles["left"]["track_id"] == "left_1"
    evidence = roles["cross_section"]["candidate_evaluations"]
    assert any(x["track_id"] == "left_2" and "not_immediate_neighbor" in x["rejection_reasons"] for x in evidence)


def test_role_identity_swaps_stably_across_actual_left_lane_change():
    a = _parallel_track("A", 0.0)
    b = _parallel_track("B", 3.5)
    topology = build_static_lane_order([a, b])
    before = classify_lane_roles((10.0, 0.0), "A", [a, b], topology, 0.0)
    after = classify_lane_roles((20.0, 3.5), "B", [a, b], topology, 0.0)
    assert before["roles"] == [{"track_id": "A", "role": "ego", "member_lane_ids": ["A"], "source": "canonical_continuous_track", "distance_to_ego_m": 0.0, "nearest_piece_kind": "observed_ld"}, {"track_id": "B", "role": "left_adjacent", "member_lane_ids": ["B"], "source": "canonical_continuous_track", "distance_to_ego_m": 3.5, "nearest_piece_kind": "observed_ld"}]
    assert {x["track_id"]: x["role"] for x in after["roles"]} == {"A": "right_adjacent", "B": "ego"}
