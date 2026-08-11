import ms_odd_tagging.experiments.lane_debug_v2.static_inferred_affiliation as affiliation


def test_highest_ranked_eligible_candidate_is_selected_even_when_margin_is_small(monkeypatch):
    candidates = {
        "back": [
            {
                "track_id": "physical_track_back",
                "track_endpoint_side": "end",
                "supporting_lane_id": "back",
                "supporting_lane_endpoint_side": "end",
                "score": 10.0,
                "rejection_reasons": [],
                "accepted_by_gates": True,
            }
        ],
        "front": [
            {
                "track_id": "physical_track_0013",
                "track_endpoint_side": "start",
                "supporting_lane_id": "2457",
                "supporting_lane_endpoint_side": "start",
                "score": 16.92,
                "rejection_reasons": [],
                "accepted_by_gates": True,
            },
            {
                "track_id": "physical_track_0051",
                "track_endpoint_side": "end",
                "supporting_lane_id": "2443",
                "supporting_lane_endpoint_side": "end",
                "score": 17.04,
                "rejection_reasons": [],
                "accepted_by_gates": True,
            },
        ],
    }

    def fake_evaluate(inferred, track, lane_by_id, role, **kwargs):
        track_id = str(track["track_id"])
        return [row.copy() for row in candidates[role] if row["track_id"] == track_id]

    monkeypatch.setattr(affiliation, "evaluate_inferred_endpoint_candidate", fake_evaluate)

    inferred = {
        "static_inferred_lane_id": "static_test",
        "route_id": "route_test",
        "start_observed_track_id": None,
        "end_observed_track_id": None,
    }
    tracks = [
        {"track_id": "physical_track_back"},
        {"track_id": "physical_track_0013"},
        {"track_id": "physical_track_0051"},
    ]

    resolved, debug = affiliation.assign_static_inferred_affiliations(
        [inferred],
        tracks,
        [],
        minimum_unique_score_margin=0.5,
    )

    lane = resolved[0]
    assert lane["start_observed_track_id"] == "physical_track_back"
    assert lane["end_observed_track_id"] == "physical_track_0013"
    assert lane["front_affiliation"]["score"] == 16.92
    assert lane["front_affiliation"]["runner_up_score_margin"] == 0.12
    assert lane["front_affiliation"]["runner_up_margin_below_configured_unique_threshold"] is True
    assert lane["front_affiliation"]["selection_policy"] == "highest_ranked_eligible_candidate"
    assert lane["bridge_complete"] is True
    assert debug[0]["front_selection_rejection_reason"] is None
    assert debug[0]["front_runner_up_margin_below_configured_unique_threshold"] is True
