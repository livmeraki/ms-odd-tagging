"""Piece-local static lane ordering for the integrated lane-debug-v2 pipeline.

Reference-track stations remain defined on the track centerline, but candidate
tracks are projected through their actual local pieces. This prevents a merged
track centerline from hiding a nearby static_inferred_corridor or connector.
"""
from __future__ import annotations

import math
from typing import Any

from .lane_geometry import wrap_angle
from .static_lane_order import _project, _sample

_LOCAL_PIECE_KINDS = {
    "observed_ld",
    "recovered_full_edge",
    "inferred_gap",
    "anchored_ld_bridge",
    "canonical_track_stitch",
    "topology_supported_curvature_stitch",
    "ego_supported_inferred_route",
    "static_inferred_corridor",
    "static_inferred_connector",
}


def _track_piece_projections(point, track: dict[str, Any]) -> list[dict[str, Any]]:
    projections = []
    for index, piece in enumerate(track.get("pieces") or []):
        kind = str(piece.get("kind"))
        if kind not in _LOCAL_PIECE_KINDS:
            continue
        proj = _project(point, piece.get("centerline_lcs_m") or [])
        if proj is None:
            continue
        projections.append({
            **proj,
            "projection_piece_kind": kind,
            "projection_piece_index": index,
            "projection_piece_lane_id": piece.get("lane_id"),
        })
    if projections:
        return projections
    proj = _project(point, track.get("centerline_lcs_m") or [])
    if proj is None:
        return []
    return [{**proj, "projection_piece_kind": "track_centerline_fallback", "projection_piece_index": None, "projection_piece_lane_id": None}]


def _track_local_projection(point, track: dict[str, Any]) -> dict[str, Any] | None:
    projections = _track_piece_projections(point, track)
    return min(projections, key=lambda item: float(item["distance_m"])) if projections else None


def _reference_samples(track: dict[str, Any], spacing_m: float) -> list[dict[str, Any]]:
    rows = []
    for index, piece in enumerate(track.get("pieces") or []):
        kind = str(piece.get("kind"))
        if kind not in _LOCAL_PIECE_KINDS:
            continue
        for sample in _sample(piece.get("centerline_lcs_m") or [], spacing_m):
            rows.append({
                **sample,
                "reference_piece_kind": kind,
                "reference_piece_index": index,
                "reference_piece_lane_id": piece.get("lane_id"),
            })
    if rows:
        return rows
    return [{**sample, "reference_piece_kind": "track_centerline_fallback", "reference_piece_index": None, "reference_piece_lane_id": None}
            for sample in _sample(track.get("centerline_lcs_m") or [], spacing_m)]


def _evaluate_projection(
    reference_point, reference_heading: float, track_id: str, projection: dict[str, Any],
    *, maximum_heading_difference_deg: float, minimum_lateral_m: float,
    maximum_lateral_m: float, maximum_longitudinal_m: float,
) -> dict[str, Any]:
    c, s = math.cos(reference_heading), math.sin(reference_heading)
    dx = float(projection["point"][0]) - reference_point[0]
    dy = float(projection["point"][1]) - reference_point[1]
    longitudinal = c * dx + s * dy
    lateral = -s * dx + c * dy
    heading_difference = abs(math.degrees(wrap_angle(float(projection["heading_rad"]) - reference_heading)))
    reasons = []
    if heading_difference > maximum_heading_difference_deg:
        reasons.append("heading_difference")
    if abs(lateral) < minimum_lateral_m:
        reasons.append("lateral_below_minimum")
    if abs(lateral) > maximum_lateral_m:
        reasons.append("lateral_above_maximum")
    if abs(longitudinal) > maximum_longitudinal_m:
        reasons.append("longitudinal_too_far")
    return {
        "track_id": track_id,
        "projection_piece_kind": projection.get("projection_piece_kind"),
        "projection_piece_index": projection.get("projection_piece_index"),
        "projection_piece_lane_id": projection.get("projection_piece_lane_id"),
        "projected_point": projection.get("point"),
        "projected_heading_rad": projection.get("heading_rad"),
        "signed_lateral_m": round(lateral, 6),
        "longitudinal_m": round(longitudinal, 6),
        "heading_difference_deg": round(heading_difference, 6),
        "distance_m": round(float(projection["distance_m"]), 6),
        "rejection_reasons": reasons,
        "accepted": not reasons,
    }


