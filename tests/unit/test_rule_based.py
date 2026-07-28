from __future__ import annotations

import math

from ms_odd_tagging.features.ego_motion import extract_ego_motion_features
from ms_odd_tagging.tagger.rule_based.dynamics import classify_speed_band
from ms_odd_tagging.tagger.rule_based.event_segmentation import segment_signal
from ms_odd_tagging.tagger.rule_based.registry import (
    detect_events,
    events_overlapping_window,
    load_config,
    validate_config,
)


def frames(speeds, *, times=None, headings=None, accelerations=None, velocities=None, yaw_rates=None):
    count = len(speeds)
    times = times or [index * 0.1 for index in range(count)]
    headings = headings or [0.0] * count
    accelerations = accelerations or [0.0] * count
    velocities = velocities or [
        (speed * math.cos(heading), speed * math.sin(heading))
        if isinstance(speed, (int, float)) and math.isfinite(speed)
        else None
        for speed, heading in zip(speeds, headings)
    ]
    yaw_rates = yaw_rates or [0.0] * count
    return [{
        "frame_index": index,
        "time_since_start_s": timestamp,
        "ego": {
            "speed_mps": speed,
            "acceleration_mps2": acceleration,
            "heading_lcs_rad": heading,
            "yaw_rate_radps": yaw_rate,
            "velocity_lcs_mps": [velocity[0], velocity[1], 0.0] if velocity is not None else None,
        },
    } for index, (timestamp, speed, heading, acceleration, velocity, yaw_rate) in enumerate(zip(times, speeds, headings, accelerations, velocities, yaw_rates))]


def labels(input_frames):
    events, _ = detect_events(input_frames)
    return [event.scenario for event in events], events


def test_constant_stationary_trajectory():
    found, _ = labels(frames([0.0] * 21))
    assert found == ["stationary"]


def test_low_medium_high_intervals_and_boundaries_are_exclusive():
    input_frames = frames([0.5, 0.5, 5.0, 5.0, 15.0, 15.0])
    found, events = labels(input_frames)
    assert set(found) == {"low_magnitude_speed", "medium_magnitude_speed", "high_magnitude_speed"}
    for index in range(len(input_frames)):
        active = [event.scenario for event in events if event.start_frame <= index <= event.end_frame and "magnitude_speed" in event.scenario]
        assert len(active) == 1


def speed_events(events):
    speed_scenarios = {
        "stationary", "low_magnitude_speed", "medium_magnitude_speed",
        "high_magnitude_speed",
    }
    return sorted(
        (event for event in events if event.scenario in speed_scenarios),
        key=lambda event: event.start_frame,
    )


def test_exact_speed_threshold_boundaries():
    config = load_config()
    cases = (
        (0.0, "stationary"),
        (0.499999, "stationary"),
        (0.5, "low_magnitude_speed"),
        (4.999999, "low_magnitude_speed"),
        (5.0, "medium_magnitude_speed"),
        (14.999999, "medium_magnitude_speed"),
        (15.0, "high_magnitude_speed"),
        (100.0, "high_magnitude_speed"),
    )
    assert [(speed, classify_speed_band(speed, config)) for speed, _ in cases] == list(cases)


def test_every_adjacent_speed_transition_in_both_directions():
    speeds = [0.0, 0.5, 5.0, 15.0, 5.0, 0.5, 0.0]
    _, events = labels(frames(speeds))
    ordered = speed_events(events)
    assert [event.scenario for event in ordered] == [
        "stationary", "low_magnitude_speed", "medium_magnitude_speed",
        "high_magnitude_speed", "medium_magnitude_speed",
        "low_magnitude_speed", "stationary",
    ]
    assert [(event.start_frame, event.end_frame) for event in ordered] == [(i, i) for i in range(7)]


def test_isolated_speed_spike_does_not_create_event():
    speeds = [0.0, 0.0, 0.0, 15.0, 0.0, 0.0, 0.0]
    _, events = labels(frames(speeds))
    assert not any(event.scenario == "high_magnitude_speed" for event in events)


def test_variable_duration_speed_intervals_preserve_real_bounds():
    speeds = [0.0, 0.0, 1.0, 1.0, 1.0, 8.0, 16.0, 16.0]
    times = [0.0, 0.07, 0.19, 0.31, 0.46, 0.60, 0.91, 1.25]
    _, events = labels(frames(speeds, times=times))
    ordered = speed_events(events)
    assert [(event.start_frame, event.end_frame) for event in ordered] == [(0, 1), (2, 4), (5, 5), (6, 7)]
    assert [(event.start_timestamp_s, event.end_timestamp_s) for event in ordered] == [(0.0, 0.07), (0.19, 0.46), (0.6, 0.6), (0.91, 1.25)]


