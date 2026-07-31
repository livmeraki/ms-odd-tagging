"""Small serializable domain models used by the POC."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

Point = tuple[float, float]


@dataclass(frozen=True)
class Boundary:
    boundary_id: str
    points: tuple[Point, ...]
    source_kind: str = "lane_line"
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LaneCandidate:
    lane_id: str
    left_boundary_id: str
    right_boundary_id: str
    left: tuple[Point, ...]
    right: tuple[Point, ...]
    centerline: tuple[Point, ...]
    polygon: tuple[Point, ...]
    pair_score: float
    pair_metrics: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "lane_id": self.lane_id,
            "boundary_ids": {
                "left": self.left_boundary_id,
                "right": self.right_boundary_id,
            },
            "left_boundary_lcs_m": [list(point) for point in self.left],
            "right_boundary_lcs_m": [list(point) for point in self.right],
            "centerline_lcs_m": [list(point) for point in self.centerline],
            "polygon_lcs_m": [list(point) for point in self.polygon],
            "pair_score": round(self.pair_score, 4),
            "pair_metrics": self.pair_metrics,
        }
