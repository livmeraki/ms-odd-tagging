"""Configuration for the isolated Lanelet2 POC."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "feature_enabled": False,
    "require_lanelet2": True,
    "location": "Germany",
    "participant": "Vehicle",
    "local_forward_m": 100.0,
    "local_backward_m": 30.0,
    "local_lateral_m": 22.0,
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
    "maximum_centerline_distance_m": 4.0,
    "outside_polygon_tolerance_m": 0.8,
    "minimum_pair_score": 0.35,
    "ambiguity_score_margin": 0.12,
    "resample_count": 20,
    "exclude_virtual_lane_lines": True,
    "include_drivable_road_boundaries": True,
    "debug_overlays": True,
}


def load_config(path: Path | None = None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    if path is not None:
        config.update(json.loads(path.read_text(encoding="utf-8")))
    if overrides:
        config.update(overrides)
    return config
