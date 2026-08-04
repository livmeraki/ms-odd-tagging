from __future__ import annotations

from copy import deepcopy

from ms_odd_tagging.tagger.rule_based.registry import (
    detect_events,
    events_overlapping_window,
    load_config,
    merge_scenario_events,
)


def motion_frames(count: int) -> list[dict]:
    return [
        {
            "frame_index": index,
            "time_since_start_s": round(index * 0.1, 6),
            "ego": {
                "speed_mps": 10.0,
                "heading_lcs_rad": 0.0,
                "yaw_rate_radps": 0.0,
                "velocity_lcs_mps": [10.0, 0.0, 0.0],
                "acceleration_mps2": 0.0,
            },
        }
        for index in range(count)
    ]


def turning_motion_frames(count: int, yaw_rate: float) -> list[dict]:
    frames = motion_frames(count)
    heading = 0.0
    for index, frame in enumerate(frames):
        if index > 0:
            heading += yaw_rate * 0.1
        frame["ego"]["heading_lcs_rad"] = heading
        frame["ego"]["yaw_rate_radps"] = yaw_rate
        frame["ego"]["velocity_lcs_mps"] = [10.0, 0.0, 0.0]
    return frames


def lane_context(
    lane_ids: list[str | None],
    *,
    source: str = "lane-a",
    target: str = "lane-b",
    direction: str = "left",
    adjacent: bool = True,
    topology_active_frames: set[int] | None = None,
    topology_class: str = "x-intersection",
    topology_confidence: float = 0.95,
) -> dict[int, dict]:
    result = {}
    topology_active_frames = topology_active_frames or set()
    for index, lane_id in enumerate(lane_ids):
        item = {
            "logical_lane_id": lane_id,
            "left_logical_lane_id": None,
            "right_logical_lane_id": None,
            "topology_class": topology_class if index in topology_active_frames else "normal",
            "topology_subtype": topology_class if index in topology_active_frames else "normal",
            "ego_inside_topology_polygon": index in topology_active_frames,
            "distance_to_topology_polygon_m": 0.0 if index in topology_active_frames else 5.0,
            "topology_confidence": topology_confidence if index in topology_active_frames else 0.0,
            "active_is_intersection": index in topology_active_frames,
            "active_topology_subtype": topology_class if index in topology_active_frames else "normal",
            "component_geometry_confidence": topology_confidence if index in topology_active_frames else 0.0,
        }
        if adjacent and lane_id == source:
            item[f"{direction}_logical_lane_id"] = target
        if adjacent and lane_id == target:
            opposite = "right" if direction == "left" else "left"
            item[f"{opposite}_logical_lane_id"] = source
        result[index] = item
    return result


def lane_change_events(
    lane_ids: list[str | None],
    *,
    source: str = "lane-a",
    target: str = "lane-b",
    direction: str = "left",
    adjacent: bool = True,
    topology_active_frames: set[int] | None = None,
    topology_class: str = "x-intersection",
) -> list:
    config = deepcopy(load_config())
    config["enabled_scenarios"] = [
        "changing_lane",
        "changing_lane_to_left",
        "changing_lane_to_right",
    ]
    events, _ = detect_events(
        motion_frames(len(lane_ids)),
        config,
        frame_context=lane_context(
            lane_ids,
            source=source,
            target=target,
            direction=direction,
            adjacent=adjacent,
            topology_active_frames=topology_active_frames,
            topology_class=topology_class,
        ),
    )
    return events


def assert_one_physical_change(events: list, direction: str) -> None:
    assert [event.scenario for event in events] == [
        "changing_lane",
        f"changing_lane_to_{direction}",
    ]
    physical_ids = {
        event.evidence["physical_lane_change_event_id"] for event in events
    }
    assert len(physical_ids) == 1
    assert all(event.evidence["direction"] == direction for event in events)


def test_stable_lane_following_has_no_lane_change() -> None:
    assert lane_change_events(["lane-a"] * 30) == []


def test_clean_left_lane_change() -> None:
    events = lane_change_events(["lane-a"] * 15 + ["lane-b"] * 15)
    assert_one_physical_change(events, "left")
    assert {(event.start_frame, event.end_frame) for event in events} == {(14, 24)}


def test_clean_right_lane_change() -> None:
    events = lane_change_events(
        ["lane-a"] * 15 + ["lane-b"] * 15, direction="right"
    )
    assert_one_physical_change(events, "right")


