"""Serializable domain models for LD topology detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Point = tuple[float, float]
Evidence = Literal["strong", "partial", "none"]
TopologyClass = Literal["normal", "intersection_unknown", "x-intersection", "y-intersection", "t-intersection", "roundabout"]


@dataclass(frozen=True)
class Edge:
    edge_id: str
    source_kind: Literal["line", "road_boundary"]
    points: tuple[Point, ...]
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def intersection(self) -> bool:
        return self.source_kind == "line" and bool((self.attributes or {}).get("intersection") is True)


@dataclass(frozen=True)
class LaneGeometry:
    lane_id: str
    left_edge_id: str
    right_edge_id: str
    left_source_kind: str
    right_source_kind: str
    left_boundary: tuple[Point, ...]
    right_boundary: tuple[Point, ...]
    centerline: tuple[Point, ...]
    polygon: tuple[Point, ...]
    left_boundary_intersection: bool
    right_boundary_intersection: bool
    intersection_evidence: Evidence
    validation: dict[str, Any]
    geometry_source: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "lane_id": self.lane_id,
            "boundary_ids": {"left": self.left_edge_id, "right": self.right_edge_id},
            "boundary_source_kinds": {"left": self.left_source_kind, "right": self.right_source_kind},
            "left_boundary_intersection": self.left_boundary_intersection,
            "right_boundary_intersection": self.right_boundary_intersection,
            "intersection_evidence": self.intersection_evidence,
            "left_boundary_lcs_m": [list(p) for p in self.left_boundary],
            "right_boundary_lcs_m": [list(p) for p in self.right_boundary],
            "centerline_lcs_m": [list(p) for p in self.centerline],
            "polygon_lcs_m": [list(p) for p in self.polygon],
            "validation": self.validation,
            "geometry_source": self.geometry_source,
        }


@dataclass(frozen=True)
class Component:
    component_id: str
    lane_ids: tuple[str, ...]
    evidence_counts: dict[str, int]
    center: Point
    core_polygon: tuple[Point, ...]
    core_radius_m: float
    polygon_valid: bool
    confidence: float
    diagnostics: dict[str, Any]


@dataclass(frozen=True)
class Arm:
    arm_id: str
    angle_deg: float
    crossing_point: Point
    lane_ids: tuple[str, ...]
    confidence: float
    direction: str = "unknown"
    continuation_lane_ids: tuple[str, ...] = ()
    outside_axis_angle_deg: float | None = None
