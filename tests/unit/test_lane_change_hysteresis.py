from ms_odd_tagging.experiments.lane_debug_v2.lane_changes import _apply_lane_id_hysteresis


def _contexts(sequence):
    return {i: {"logical_lane_id": lane} for i, lane in enumerate(sequence)}


def test_one_and_two_frame_lane_spikes_are_suppressed():
    contexts = _contexts(["A", "A", "B", "A", "B", "B", "A", "A"])
    debug = _apply_lane_id_hysteresis(
        contexts,
        list(range(8)),
        {
            "lane_id_hysteresis_confirmation_frames": 3,
            "lane_id_hysteresis_missing_hold_frames": 2,
        },
    )

    assert [contexts[i]["logical_lane_id"] for i in range(8)] == [
        "A", "A", "A", "A", "A", "A", "A", "A"
    ]
    assert debug[2]["action"] == "hold_stable_pending_switch"
    assert debug[5]["pending_count"] == 2


def test_sustained_lane_change_is_confirmed_after_three_frames():
    contexts = _contexts(["A", "A", "B", "B", "B", "B"])
    debug = _apply_lane_id_hysteresis(
        contexts,
        list(range(6)),
        {"lane_id_hysteresis_confirmation_frames": 3},
    )

    assert [contexts[i]["logical_lane_id"] for i in range(6)] == [
        "A", "A", "A", "A", "B", "B"
    ]
    assert debug[4]["action"] == "confirm_switch_from_A"
    assert debug[4]["stable_logical_lane_id"] == "B"


def test_short_missing_lane_gap_holds_previous_stable_lane():
    contexts = _contexts(["A", None, None, "A", None, None, None])
    debug = _apply_lane_id_hysteresis(
        contexts,
        list(range(7)),
        {
            "lane_id_hysteresis_confirmation_frames": 3,
            "lane_id_hysteresis_missing_hold_frames": 2,
        },
    )

    assert [contexts[i]["logical_lane_id"] for i in range(7)] == [
        "A", "A", "A", "A", "A", "A", None
    ]
    assert debug[6]["action"] == "missing_hold_expired"