def test_one_frame_false_switch_is_rejected() -> None:
    assert (
        lane_change_events(["lane-a"] * 15 + ["lane-b"] + ["lane-a"] * 15)
        == []
    )


def test_missing_lane_detection_frame_does_not_break_valid_change() -> None:
    events = lane_change_events(
        ["lane-a"] * 15 + ["lane-b"] * 4 + [None] + ["lane-b"] * 10
    )
    assert_one_physical_change(events, "left")


def test_boundary_crossing_then_return_is_rejected() -> None:
    assert (
        lane_change_events(
            ["lane-a"] * 15 + ["lane-b"] * 5 + ["lane-a"] * 15
        )
        == []
    )


def test_non_adjacent_lane_jump_is_rejected() -> None:
    assert (
        lane_change_events(
            ["lane-a"] * 15 + ["lane-b"] * 15, adjacent=False
        )
        == []
    )


def test_overlapping_windows_do_not_duplicate_recording_event() -> None:
    events = lane_change_events(["lane-a"] * 15 + ["lane-b"] * 15)
    generic = next(event for event in events if event.scenario == "changing_lane")
    first = events_overlapping_window([generic], 0, 20)
    second = events_overlapping_window([generic], 10, 29)
    assert first[0] == second[0]
    assert len(merge_scenario_events([generic, generic])) == 1


def test_right_turn_intersection_lane_id_change_is_not_lane_change_right() -> None:
    lane_ids = ["lane-a"] * 8 + ["connector-r"] * 10 + ["lane-out-r"] * 12
    events = lane_change_events(
        lane_ids,
        source="lane-a",
        target="connector-r",
        direction="right",
        topology_active_frames=set(range(8, 18)),
    )
    assert {event.scenario for event in events} == set()


def test_left_turn_intersection_lane_id_change_is_not_lane_change_left() -> None:
    lane_ids = ["lane-a"] * 8 + ["connector-l"] * 10 + ["lane-out-l"] * 12
    events = lane_change_events(
        lane_ids,
        source="lane-a",
        target="connector-l",
        direction="left",
        topology_active_frames=set(range(8, 18)),
    )
    assert {event.scenario for event in events} == set()


def test_straight_intersection_connector_transitions_are_not_lane_changes() -> None:
    lane_ids = ["lane-a"] * 8 + ["connector-1"] * 5 + ["connector-2"] * 5 + ["lane-b"] * 12
    events = lane_change_events(
        lane_ids,
        source="lane-a",
        target="connector-1",
        direction="left",
        topology_active_frames=set(range(8, 18)),
    )
    assert events == []


def test_genuine_lane_change_before_intersection_remains_detectable() -> None:
    lane_ids = ["lane-a"] * 15 + ["lane-b"] * 15 + ["connector"] * 8 + ["lane-out"] * 10
    events = lane_change_events(
        lane_ids,
        source="lane-a",
        target="lane-b",
        direction="left",
        topology_active_frames=set(range(32, 40)),
    )
    assert_one_physical_change(events, "left")
    assert {(event.start_frame, event.end_frame) for event in events} == {(14, 24)}
    assert all(event.evidence["lane_change_applicable"] is True for event in events)


def test_after_intersection_lane_change_waits_for_lane_stability() -> None:
    lane_ids = (
        ["lane-a"] * 8
        + ["connector"] * 10
        + ["lane-out"] * 12
        + ["lane-target"] * 15
    )
    early_context = lane_context(
        lane_ids,
        source="connector",
        target="lane-out",
        direction="left",
        topology_active_frames=set(range(8, 18)),
    )
    config = deepcopy(load_config())
    config["enabled_scenarios"] = [
        "changing_lane",
        "changing_lane_to_left",
        "changing_lane_to_right",
    ]
    early_events, _ = detect_events(
        motion_frames(len(lane_ids)),
        config,
        frame_context=early_context,
    )
    assert early_events == []

    late_events, _ = detect_events(
        motion_frames(len(lane_ids)),
        config,
        frame_context=lane_context(
            lane_ids,
            source="lane-out",
            target="lane-target",
            direction="left",
            topology_active_frames=set(range(8, 18)),
        ),
    )
    assert_one_physical_change(late_events, "left")
    assert {(event.start_frame, event.end_frame) for event in late_events} == {(29, 39)}