def test_missing_invalid_and_negative_speed_break_intervals():
    speeds = [1.0, None, 1.0, float("nan"), 1.0, -1.0, 1.0]
    _, events = labels(frames(speeds))
    low = [event for event in speed_events(events) if event.scenario == "low_magnitude_speed"]
    assert [(event.start_frame, event.end_frame) for event in low] == [(0, 0), (2, 2), (4, 4), (6, 6)]
    classified_frames = {frame for event in low for frame in range(event.start_frame, event.end_frame + 1)}
    assert classified_frames == {0, 2, 4, 6}


def test_recording_with_all_speed_states_has_exactly_one_per_valid_frame():
    speeds = [0.1, 0.6, 6.0, 16.0, 14.0, 4.0, 0.2]
    _, events = labels(frames(speeds))
    ordered = speed_events(events)
    assert {event.scenario for event in ordered} == {
        "stationary", "low_magnitude_speed", "medium_magnitude_speed",
        "high_magnitude_speed",
    }
    for frame_index in range(len(speeds)):
        active = [event for event in ordered if event.start_frame <= frame_index <= event.end_frame]
        assert len(active) == 1
    assert all(not any("median" in key for key in event.evidence) for event in ordered)


def test_speed_intervals_never_overlap_by_frame_or_timestamp():
    _, events = labels(frames([0.0, 0.2, 0.5, 4.0, 5.0, 10.0, 15.0, 20.0]))
    ordered = speed_events(events)
    for previous, current in zip(ordered, ordered[1:]):
        assert previous.end_frame < current.start_frame
        assert previous.end_timestamp_s < current.start_timestamp_s


def test_stationary_versus_near_zero_movement():
    found, _ = labels(frames([0.49] * 21))
    assert found == ["stationary"]
    found, _ = labels(frames([0.5] * 2))
    assert found == ["low_magnitude_speed"]


def test_lateral_acceleration_below_at_and_above_threshold():
    times = [index * 0.1 for index in range(8)]
    velocities = [(0.0, value) for value in (0.0, 0.20, 0.45, 0.70, 0.95, 1.20, 1.45, 1.70)]
    found, events = labels(frames([2.0] * 8, times=times, velocities=velocities))
    assert "high_lateral_acceleration" in found
    event = next(event for event in events if event.scenario == "high_lateral_acceleration")
    assert event.evidence["peak_abs_lateral_acceleration_mps2"] >= 2.5


def test_lateral_acceleration_hysteresis_and_invalid_spike():
    times = [index * 0.1 for index in range(9)]
    lateral_accels = [0.0, 2.6, 2.2, 2.4, 1.9, 2.2, 2.6, 2.2]
    vy = [0.0]
    for accel in lateral_accels[1:]:
        vy.append(vy[-1] + accel * 0.1)
    found, events = labels(frames([3.0] * 8, times=times[:8], velocities=[(0.0, value) for value in vy]))
    assert found.count("high_lateral_acceleration") == 1
    broken = frames([3.0] * 8, velocities=[(0.0, value) for value in vy])
    broken[4]["ego"]["velocity_lcs_mps"] = None
    found, _ = labels(broken)
    assert found.count("high_lateral_acceleration") <= 1


def test_jerk_uses_irregular_timestamps_and_breaks_across_gap():
    input_frames = frames([1.0] * 5, times=[0.0, 0.1, 0.3, 0.4, 0.5], accelerations=[0.0, 0.0, 1.0, 2.0, 3.0])
    found, events = labels(input_frames)
    jerk = next(event for event in events if event.scenario == "high_magnitude_jerk")
    assert jerk.evidence["peak_jerk_mps3"] >= 10.0
    gap_frames = frames([1.0] * 4, times=[0.0, 0.1, 1.0, 1.1], accelerations=[0.0, 0.0, 10.0, 10.0])
    features = extract_ego_motion_features(gap_frames, max_sample_gap_s=0.5)
    assert features.jerk_mps3[2] is None


def test_vector_jerk_detects_acceleration_direction_change_at_equal_magnitude():
    input_frames = frames(
        [0.0, 1.0, math.sqrt(2.0), math.sqrt(5.0)],
        times=[0.0, 0.1, 0.2, 0.3],
        headings=[0.0, 0.0, 0.0, 0.0],
        accelerations=[0.0, 10.0, 0.0, 0.0],
        velocities=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (1.0, 2.0)],
    )
    vector = extract_ego_motion_features(
        input_frames, jerk_mode="acceleration_vector_magnitude"
    )
    legacy = extract_ego_motion_features(
        input_frames, jerk_mode="acceleration_magnitude"
    )
    assert math.isclose(vector.acceleration_magnitude_mps2[1], 10.0)
    assert math.isclose(vector.acceleration_magnitude_mps2[2], 10.0)
    assert math.isclose(vector.jerk_mps3[2], math.hypot(100.0, 100.0))
    assert math.isclose(legacy.jerk_mps3[2], 0.0)


def test_heading_wraparound():
    headings = [3.10, 3.13, -3.12, -3.09]
    features = extract_ego_motion_features(frames([2.0] * 4, headings=headings))
    assert features.unwrapped_heading_rad[-1] > features.unwrapped_heading_rad[0]
    assert features.unwrapped_heading_rad[-1] - features.unwrapped_heading_rad[0] < 0.2


