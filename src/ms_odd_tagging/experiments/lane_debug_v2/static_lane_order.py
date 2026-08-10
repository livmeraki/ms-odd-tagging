"""Static left-to-right ordering of constructed lane tracks.

The LD-derived lane network is static. For each track, sample its centerline once
and determine the immediate left/right constructed tracks at each station by a
road-aligned cross-section. Per-frame role assignment only looks up the nearest
precomputed sample; it does not rediscover adjacency or use pairwise station
intervals.
"""
from __future__ import annotations

import math
from typing import Any

from .lane_geometry import wrap_angle


def _dist(a, b) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _cum(line: list[list[float]]) -> list[float]:
    out = [0.0]
    for a, b in zip(line, line[1:]):
        out.append(out[-1] + _dist(a, b))
    return out


def _sample(line: list[list[float]], spacing_m: float) -> list[dict[str, Any]]:
    if len(line) < 2:
        return []
    cumulative = _cum(line)
    total = cumulative[-1]
    if total <= 1e-6:
        return []
    count = max(2, int(math.floor(total / max(spacing_m, 0.5))) + 1)
    out = []
    seg = 0
    for i in range(count):
        station = total if i == count - 1 else total * i / (count - 1)
        while seg + 2 < len(cumulative) and cumulative[seg + 1] < station:
            seg += 1
        a, b = line[seg], line[seg + 1]
        span = cumulative[seg + 1] - cumulative[seg]
        t = 0.0 if span <= 1e-9 else (station - cumulative[seg]) / span
        p = [float(a[0]) + t * (float(b[0]) - float(a[0])), float(a[1]) + t * (float(b[1]) - float(a[1]))]
        out.append({"station_m": station, "point": p, "heading_rad": math.atan2(float(b[1]) - float(a[1]), float(b[0]) - float(a[0]))})
    return out


def _project(point: tuple[float, float] | list[float], line: list[list[float]]) -> dict[str, Any] | None:
    if len(line) < 2:
        return None
    cumulative = _cum(line)
    best = None
    for i, (a, b) in enumerate(zip(line, line[1:])):
        ax, ay, bx, by = float(a[0]), float(a[1]), float(b[0]), float(b[1])
        dx, dy = bx - ax, by - ay
        den = dx * dx + dy * dy
        if den <= 1e-12:
            continue
        t = max(0.0, min(1.0, ((float(point[0]) - ax) * dx + (float(point[1]) - ay) * dy) / den))
        q = [ax + t * dx, ay + t * dy]
        item = {
            "distance_m": _dist(point, q),
            "station_m": cumulative[i] + t * math.sqrt(den),
            "point": q,
            "heading_rad": math.atan2(dy, dx),
        }
        if best is None or item["distance_m"] < best["distance_m"]:
            best = item
    return best


def build_static_lane_order(
    tracks: list[dict[str, Any]],
    *,
    sample_spacing_m: float = 2.0,
    maximum_heading_difference_deg: float = 20.0,
    minimum_lateral_m: float = 1.5,
    maximum_lateral_m: float = 8.0,
    maximum_longitudinal_m: float = 8.0,
) -> dict[str, Any]:
    """Precompute immediate left/right neighbor at each track station."""
    by_id = {str(t.get("track_id")): t for t in tracks}
    samples_by_track: dict[str, list[dict[str, Any]]] = {}
    for track_id, track in by_id.items():
        rows = []
        for sample in _sample(track.get("centerline_lcs_m") or [], sample_spacing_m):
            p = sample["point"]
            h = sample["heading_rad"]
            c, s = math.cos(h), math.sin(h)
            candidates = []
            for other_id, other in by_id.items():
                if other_id == track_id:
                    continue
                proj = _project(p, other.get("centerline_lcs_m") or [])
                if proj is None:
                    continue
                diff = abs(math.degrees(wrap_angle(float(proj["heading_rad"]) - h)))
                if diff > maximum_heading_difference_deg:
                    continue
                dx, dy = proj["point"][0] - p[0], proj["point"][1] - p[1]
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
                })
            left_candidates = sorted((x for x in candidates if x["signed_lateral_m"] > 0), key=lambda x: (x["signed_lateral_m"], abs(x["longitudinal_m"]), x["track_id"]))
            right_candidates = sorted((x for x in candidates if x["signed_lateral_m"] < 0), key=lambda x: (abs(x["signed_lateral_m"]), abs(x["longitudinal_m"]), x["track_id"]))
            rows.append({
                "station_m": round(sample["station_m"], 3),
                "point": p,
                "heading_rad": h,
                "left": left_candidates[0] if left_candidates else None,
                "right": right_candidates[0] if right_candidates else None,
                "ordered_candidates": sorted(candidates, key=lambda x: -x["signed_lateral_m"]),
            })
        samples_by_track[track_id] = rows
    return {
        "method": "static_cross_section_lane_order",
        "sample_spacing_m": sample_spacing_m,
        "samples_by_track": samples_by_track,
    }