def build_static_lane_order(
    tracks: list[dict[str, Any]],
    *,
    sample_spacing_m: float = 2.0,
    maximum_heading_difference_deg: float = 20.0,
    minimum_lateral_m: float = 1.5,
    maximum_lateral_m: float = 8.0,
    maximum_longitudinal_m: float = 8.0,
) -> dict[str, Any]:
    by_id = {str(t.get("track_id")): t for t in tracks}
    samples_by_track: dict[str, list[dict[str, Any]]] = {}
    for track_id, track in by_id.items():
        rows = []
        for sample in _reference_samples(track, sample_spacing_m):
            p, h = sample["point"], float(sample["heading_rad"])
            evaluations = []
            candidates = []
            for other_id, other in by_id.items():
                if other_id == track_id:
                    continue
                piece_evaluations = [_evaluate_projection(
                    p, h, other_id, projection,
                    maximum_heading_difference_deg=maximum_heading_difference_deg,
                    minimum_lateral_m=minimum_lateral_m,
                    maximum_lateral_m=maximum_lateral_m,
                    maximum_longitudinal_m=maximum_longitudinal_m,
                ) for projection in _track_piece_projections(p, other)]
                accepted = [item for item in piece_evaluations if item["accepted"]]
                if accepted:
                    winner = min(accepted, key=lambda item: (
                        abs(item["longitudinal_m"]), abs(item["signed_lateral_m"]),
                        item["distance_m"], item["projection_piece_index"] if item["projection_piece_index"] is not None else -1,
                    ))
                    winner["track_piece_winner"] = True
                    candidates.append(winner)
                evaluations.extend(piece_evaluations)
            left = sorted((x for x in candidates if x["signed_lateral_m"] > 0), key=lambda x: (x["signed_lateral_m"], abs(x["longitudinal_m"]), x["track_id"]))
            right = sorted((x for x in candidates if x["signed_lateral_m"] < 0), key=lambda x: (abs(x["signed_lateral_m"]), abs(x["longitudinal_m"]), x["track_id"]))
            immediate = {item["track_id"] for item in ((left[0] if left else None), (right[0] if right else None)) if item}
            for candidate in candidates:
                if candidate["track_id"] not in immediate:
                    candidate["accepted"] = False
                    candidate["rejection_reasons"].append("not_immediate_neighbor")
            rows.append({
                "station_m": round(float(sample["station_m"]), 3),
                "point": p,
                "heading_rad": h,
                "reference_piece_kind": sample.get("reference_piece_kind"),
                "reference_piece_index": sample.get("reference_piece_index"),
                "reference_piece_lane_id": sample.get("reference_piece_lane_id"),
                "left": left[0] if left else None,
                "right": right[0] if right else None,
                "ordered_candidates": sorted(candidates, key=lambda x: -x["signed_lateral_m"]),
                "candidate_evaluations": evaluations,
            })
        samples_by_track[track_id] = rows
    return {
        "method": "static_cross_section_piece_local_lane_order",
        "projection_method": "nearest_valid_track_piece_centerline",
        "sample_spacing_m": sample_spacing_m,
        "maximum_heading_difference_deg": maximum_heading_difference_deg,
        "samples_by_track": samples_by_track,
    }


def classify_lane_roles(point, ego_track_id, tracks, topology, heading_rad: float | None = None):
    track_by_id = {str(t.get("track_id")): t for t in tracks}
    role_by_id = {tid: "irrelevant" for tid in track_by_id}
    empty = {"track_id": None, "method": "not_found"}
    if not ego_track_id or str(ego_track_id) not in track_by_id:
        return {"ego_track_id": None, "left": empty, "right": empty, "roles": [{"track_id": tid, "role": "irrelevant"} for tid in sorted(track_by_id)], "method": "no_ego_track_for_static_order"}
    ego_id = str(ego_track_id)
    samples = (topology.get("samples_by_track") or {}).get(ego_id, [])
    if not samples:
        return {"ego_track_id": ego_id, "left": empty, "right": empty, "roles": [{"track_id": tid, "role": "ego" if tid == ego_id else "irrelevant"} for tid in sorted(track_by_id)], "method": "static_order_unavailable"}
    def row_key(row):
        distance = math.hypot(float(row["point"][0]) - point[0], float(row["point"][1]) - point[1])
        heading_difference = 0.0 if heading_rad is None else abs(math.degrees(wrap_angle(float(row["heading_rad"]) - heading_rad)))
        incompatible = heading_rad is not None and heading_difference > float(topology.get("maximum_heading_difference_deg", 20.0))
        return (incompatible, distance, heading_difference, int(row.get("reference_piece_index") or 0))
    row = min(samples, key=row_key)
    role_by_id[ego_id] = "ego"
    selected = {}
    for side, role in (("left", "left_adjacent"), ("right", "right_adjacent")):
        candidate = row.get(side)
        if candidate and str(candidate.get("track_id")) in role_by_id:
            tid = str(candidate["track_id"])
            role_by_id[tid] = role
            selected[side] = {**candidate, "method": "static_cross_section_piece_local_immediate_neighbor", "reference_station_m": row["station_m"], "confidence": "high"}
        else:
            selected[side] = {"track_id": None, "method": "not_found", "reference_station_m": row["station_m"]}
    roles = []
    for tid in sorted(track_by_id):
        proj = _track_local_projection(point, track_by_id[tid])
        roles.append({
            "track_id": tid,
            "role": role_by_id[tid],
            "member_lane_ids": list(track_by_id[tid].get("member_lane_ids", [])),
            "source": track_by_id[tid].get("source", "canonical_continuous_track"),
            "distance_to_ego_m": None if proj is None else round(float(proj["distance_m"]), 3),
            "nearest_piece_kind": None if proj is None else proj.get("projection_piece_kind"),
        })
    return {
        "ego_track_id": ego_id,
        "left": selected["left"],
        "right": selected["right"],
        "roles": roles,
        "cross_section": row,
        "method": "static_cross_section_piece_local_lane_order",
    }


def build_constructed_lane_network(tracks, topology):
    return {
        "lane_count": len(tracks),
        "role_semantics": ["ego", "left_adjacent", "right_adjacent", "irrelevant"],
        "ordering_method": topology.get("method"),
        "projection_method": topology.get("projection_method"),
        "lanes": [{
            "track_id": str(t.get("track_id")),
            "member_lane_ids": list(t.get("member_lane_ids", [])),
            "source": t.get("source", "canonical_continuous_track"),
            "median_width_m": t.get("median_width_m"),
        } for t in tracks],
    }
