"""Small, deterministic lane-state diagnostics used by debug-v2 tests/explorer."""
from __future__ import annotations
import math
from typing import Any


def wrap_deg(value: float) -> float:
    return abs(math.degrees(math.atan2(math.sin(math.radians(value)), math.cos(math.radians(value)))))

def direction_relation(heading_a_deg: float, heading_b_deg: float, threshold_deg: float) -> str:
    diff=wrap_deg(heading_a_deg-heading_b_deg)
    if diff <= threshold_deg:return "same_direction"
    if diff >= 180.0-threshold_deg:return "opposite_direction"
    return "crossing_or_diverging"

def deterministic_candidate(candidates: list[dict[str,Any]]) -> dict[str,Any] | None:
    if not candidates:return None
    return min(candidates,key=lambda c:(float(c.get("score",math.inf)),str(c.get("lane_id",""))))

def transition_kind(source_physical: str|None, target_physical: str|None, source_logical: str|None, target_logical: str|None, left_logical: str|None, right_logical: str|None) -> str:
    if target_physical is None:return "missing_lane"
    if source_physical != target_physical and source_logical and source_logical==target_logical:return "physical_fragment_transition_same_route"
    if source_logical==target_logical:return "same_lane"
    if target_logical and target_logical==left_logical:return "lane_change_left_candidate"
    if target_logical and target_logical==right_logical:return "lane_change_right_candidate"
    return "unexplained_route_transition"
