"""Configuration for the Qwen VLM scenario-tagging POC."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ms_odd_tagging.common.config import CANONICAL, OUTPUT_ROOT
from ms_odd_tagging.common.scenario_catalog import (
    vlm_candidate_groups,
    vlm_labels_for_group,
)


TRAFFIC_LIGHT_LABELS = vlm_labels_for_group("traffic_light_episode")
SCENARIOS = vlm_candidate_groups()


@dataclass(frozen=True)
class VlmPocConfig:
    model: str = "Qwen/Qwen3-VL-8B-Instruct"
    endpoint: str = "http://127.0.0.1:8001/v1/chat/completions"
    timeout_s: float = 45.0
    retries: int = 1
    temperature: float = 0.0
    max_tokens: int = 256
    response_format_json: bool = True
    window_seconds: float = 5.0
    frames_per_second: float = 2.0
    max_bev_images: int = 6
    candidate_stride_seconds: float = 2.5
    acceptance_threshold: float = 0.72
    review_threshold: float = 0.45
    minimum_duration_s: float = 0.5
    maximum_inactive_gap_s: float = 1.25
    overlap_threshold: float = 0.25
    boundary_hysteresis_s: float = 0.25
    max_request_bytes: int = 8_000_000
    cache_enabled: bool = True
    input_dir: Path = CANONICAL
    output_root: Path = OUTPUT_ROOT / "qwen_vlm_poc"
    bev_extent_m: tuple[float, float, float, float] = (45.0, 45.0, 25.0, 70.0)
    bev_size_px: tuple[int, int] = (768, 768)
    pedestrian_near_radius_m: float = 30.0
    pedestrian_corridor_lateral_m: float = 5.0
    pedestrian_forward_m: float = 40.0
    pedestrian_behind_m: float = 8.0
    pedestrian_slow_speed_mps: float = 2.0
    pedestrian_decel_mps2: float = -0.4
    intersection_classes: tuple[str, ...] = (
        "intersection_unknown",
        "x-intersection",
        "t-intersection",
        "y-intersection",
        "roundabout",
    )
    minimum_intersection_confidence: float = 0.25
    u_turn_min_heading_change_rad: float = 1.2
    u_turn_min_cumulative_heading_change_rad: float = 1.5
    traffic_light_classes: tuple[str, ...] = (
        "traffic_light",
        "traffic_light_car",
        "traffic_light_pedestrian",
    )
    traffic_light_episode_merge_gap_s: float = 1.5
    traffic_light_episode_min_signal_frames: int = 1
    traffic_light_stopline_near_m: float = 35.0
    traffic_light_forward_m: float = 70.0
    traffic_light_backward_m: float = 8.0
    traffic_light_path_lateral_m: float = 12.0
    traffic_light_lead_forward_m: float = 45.0
    traffic_light_lead_lateral_m: float = 4.0
    prompt_version: str = "qwen-vlm-poc-v1"
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["input_dir"] = str(self.input_dir)
        data["output_root"] = str(self.output_root)
        return data


def load_config(path: Path | None = None, overrides: dict[str, Any] | None = None) -> VlmPocConfig:
    """Load JSON config plus caller overrides."""
    data: dict[str, Any] = {}
    if path is not None:
        import json

        data.update(json.loads(path.read_text(encoding="utf-8")))
    if overrides:
        data.update({key: value for key, value in overrides.items() if value is not None})
    for key in ("input_dir", "output_root"):
        if key in data and not isinstance(data[key], Path):
            data[key] = Path(data[key])
    for key in ("bev_extent_m", "bev_size_px", "intersection_classes", "traffic_light_classes"):
        if key in data and isinstance(data[key], list):
            data[key] = tuple(data[key])
    return VlmPocConfig(**data)
