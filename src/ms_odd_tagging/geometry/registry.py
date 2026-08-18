"""Authoritative ownership map for geometry implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


GeometryStatus = Literal["canonical", "candidate", "experiment"]


@dataclass(frozen=True)
class GeometryOwner:
    module: str
    status: GeometryStatus
    responsibility: str


GEOMETRY_OWNERS: dict[str, GeometryOwner] = {
    "canonical_ld_normalization": GeometryOwner(
        "ms_odd_tagging.canonical.core_odld",
        "canonical",
        "Normalize recording-level LD and attach nearby references to frames.",
    ),
    "following_lane": GeometryOwner(
        "ms_odd_tagging.scenarios.following_lane",
        "canonical",
        "Physical ego-lane and lead-vehicle assignment.",
    ),
    "ld_topology": GeometryOwner(
        "ms_odd_tagging.ld_topology",
        "candidate",
        "Topology and intersection reconstruction candidate.",
    ),
    "bev_lane": GeometryOwner(
        "ms_odd_tagging.bev_lane_poc",
        "experiment",
        "Independent BEV lane reconstruction hypothesis.",
    ),
    "lanelet2": GeometryOwner(
        "ms_odd_tagging.lanelet2_poc",
        "experiment",
        "Optional Lanelet2-backed reconstruction hypothesis.",
    ),
}


def get_geometry_owner(capability: str) -> GeometryOwner:
    try:
        return GEOMETRY_OWNERS[capability]
    except KeyError as exc:
        known = ", ".join(sorted(GEOMETRY_OWNERS))
        raise KeyError(f"unknown geometry capability {capability!r}; choose one of: {known}") from exc