def turn_frames(rate: float, speed: float = 4.0, count: int = 31):
    headings = [rate * index * 0.1 for index in range(count)]
    return frames([speed] * count, headings=headings, yaw_rates=[rate] * count)


def test_left_right_and_speed_qualified_turns():
    found, events = labels(turn_frames(0.1, 4.0))
    assert {"starting_left_turn", "starting_low_speed_turn"} <= set(found)
    ids = {event.evidence["physical_turn_event_id"] for event in events if "turn" in event.scenario}
    assert len(ids) == 1
    found, _ = labels(turn_frames(-0.1, 5.0))
    assert {"starting_right_turn", "starting_high_speed_turn"} <= set(found)


def test_turn_speed_uses_trigger_frame_not_a_median():
    low_at_trigger = turn_frames(0.1, 10.0)
    low_at_trigger[0]["ego"]["speed_mps"] = 4.0
    found, _ = labels(low_at_trigger)
    assert "starting_low_speed_turn" in found
    assert "starting_high_speed_turn" not in found

    high_at_trigger = turn_frames(0.1, 0.0)
    high_at_trigger[0]["ego"]["speed_mps"] = 6.0
    found, events = labels(high_at_trigger)
    assert "starting_high_speed_turn" in found
    assert "starting_low_speed_turn" not in found
    turn_evidence = [event.evidence for event in events if "turn" in event.scenario]
    assert all(evidence.get("trigger_speed_mps") == 6.0 for evidence in turn_evidence)
    assert all(not any("median" in key for key in evidence) for evidence in turn_evidence)


def test_gradual_curvature_and_short_noise_are_not_turns():
    found, _ = labels(turn_frames(0.05, count=61))
    assert not any("turn" in label for label in found)
    shallow_curve, _ = labels(turn_frames(0.088, count=31))
    assert not any("turn" in label for label in shallow_curve)
    noisy = turn_frames(0.0, count=20)
    noisy[5]["ego"]["yaw_rate_radps"] = 0.2
    assert not any("turn" in label for label in labels(noisy)[0])


def test_same_logical_lane_requires_sixty_degrees_for_turn() -> None:
    curved_lane = turn_frames(0.1, count=61)
    same_lane = {
        frame["frame_index"]: {"logical_lane_id": "route-a"}
        for frame in curved_lane
    }
    same_lane_events, _ = detect_events(curved_lane, frame_context=same_lane)
    assert not any("turn" in event.scenario for event in same_lane_events)

    lane_change = {
        frame["frame_index"]: {
            "logical_lane_id": "route-a" if frame["frame_index"] < 30 else "route-b"
        }
        for frame in curved_lane
    }
    lane_change_events, _ = detect_events(curved_lane, frame_context=lane_change)
    assert "starting_left_turn" in {event.scenario for event in lane_change_events}

    strong_turn = turn_frames(0.2, count=61)
    strong_context = {
        frame["frame_index"]: {"logical_lane_id": "route-a"}
        for frame in strong_turn
    }
    strong_events, _ = detect_events(strong_turn, frame_context=strong_context)
    turn = next(event for event in strong_events if event.scenario == "starting_left_turn")
    assert turn.evidence["same_logical_lane"] is True
    assert turn.evidence["threshold_mode"] == "same_logical_lane"


def test_event_spanning_overlapping_windows_is_same_recording_event():
    _, events = labels(turn_frames(0.1, count=61))
    event = next(event for event in events if event.scenario == "starting_left_turn")
    first = events_overlapping_window([event], 0, 49)
    second = events_overlapping_window([event], 25, 60)
    assert first[0] == second[0]


def test_adjacent_signals_merge_across_configured_gap():
    intervals = segment_signal([True, True, False, True, True], [0.0, 0.1, 0.2, 0.3, 0.4], maximum_inactive_gap_s=0.21)
    assert len(intervals) == 1


def test_missing_fields_non_monotonic_empty_and_single_frame():
    try:
        detect_events([{"frame_index": 0, "ego": {}}])
    except ValueError as exc:
        assert "time_since_start_s" in str(exc)
    else:
        raise AssertionError("missing timestamp must fail clearly")
    _, quality = detect_events(frames([1.0, 1.0], times=[0.1, 0.0]))
    assert quality["feature_quality_issues"][0].startswith("non_monotonic_timestamp")
    assert detect_events([])[0] == []
    found, _ = labels(frames([5.0]))
    assert found == ["medium_magnitude_speed"]


def test_invalid_configuration_fails_clearly():
    config = load_config()
    config["speed_bands"]["medium_magnitude_speed"]["minimum_mps"] = 4.0
    try:
        validate_config(config)
    except ValueError as exc:
        assert "overlapping" in str(exc)
    else:
        raise AssertionError("overlapping speed ranges must fail")
