"""Canonical recording adapter and per-frame POC runner."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable, Iterable

from .geometry import filter_local_boundaries, match_ego, pair_boundaries
from .lanelet_backend import (
    Lanelet2Unavailable,
    available,
    build_routing_context,
    geometric_neighbors,
    query_neighbors,
)
from .models import Boundary, LaneCandidate

LogFunction = Callable[[dict[str, Any]], None]


def boundaries_from_recording(recording: dict[str, Any], config: dict[str, Any]) -> list[Boundary]:
    store = recording.get("ld_feature_store") or {}
    points = {
        str(point.get("point_id")): tuple(point["position_lcs_m"][:2])
        for point in store.get("points", [])
        if len(point.get("position_lcs_m") or []) >= 2
    }
    output = []
    for feature in store.get("lane_lines", []):
        feature_points = tuple(
            points[str(point_id)]
            for point_id in feature.get("point_ids", [])
            if str(point_id) in points
        )
        output.append(
            Boundary(
                str(feature["line_id"]),
                feature_points,
                "lane_line",
                feature.get("attributes") or {},
            )
        )
    if config.get("include_drivable_road_boundaries", True):
        for feature in store.get("road_boundaries", []):
            if str(feature.get("boundary_attribute", "")).lower() != "drivable":
                continue
            feature_points = tuple(
                points[str(point_id)]
                for point_id in feature.get("point_ids", [])
                if str(point_id) in points
            )
            output.append(
                Boundary(
                    str(feature["road_boundary_id"]),
                    feature_points,
                    "drivable_road_boundary",
                    {
                        **(feature.get("attributes") or {}),
                        "boundary_attribute": "drivable",
                    },
                )
            )
    return output


def _lane_output(
    lane: LaneCandidate | None,
    confidence: float | None = None,
    *,
    rejection_reasons: list[str] | None = None,
    selection_source: str | None = None,
) -> dict[str, Any]:
    if lane is None:
        return {
            "exists": False,
            "lane_id": None,
            "boundary_ids": {"left": None, "right": None},
            "polygon_lcs_m": [],
            "confidence": 0.0,
            "selection_source": selection_source,
            "rejection_reasons": rejection_reasons or [],
        }
    value = lane.as_dict()
    return {
        "exists": True,
        "lane_id": lane.lane_id,
        "boundary_ids": value["boundary_ids"],
        "polygon_lcs_m": value["polygon_lcs_m"],
        "confidence": round(lane.pair_score if confidence is None else confidence, 4),
        "selection_source": selection_source,
        "rejection_reasons": rejection_reasons or [],
    }


def run_frame(
    boundaries: Iterable[Boundary],
    ego: tuple[float, float, float],
    config: dict[str, Any],
    *,
    frame_index: int | None = None,
    log: LogFunction | None = None,
) -> dict[str, Any]:
    if len(ego) != 3 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in ego):
        return {
            "frame_index": frame_index,
            "status": "invalid_input",
            "rejection_reasons": ["ego_pose_must_be_finite_x_y_yaw"],
            "ego_lane": _lane_output(None, rejection_reasons=["invalid_ego_pose"]),
            "left_adjacent": _lane_output(None, rejection_reasons=["invalid_ego_pose"]),
            "right_adjacent": _lane_output(None, rejection_reasons=["invalid_ego_pose"]),
        }
    local, boundary_rejections = filter_local_boundaries(boundaries, ego, config)
    lanes, pair_rejections = pair_boundaries(local, ego, config)
    match = match_ego(lanes, ego, config)
    by_id = {lane.lane_id: lane for lane in lanes}
    ego_lane_id = match["lane_id"]
    routing_queries = {
        "left": None,
        "right": None,
        "adjacentLeft": None,
        "adjacentRight": None,
    }
    routing_backend = "unavailable"
    routing_error = None
    neighbors = {"left": None, "right": None}
    neighbor_sources = {"left": None, "right": None}
    if ego_lane_id:
        neighbors = geometric_neighbors(lanes, ego_lane_id)
        for side in ("left", "right"):
            if neighbors[side]:
                neighbor_sources[side] = "shared_boundary_geometric_fallback"
        if available():
            try:
                context = build_routing_context(lanes, config, local)
                routing_queries = query_neighbors(context, ego_lane_id)
                routing_backend = "lanelet2"
                neighbors["left"] = (
                    routing_queries["left"]
                    or routing_queries["adjacentLeft"]
                    or neighbors["left"]
                )
                neighbor_sources["left"] = (
                    "lanelet2_left"
                    if routing_queries["left"]
                    else "lanelet2_adjacentLeft"
                    if routing_queries["adjacentLeft"]
                    else neighbor_sources["left"]
                )
                neighbors["right"] = (
                    routing_queries["right"]
                    or routing_queries["adjacentRight"]
                    or neighbors["right"]
                )
                neighbor_sources["right"] = (
                    "lanelet2_right"
                    if routing_queries["right"]
                    else "lanelet2_adjacentRight"
                    if routing_queries["adjacentRight"]
                    else neighbor_sources["right"]
                )
            except (Lanelet2Unavailable, RuntimeError, ValueError, AttributeError) as exc:
                routing_error = str(exc)
                routing_backend = "geometric_fallback"
        else:
            routing_backend = "geometric_fallback"
            routing_error = "lanelet2_bindings_unavailable"
    result = {
        "frame_index": frame_index,
        "status": "matched" if ego_lane_id else "unmatched",
        "ego_pose_lcs": {"x": ego[0], "y": ego[1], "yaw": ego[2]},
        "ego_lane": _lane_output(
            by_id.get(ego_lane_id),
            match.get("confidence"),
            rejection_reasons=[] if ego_lane_id else ["no_acceptable_ego_lane"],
            selection_source=match.get("method"),
        ),
        "left_adjacent": _lane_output(
            by_id.get(neighbors["left"]),
            rejection_reasons=[]
            if neighbors["left"]
            else ["no_legal_or_geometric_left_neighbor"],
            selection_source=neighbor_sources["left"],
        ),
        "right_adjacent": _lane_output(
            by_id.get(neighbors["right"]),
            rejection_reasons=[]
            if neighbors["right"]
            else ["no_legal_or_geometric_right_neighbor"],
            selection_source=neighbor_sources["right"],
        ),
        "routing": {
            "backend": routing_backend,
            "queries": routing_queries,
            "error": routing_error,
            "fallback": "shared_boundary_geometric_adjacency",
        },
        "matching": match,
        "candidate_lanelets": [lane.as_dict() for lane in lanes],
        "rejections": {
            "boundaries": boundary_rejections,
            "pairs": pair_rejections,
        },
        "debug_overlay": {
            "local_boundary_ids": [boundary.boundary_id for boundary in local],
            "candidate_lane_ids": [lane.lane_id for lane in lanes],
        }
        if config.get("debug_overlays", True)
        else None,
    }
    if log:
        log(
            {
                "event": "lanelet2_poc_frame",
                "frame_index": frame_index,
                "status": result["status"],
                "local_boundary_count": len(local),
                "candidate_lanelet_count": len(lanes),
                "ego_lane_id": ego_lane_id,
                "left_adjacent_lane_id": neighbors["left"],
                "right_adjacent_lane_id": neighbors["right"],
                "routing_backend": routing_backend,
            }
        )
    return result


def run_recording(
    recording: dict[str, Any],
    config: dict[str, Any],
    *,
    frame_indices: set[int] | None = None,
    log: LogFunction | None = None,
) -> dict[str, Any]:
    if not config.get("feature_enabled", False):
        return {
            "schema_version": "lanelet2-lcs-poc-v1",
            "feature_enabled": False,
            "status": "disabled",
            "recording_id": recording.get("recording_id"),
            "coordinate_system": "LCS",
            "frames": [],
        }
    boundaries = boundaries_from_recording(recording, config)
    frames = []
    for source in recording.get("frames", []):
        frame_index = int(source["frame_index"])
        if frame_indices is not None and frame_index not in frame_indices:
            continue
        ego_source = source.get("ego") or {}
        position = ego_source.get("position_lcs_m") or []
        yaw = ego_source.get("heading_lcs_rad")
        ego = (
            float(position[0]) if len(position) >= 2 else math.nan,
            float(position[1]) if len(position) >= 2 else math.nan,
            float(yaw) if isinstance(yaw, (int, float)) else math.nan,
        )
        frames.append(run_frame(boundaries, ego, config, frame_index=frame_index, log=log))
    return {
        "schema_version": "lanelet2-lcs-poc-v1",
        "feature_enabled": bool(config.get("feature_enabled")),
        "recording_id": recording.get("recording_id"),
        "coordinate_system": "LCS",
        "lanelet2_available": available(),
        "assumptions": [
            "Temporary lanelets are inferred from detected boundaries, not an HD map.",
            "Lanelet2 legal routing results are experimental without regulatory elements.",
            "Geometric fallback adjacency requires a shared inferred boundary.",
        ],
        "config": config,
        "frames": frames,
    }


def jsonl_logger(path: Path) -> LogFunction:
    path.parent.mkdir(parents=True, exist_ok=True)

    def write(event: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=True, separators=(",", ":")) + "\n")

    return write