def classify_lane_roles(
    point: tuple[float, float],
    ego_track_id: str | None,
    tracks: list[dict[str, Any]],
    topology: dict[str, Any],
) -> dict[str, Any]:
    """Classify every static track using the nearest precomputed cross-section."""
    track_by_id = {str(t.get("track_id")): t for t in tracks}
    role_by_id = {tid: "irrelevant" for tid in track_by_id}
    empty = {"track_id": None, "method": "not_found"}
    if not ego_track_id or str(ego_track_id) not in track_by_id:
        return {"ego_track_id": None, "left": empty, "right": empty, "roles": [{"track_id": tid, "role": "irrelevant"} for tid in sorted(track_by_id)], "method": "no_ego_track_for_static_order"}
    ego_id = str(ego_track_id)
    projection = _project(point, track_by_id[ego_id].get("centerline_lcs_m") or [])
    samples = (topology.get("samples_by_track") or {}).get(ego_id, [])
    if projection is None or not samples:
        return {"ego_track_id": ego_id, "left": empty, "right": empty, "roles": [{"track_id": tid, "role": "ego" if tid == ego_id else "irrelevant"} for tid in sorted(track_by_id)], "method": "static_order_unavailable"}
    row = min(samples, key=lambda r: abs(float(r["station_m"]) - float(projection["station_m"])))
    role_by_id[ego_id] = "ego"
    selected = {}
    for side, role in (("left", "left_adjacent"), ("right", "right_adjacent")):
        candidate = row.get(side)
        if candidate and candidate.get("track_id") in role_by_id:
            role_by_id[str(candidate["track_id"])] = role
            selected[side] = {**candidate, "method": "static_cross_section_immediate_neighbor", "reference_station_m": row["station_m"], "confidence": "high"}
        else:
            selected[side] = {"track_id": None, "method": "not_found", "reference_station_m": row["station_m"]}
    roles = []
    for tid in sorted(track_by_id):
        proj = _project(point, track_by_id[tid].get("centerline_lcs_m") or [])
        roles.append({
            "track_id": tid,
            "role": role_by_id[tid],
            "member_lane_ids": list(track_by_id[tid].get("member_lane_ids", [])),
            "source": track_by_id[tid].get("source", "canonical_continuous_track"),
            "distance_to_ego_m": None if proj is None else round(proj["distance_m"], 3),
        })
    return {
        "ego_track_id": ego_id,
        "left": selected["left"],
        "right": selected["right"],
        "roles": roles,
        "cross_section": row,
        "method": "static_cross_section_lane_order",
    }


def build_constructed_lane_network(tracks: list[dict[str, Any]], topology: dict[str, Any]) -> dict[str, Any]:
    return {
        "lane_count": len(tracks),
        "role_semantics": ["ego", "left_adjacent", "right_adjacent", "irrelevant"],
        "ordering_method": topology.get("method"),
        "lanes": [{
            "track_id": str(t.get("track_id")),
            "member_lane_ids": list(t.get("member_lane_ids", [])),
            "source": t.get("source", "canonical_continuous_track"),
            "median_width_m": t.get("median_width_m"),
        } for t in tracks],
    }
