"""Trajectory-only dynamics detectors."""
from __future__ import annotations
import math
from statistics import median
from typing import Any
from ms_odd_tagging.features.ego_motion import EgoMotionFeatures
from .event_segmentation import SegmentedInterval, segment_signal
from .scenario_event import ScenarioEvent

SPEED_BAND_ORDER = (
    "stationary",
    "low_magnitude_speed",
    "medium_magnitude_speed",
    "high_magnitude_speed",
)


def classify_speed_band(speed_mps: float | None, config: dict[str, Any]) -> str | None:
    """Return the one configured speed band for a valid sample, else ``None``."""
    if speed_mps is None or not math.isfinite(speed_mps) or speed_mps < 0:
        return None
    for name in SPEED_BAND_ORDER:
        band = config["speed_bands"][name]
        minimum = float(band["minimum_mps"])
        maximum = band["maximum_mps"]
        if speed_mps < minimum:
            continue
        if maximum is None or speed_mps < float(maximum):
            return name
        if band["maximum_inclusive"] and speed_mps == float(maximum):
            return name
    return None


def _stabilized_speed_states(speed_values: list[float | None], config: dict[str, Any]) -> list[str | None]:
    """Suppress single-frame spikes that rise above a much quieter neighborhood."""
    states = [classify_speed_band(speed, config) for speed in speed_values]
    band_order = {name: index for index, name in enumerate(SPEED_BAND_ORDER)}
    for index in range(len(states)):
        if states[index] is None:
            continue
        if index == 0 or index == len(states) - 1:
            continue
        previous_state = states[index - 1]
        next_state = states[index + 1]
        if previous_state is None or next_state is None:
            continue
        current_rank = band_order[states[index]]
        previous_rank = band_order[previous_state]
        next_rank = band_order[next_state]
        if current_rank >= 2 and previous_rank <= current_rank - 2 and next_rank <= current_rank - 2:
            states[index] = None
    return states


def _event(scenario: str, interval: SegmentedInterval, features: EgoMotionFeatures, config: dict[str, Any], evidence: dict[str, Any]) -> ScenarioEvent:
    start, end = interval.start_index, interval.end_index
    return ScenarioEvent(scenario, features.frame_index[start], features.frame_index[end], features.timestamp_s[start], features.timestamp_s[end], round(features.timestamp_s[end] - features.timestamp_s[start], 6), detector_version=config["detector_version"], evidence=evidence)

class SpeedBandDetector:
    scenario_name = "speed_bands"
    required_features = frozenset({"speed_mps"})
    output_scenarios = frozenset(SPEED_BAND_ORDER)
    def detect(self, frames: list[dict[str, Any]], features: EgoMotionFeatures, config: dict[str, Any]) -> list[ScenarioEvent]:
        events: list[ScenarioEvent] = []
        raw_speeds = features.speed_mps
        states = _stabilized_speed_states(raw_speeds, config)
        for name in SPEED_BAND_ORDER:
            band = config["speed_bands"][name]
            low, high = float(band["minimum_mps"]), band["maximum_mps"]
            signal = [None if state is None else state == name for state in states]
            for interval in segment_signal(signal, features.timestamp_s, minimum_duration_s=float(band["minimum_duration_s"])):
                speeds = [raw_speeds[i] for i in interval.active_indices if raw_speeds[i] is not None]
                events.append(_event(name, interval, features, config, {"start_speed_mps": speeds[0], "end_speed_mps": speeds[-1], "minimum_speed_mps": min(speeds), "maximum_speed_mps": max(speeds), "classification_mode": "exclusive_per_frame_speed", "band_minimum_mps": low, "band_maximum_mps": high, "maximum_inclusive": band["maximum_inclusive"], "interval_boundary_convention": "inclusive_samples", "threshold_provenance": band["provenance"]}))
        return events

class LateralAccelerationDetector:
    scenario_name = "high_lateral_acceleration"
    required_features = frozenset({"lateral_acceleration_mps2"})
    output_scenarios = frozenset({scenario_name})
    def detect(self, frames: list[dict[str, Any]], features: EgoMotionFeatures, config: dict[str, Any]) -> list[ScenarioEvent]:
        rule = config["lateral_acceleration"]
        signal = [abs(value) if value is not None else None for value in features.lateral_acceleration_mps2]
        events = []
        for interval in segment_signal(signal, features.timestamp_s, onset_threshold=rule["entry_abs_mps2"], release_threshold=rule["exit_abs_mps2"], minimum_duration_s=rule["minimum_duration_s"], maximum_inactive_gap_s=rule["maximum_inactive_gap_s"]):
            signed = [features.lateral_acceleration_mps2[i] for i in interval.active_indices if features.lateral_acceleration_mps2[i] is not None]
            peak = max(signed, key=abs); peak_index = next(i for i in interval.active_indices if features.lateral_acceleration_mps2[i] == peak)
            events.append(_event(self.scenario_name, interval, features, config, {"peak_abs_lateral_acceleration_mps2": abs(peak), "peak_signed_lateral_acceleration_mps2": peak, "representative_abs_lateral_acceleration_mps2": median(abs(value) for value in signed), "peak_frame": features.frame_index[peak_index], "entry_threshold_abs_mps2": rule["entry_abs_mps2"], "exit_threshold_abs_mps2": rule["exit_abs_mps2"], "threshold_provenance": rule["provenance"]}))
        return events

class JerkDetector:
    scenario_name = "high_magnitude_jerk"
    required_features = frozenset({"jerk_mps3"})
    output_scenarios = frozenset({scenario_name})
    def detect(self, frames: list[dict[str, Any]], features: EgoMotionFeatures, config: dict[str, Any]) -> list[ScenarioEvent]:
        rule = config["jerk"]; events = []
        for interval in segment_signal(features.jerk_mps3, features.timestamp_s, onset_threshold=rule["entry_abs_mps3"], release_threshold=rule["exit_abs_mps3"], minimum_duration_s=rule["minimum_duration_s"], maximum_inactive_gap_s=rule["maximum_inactive_gap_s"]):
            values = [features.jerk_mps3[i] for i in interval.active_indices if features.jerk_mps3[i] is not None]
            if rule["reject_isolated_spikes"] and len(values) < 2: continue
            peak = max(values); peak_index = next(i for i in interval.active_indices if features.jerk_mps3[i] == peak)
            events.append(_event(self.scenario_name, interval, features, config, {"calculation_mode": rule["calculation_mode"], "peak_jerk_mps3": peak, "representative_jerk_mps3": median(values), "peak_frame": features.frame_index[peak_index], "entry_threshold_abs_mps3": rule["entry_abs_mps3"], "exit_threshold_abs_mps3": rule["exit_abs_mps3"], "threshold_provenance": rule["provenance"]}))
        return events
