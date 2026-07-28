"""Generic hysteretic temporal segmentation for current and future detectors."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence

@dataclass(frozen=True)
class SegmentedInterval:
    start_index: int
    end_index: int
    trigger_start_index: int
    trigger_end_index: int
    active_indices: tuple[int, ...]

def segment_signal(values: Sequence[float | bool | None], timestamps_s: Sequence[float], *, onset_threshold: float = 1.0, release_threshold: float | None = None, minimum_duration_s: float = 0.0, maximum_inactive_gap_s: float = 0.0, merge_gap_s: float = 0.0, pre_roll_s: float = 0.0, post_roll_s: float = 0.0) -> list[SegmentedInterval]:
    """Segment Boolean or non-negative scores; invalid samples break events."""
    if len(values) != len(timestamps_s):
        raise ValueError("values and timestamps_s must have equal length")
    if any(value < 0 for value in (minimum_duration_s, maximum_inactive_gap_s, merge_gap_s, pre_roll_s, post_roll_s)):
        raise ValueError("segmentation durations cannot be negative")
    release = onset_threshold if release_threshold is None else release_threshold
    if release > onset_threshold:
        raise ValueError("release_threshold cannot exceed onset_threshold")
    raw: list[tuple[int, int, tuple[int, ...]]] = []
    start: int | None = None
    last_active: int | None = None
    active: list[int] = []
    def finish() -> None:
        nonlocal start, last_active, active
        if start is not None and last_active is not None and timestamps_s[last_active] - timestamps_s[start] >= minimum_duration_s:
            raw.append((start, last_active, tuple(active)))
        start = last_active = None
        active = []
    for index, value in enumerate(values):
        if value is None or (index and timestamps_s[index] <= timestamps_s[index - 1]):
            finish(); continue
        score = float(value)
        if start is None:
            if score >= onset_threshold:
                start = last_active = index; active = [index]
        elif score >= release:
            last_active = index; active.append(index)
        elif last_active is not None and timestamps_s[index] - timestamps_s[last_active] > maximum_inactive_gap_s:
            finish()
    finish()
    merged: list[tuple[int, int, tuple[int, ...]]] = []
    for current in raw:
        if merged and timestamps_s[current[0]] - timestamps_s[merged[-1][1]] <= merge_gap_s:
            previous = merged.pop(); merged.append((previous[0], current[1], previous[2] + current[2]))
        else:
            merged.append(current)
    result = []
    for trigger_start, trigger_end, active_indices in merged:
        start_index, end_index = trigger_start, trigger_end
        while start_index > 0 and timestamps_s[trigger_start] - timestamps_s[start_index - 1] <= pre_roll_s: start_index -= 1
        while end_index + 1 < len(values) and timestamps_s[end_index + 1] - timestamps_s[trigger_end] <= post_roll_s: end_index += 1
        result.append(SegmentedInterval(start_index, end_index, trigger_start, trigger_end, active_indices))
    return result
