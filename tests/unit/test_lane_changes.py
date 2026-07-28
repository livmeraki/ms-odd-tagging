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


def lane_context(
    lane_ids: list[str | None],
    *,
    source: str = "lane-a",
    target: str = "lane-b",
    direction: str = "left",
    adjacent: bool = True,
) -> dict[int, dict]:
    result = {}
    for index, lane_id in enumerate(lane_ids):
        item = {
            "logical_lane_id": lane_id,
            "left_logical_lane_id": None,
            "right_logical_lane_id": None,
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
    direction: str = "left",
    adjacent: bool = True,
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
            lane_ids, direction=direction, adjacent=adjacent
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