def test_suppressed_lane_change_debug_fields_are_reported() -> None:
    lane_ids = ["lane-a"] * 8 + ["connector"] * 10 + ["lane-out"] * 12
    config = deepcopy(load_config())
    config["enabled_scenarios"] = [
        "changing_lane",
        "changing_lane_to_left",
        "changing_lane_to_right",
    ]
    events, quality = detect_events(
        motion_frames(len(lane_ids)),
        config,
        frame_context=lane_context(
            lane_ids,
            source="lane-a",
            target="connector",
            direction="right",
            topology_active_frames=set(range(8, 18)),
        ),
    )
    assert events == []
    suppressed = quality["lane_change_evaluation"][8]
    assert suppressed["intersection_active"] is True
    assert suppressed["topology_class"] == "x-intersection"
    assert suppressed["topology_confidence"] == 0.95
    assert suppressed["lane_change_applicable"] is False
    assert suppressed["lane_change_suppression_reason"] == "suppressed_by_topology"
    assert suppressed["pre_intersection_lane_id"] == "lane-a"
    assert suppressed["current_lane_id"] == "connector"
    assert suppressed["post_intersection_lane_id"] is None
    assert suppressed["lane_stability_frames"] == 0
    assert (
        suppressed["final_decision_reason"]
        == "lane_change_not_applicable_inside_intersection_topology"
    )


def test_turn_detection_continues_inside_intersection_suppression() -> None:
    lane_ids = ["lane-a"] * 8 + ["connector"] * 14 + ["lane-out"] * 8
    config = deepcopy(load_config())
    config["enabled_scenarios"] = [
        "starting_left_turn",
        "starting_right_turn",
        "changing_lane",
        "changing_lane_to_left",
        "changing_lane_to_right",
    ]
    events, _ = detect_events(
        turning_motion_frames(len(lane_ids), yaw_rate=0.35),
        config,
        frame_context=lane_context(
            lane_ids,
            source="lane-a",
            target="connector",
            direction="left",
            topology_active_frames=set(range(8, 22)),
        ),
    )
    assert "starting_left_turn" in {event.scenario for event in events}
    assert "changing_lane_to_left" not in {event.scenario for event in events}


def test_roundabout_lane_transitions_do_not_create_ordinary_lane_change() -> None:
    lane_ids = ["lane-a"] * 6 + ["roundabout-entry"] * 6 + ["circulating"] * 8 + ["lane-out"] * 10
    events = lane_change_events(
        lane_ids,
        source="lane-a",
        target="roundabout-entry",
        direction="right",
        topology_active_frames=set(range(6, 20)),
        topology_class="roundabout",
    )
    assert events == []


def test_intersection_unknown_suppresses_lane_change_by_geometry() -> None:
    lane_ids = ["lane-a"] * 8 + ["connector"] * 10 + ["lane-out"] * 12
    events = lane_change_events(
        lane_ids,
        source="lane-a",
        target="connector",
        direction="right",
        topology_active_frames=set(range(8, 18)),
        topology_class="intersection_unknown",
    )
    assert events == []


def test_intersection_turn_suppresses_lane_change_outside_polygon_tolerance() -> None:
    lane_ids = ["lane-a"] * 8 + ["connector"] * 10 + ["lane-out"] * 12
    context = lane_context(
        lane_ids,
        source="lane-a",
        target="connector",
        direction="right",
        topology_active_frames=set(range(8, 18)),
        topology_class="intersection_unknown",
    )
    for index in range(8, 18):
        context[index]["ego_inside_topology_polygon"] = False
        context[index]["distance_to_topology_polygon_m"] = 12.0

    config = deepcopy(load_config())
    config["enabled_scenarios"] = [
        "starting_right_turn",
        "changing_lane",
        "changing_lane_to_left",
        "changing_lane_to_right",
    ]
    events, quality = detect_events(
        turning_motion_frames(len(lane_ids), yaw_rate=-0.35),
        config,
        frame_context=context,
    )

    assert "starting_right_turn" in {event.scenario for event in events}
    assert "changing_lane_to_right" not in {event.scenario for event in events}
    suppressed = quality["lane_change_evaluation"][8]
    assert suppressed["intersection_active"] is True
    assert suppressed["lane_change_applicable"] is False
    assert suppressed["lane_change_suppression_reason"] == "suppressed_by_topology_turn"
    assert suppressed["turn_candidate"] == "starting_right_turn"
    assert (
        suppressed["final_decision_reason"]
        == "lane_change_not_applicable_during_intersection_turn"
    )
