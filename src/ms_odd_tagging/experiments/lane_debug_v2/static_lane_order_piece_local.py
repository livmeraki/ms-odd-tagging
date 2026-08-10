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


def _track_local_projection(point, track: dict[str, Any]) -> dict[str, Any] | None:
    best = None
    for index, piece in enumerate(track.get("pieces") or []):
        kind = str(piece.get("kind"))
        if kind not in _LOCAL_PIECE_KINDS:
            continue
        proj = _project(point, piece.get("centerline_lcs_m") or [])
        if proj is None:
            continue
        item = {**proj, "projection_piece_kind": kind, "projection_piece_index": index}
        if best is None or float(item["distance_m"]) < float(best["distance_m"]):
            best = item
    if best is not None:
        return best
    proj = _project(point, track.get("centerline_lcs_m") or [])
    if proj is None:
        return None
    return {**proj, "projection_piece_kind": "track_centerline_fallback", "projection_piece_index": None}


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
        for sample in _sample(track.get("centerline_lcs_m") or [], sample_spacing_m):
            p, h = sample["point"], float(sample["heading_rad"])
            c, s = math.cos(h), math.sin(h)
            candidates = []
            for other_id, other in by_id.items():
                if other_id == track_id:
                    continue
                proj = _track_local_projection(p, other)
                if proj is None:
                    continue
                diff = abs(math.degrees(wrap_angle(float(proj["heading_rad"]) - h)))
                if diff > maximum_heading_difference_deg:
                    continue
                dx, dy = float(proj["point"][0]) - p[0], float(proj["point"][1]) - p[1]
                lon = c * dx + s * dy
                lat = -s * dx + c * dy
                if abs(lon) > maximum_longitudinal_m or not (minimum_lateral_m <= abs(lat) <= maximum_lateral_m):
                    continue
                candidates.append({
                    "track_id": other_id,
                    "signed_lateral_m": lat,
                    "longitudinal_m": lon,
                    "heading_difference_deg": diff,
                    "distance_m": proj["distance_m"],
                    "projection_piece_kind": proj.get("projection_piece_kind"),
                    "projection_piece_index": proj.get("projection_piece_index"),
                })
            left = sorted((x for x in candidates if x["signed_lateral_m"] > 0), key=lambda x: (x["signed_lateral_m"], abs(x["longitudinal_m"]), x["track_id"]))
            right = sorted((x for x in candidates if x["signed_lateral_m"] < 0), key=lambda x: (abs(x["signed_lateral_m"]), abs(x["longitudinal_m"]), x["track_id"]))
            rows.append({
                "station_m": round(float(sample["station_m"]), 3),
                "point": p,
                "heading_rad": h,
                "left": left[0] if left else None,
                "right": right[0] if right else None,
                "ordered_candidates": sorted(candidates, key=lambda x: -x["signed_lateral_m"]),
            })
        samples_by_track[track_id] = rows
    return {
        "method": "static_cross_section_piece_local_lane_order",
        "projection_method": "nearest_valid_track_piece_centerline",
        "sample_spacing_m": sample_spacing_m,
        "samples_by_track": samples_by_track,
    }


def classify_lane_roles(point, ego_track_id, tracks, topology):
    track_by_id = {str(t.get("track_id")): t for t in tracks}
    role_by_id = {tid: "irrelevant" for tid in track_by_id}
    empty = {"track_id": None, "method": "not_found"}
    if not ego_track_id or str(ego_track_id) not in track_by_id:
        return {"ego_track_id": None, "left": empty, "right": empty, "roles": [{"track_id": tid, "role": "irrelevant"} for tid in sorted(track_by_id)], "method": "no_ego_track_for_static_order"}
    ego_id = str(ego_track_id)
    # Reference stations were sampled on the full ego track, so use that same
    # coordinate here. Candidate geometry is piece-local.
    projection = _project(point, track_by_id[ego_id].get("centerline_lcs_m") or [])
    samples = (topology.get("samples_by_track") or {}).get(ego_id, [])
    if projection is None or not samples:
        return {"ego_track_id": ego_id, "left": empty, "right": empty, "roles": [{"track_id": tid, "role": "ego" if tid == ego_id else "irrelevant"} for tid in sorted(track_by_id)], "method": "static_order_unavailable"}
    row = min(samples, key=lambda r: abs(float(r["station_m"]) - float(projection["station_m"])))
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
