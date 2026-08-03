"""Configuration for the isolated BEV lane-detection POC."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "feature_enabled": False,
    "left_m": 45.0,
    "right_m": 45.0,
    "back_m": 25.0,
    "forward_m": 95.0,
    "local_forward_m": 95.0,
    "local_backward_m": 25.0,
    "local_lateral_m": 45.0,
    "minimum_boundary_length_m": 4.0,
    "maximum_boundary_segment_gap_m": 15.0,
    "merge_boundary_fragments": True,
    "maximum_boundary_merge_gap_m": 12.0,
    "maximum_boundary_merge_lateral_offset_m": 0.8,
    "maximum_boundary_merge_heading_difference_deg": 10.0,
    "minimum_longitudinal_overlap_m": 5.0,
    "minimum_lane_width_m": 2.2,
    "maximum_lane_width_m": 5.2,
    "maximum_lane_width_range_m": 2.0,
    "maximum_pair_heading_difference_deg": 22.0,
    "maximum_ego_heading_difference_deg": 55.0,
    "maximum_centerline_distance_m": 4.5,
    "outside_polygon_tolerance_m": 1.2,
    "minimum_pair_score": 0.2,
    "ambiguity_score_margin": 0.12,
    "resample_count": 20,
    "exclude_virtual_lane_lines": True,
    "include_drivable_road_boundaries": True,
    "deduplicate_centerline_distance_m": 0.75,
    "deduplicate_lateral_distance_m": 0.9,
    "minimum_adjacent_lateral_offset_m": 1.5,
    "maximum_adjacent_lateral_offset_m": 8.0,
    "maximum_adjacent_heading_difference_deg": 25.0,
    "extend_lane_boundaries": False,
    "lane_extension_forward_m": 18.0,
    "lane_extension_backward_m": 8.0,
    "lane_extension_step_m": 2.5,
    "lane_extension_fit_points": 5,
    "lane_extension_min_source_length_m": 6.0,
    "lane_extension_allow_curvature": True,
    "lane_extension_max_heading_change_deg": 30.0,
    "lane_extension_max_lateral_drift_m": 3.0,
}


def load_config(path: Path | None = None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    if path is not None:
        config.update(json.loads(path.read_text(encoding="utf-8")))
    if overrides:
        config.update(overrides)
    config["local_forward_m"] = float(config.get("local_forward_m", config["forward_m"]))
    config["local_backward_m"] = float(config.get("local_backward_m", config["back_m"]))
    config["local_lateral_m"] = max(float(config["left_m"]), float(config["right_m"]))
    return config
