"""Classify every constructed continuous lane track per frame.

The lane network is static for a recording. Frames only assign roles to those
preconstructed tracks: ego, left-adjacent, right-adjacent, or irrelevant.
Adjacency is taken from the static track topology graph and includes reciprocal
relations so a previous ego track can become the opposite adjacent lane after a
lane change instead of disappearing because one directed relation is missing.
"""
from __future__ import annotations

import math
from typing import Any


def _dist(a: list[float] | tuple[float, float], b: list[float] | tuple[float, float]) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _cumulative(line: list[list[float]]) -> list[float]:
    out = [0.0]
    for a, b in zip(line, line[1:]):
        out.append(out[-1] + _dist(a, b))
    return out


def _project(point: tuple[float, float], line: list[list[float]]) -> dict[str, Any] | None:
    if len(line) < 2:
        return None
    cumulative = _cumulative(line)
    best = None
    for i, (a, b) in enumerate(zip(line, line[1:])):
        ax, ay, bx, by = float(a[0]), float(a[1]), float(b[0]), float(b[1])
        dx, dy = bx - ax, by - ay
        denom = dx * dx + dy * dy
        if denom <= 1e-12:
            continue
        t = max(0.0, min(1.0, ((point[0] - ax) * dx + (point[1] - ay) * dy) / denom))
        q = [ax + t * dx, ay + t * dy]
        distance_m = _dist(point, q)
        station_m = cumulative[i] + t * math.sqrt(denom)
        candidate = {
            "distance_m": distance_m,
            "station_m": station_m,
            "point": q,
            "heading_rad": math.atan2(dy, dx),
        }
        if best is None or distance_m < best["distance_m"]:
            best = candidate
    return best


def build_constructed_lane_network(
    tracks: list[dict[str, Any]], graph: dict[str, Any]
) -> dict[str, Any]:
    """Return the complete static lane network, independent of frame role."""
    neighbors: dict[str, dict[str, set[str]]] = {
        str(t.get("track_id")): {"left": set(), "right": set()} for t in tracks
    }
    for relation in graph.get("relations", []):
        ego = str(relation.get("ego_track_id"))
        adjacent = str(relation.get("adjacent_track_id"))
        side = relation.get("side")
        if ego in neighbors and side in {"left", "right"}:
            neighbors[ego][side].add(adjacent)
        # Adjacency is reciprocal. If B is left of A, A is right of B.
        inverse = "right" if side == "left" else "left" if side == "right" else None
        if adjacent in neighbors and inverse:
            neighbors[adjacent][inverse].add(ego)
    lanes = []
    for track in tracks:
        track_id = str(track.get("track_id"))
        lanes.append({
            "track_id": track_id,
            "logical_lane_id": track.get("logical_lane_id"),
            "member_lane_ids": list(track.get("member_lane_ids", [])),
            "piece_count": track.get("piece_count"),
            "observed_segment_count": track.get("observed_segment_count"),
            "inferred_gap_count": track.get("inferred_gap_count"),
            "median_width_m": track.get("median_width_m"),
            "left_neighbor_track_ids": sorted(neighbors[track_id]["left"]),
            "right_neighbor_track_ids": sorted(neighbors[track_id]["right"]),
        })
    return {
        "lane_count": len(lanes),
        "lanes": lanes,
        "role_semantics": ["ego", "left_adjacent", "right_adjacent", "irrelevant"],
    }


def _active_direct_relations(
    ego_track_id: str,
    point: tuple[float, float],
    track_by_id: dict[str, dict[str, Any]],
    graph: dict[str, Any],
    station_margin_m: float,
) -> list[dict[str, Any]]:
    ego = track_by_id.get(ego_track_id)
    if not ego:
        return []
    projection = _project(point, ego.get("centerline_lcs_m") or [])
    if projection is None:
        return []
    station = projection["station_m"]
    out = []
    sides = (graph.get("by_ego_track") or {}).get(ego_track_id, {})
    for side in ("left", "right"):
        for relation in sides.get(side, []):
            start = float(relation.get("ego_s_start_m", -math.inf)) - station_margin_m
            end = float(relation.get("ego_s_end_m", math.inf)) + station_margin_m
            if start <= station <= end:
                out.append({
                    **relation,
                    "track_id": str(relation.get("adjacent_track_id")),
                    "side": side,
                    "method": "static_track_topology_direct",
                    "reference_station_m": round(station, 3),
                    "reciprocal": False,
                })
    return out


def _active_reciprocal_relations(
    ego_track_id: str,
    point: tuple[float, float],
    track_by_id: dict[str, dict[str, Any]],
    graph: dict[str, Any],
    station_margin_m: float,
) -> list[dict[str, Any]]:
    """Recover adjacency from the opposite directed relation.

    If A->B says B is left of A and ego later changes into B, project the ego
    point onto A and activate A as B's right neighbor over the same overlap.
    """
    out = []
    for relation in graph.get("relations", []):
        if str(relation.get("adjacent_track_id")) != ego_track_id:
            continue
        other_id = str(relation.get("ego_track_id"))
        other = track_by_id.get(other_id)
        if not other:
            continue
        projection = _project(point, other.get("centerline_lcs_m") or [])
        if projection is None:
            continue
        station = projection["station_m"]
        start = float(relation.get("ego_s_start_m", -math.inf)) - station_margin_m
        end = float(relation.get("ego_s_end_m", math.inf)) + station_margin_m
        if not (start <= station <= end):
            continue
        original_side = relation.get("side")
        side = "right" if original_side == "left" else "left"
        out.append({
            **relation,
            "track_id": other_id,
            "side": side,
            "method": "static_track_topology_reciprocal",
            "reference_station_m": round(station, 3),
            "reciprocal": True,
            # Direct relations win ties, but reciprocal evidence is still strong.
            "effective_score": round(float(relation.get("score", 999.0)) + 0.1, 3),
        })
    return out


def _choose_side(
    side: str,
    candidates: list[dict[str, Any]],
    previous_id: str | None,
    pending: dict[str, Any] | None,
    *,
    hysteresis_enabled: bool,
    switch_score_margin: float,
    switch_confirmation_frames: int,
) -> tuple[dict[str, Any], str | None, dict[str, Any] | None]:
    eligible = [c for c in candidates if c.get("side") == side]
    if not eligible:
        return {"track_id": None, "method": "not_found"}, None, None
    eligible.sort(key=lambda c: (
        float(c.get("effective_score", c.get("score", 999.0))),
        -float(c.get("overlap_m", 0.0)),
        str(c.get("track_id")),
    ))
    best = eligible[0]
    best_score = float(best.get("effective_score", best.get("score", 999.0)))
    prior = next((c for c in eligible if str(c.get("track_id")) == str(previous_id)), None)
    chosen = best
    held = False
    method = best.get("method", "static_track_topology")
    if hysteresis_enabled and prior and str(best.get("track_id")) != str(previous_id):
        prior_score = float(prior.get("effective_score", prior.get("score", 999.0)))
        improvement = prior_score - best_score
        if improvement < switch_score_margin:
            chosen = prior
            held = True
            pending = None
            method = "lane_role_hysteresis_hold"
        else:
            if pending and str(pending.get("track_id")) == str(best.get("track_id")):
                pending = {**pending, "count": int(pending.get("count", 0)) + 1}
            else:
                pending = {"track_id": str(best.get("track_id")), "count": 1}
            if int(pending["count"]) < max(1, switch_confirmation_frames):
                chosen = prior
                held = True
                method = "lane_role_hysteresis_pending"
            else:
                pending = None
    else:
        pending = None
    selected = {
        **chosen,
        "track_id": str(chosen.get("track_id")),
        "method": method,
        "held_from_previous_frame": held,
        "hysteresis_enabled": hysteresis_enabled,
    }
    return selected, selected["track_id"], pending


def classify_all_lane_roles(
    point: tuple[float, float],
    ego_track_id: str | None,
    tracks: list[dict[str, Any]],
    graph: dict[str, Any],
    *,
    previous_adjacency: dict[str, str | None] | None = None,
    pending_adjacency: dict[str, dict[str, Any] | None] | None = None,
    hysteresis_enabled: bool = True,
    switch_score_margin: float = 0.75,
    switch_confirmation_frames: int = 3,
    station_margin_m: float = 4.0,
) -> tuple[dict[str, Any], dict[str, str | None], dict[str, dict[str, Any] | None]]:
    """Assign ego/left/right/irrelevant roles to every static constructed track."""
    previous = dict(previous_adjacency or {"left": None, "right": None})
    pending = dict(pending_adjacency or {"left": None, "right": None})
    track_by_id = {str(t.get("track_id")): t for t in tracks}
    candidates: list[dict[str, Any]] = []
    if ego_track_id:
        candidates.extend(_active_direct_relations(str(ego_track_id), point, track_by_id, graph, station_margin_m))
        candidates.extend(_active_reciprocal_relations(str(ego_track_id), point, track_by_id, graph, station_margin_m))
    selected = {}
    for side in ("left", "right"):
        selected[side], previous[side], pending[side] = _choose_side(
            side,
            candidates,
            previous.get(side),
            pending.get(side),
            hysteresis_enabled=hysteresis_enabled,
            switch_score_margin=switch_score_margin,
            switch_confirmation_frames=switch_confirmation_frames,
        )
    role_by_track = {track_id: "irrelevant" for track_id in track_by_id}
    if ego_track_id and str(ego_track_id) in role_by_track:
        role_by_track[str(ego_track_id)] = "ego"
    for side, role in (("left", "left_adjacent"), ("right", "right_adjacent")):
        track_id = selected[side].get("track_id")
        if track_id and track_id != str(ego_track_id):
            role_by_track[str(track_id)] = role
    roles = []
    for track_id in sorted(track_by_id):
        projection = _project(point, track_by_id[track_id].get("centerline_lcs_m") or [])
        roles.append({
            "track_id": track_id,
            "role": role_by_track[track_id],
            "member_lane_ids": list(track_by_id[track_id].get("member_lane_ids", [])),
            "distance_to_ego_m": None if projection is None else round(projection["distance_m"], 3),
            "track_station_near_ego_m": None if projection is None else round(projection["station_m"], 3),
        })
    return {
        "ego_track_id": str(ego_track_id) if ego_track_id else None,
        "left": selected["left"],
        "right": selected["right"],
        "roles": roles,
        "active_adjacency_candidates": sorted(
            candidates,
            key=lambda c: (c.get("side", ""), float(c.get("effective_score", c.get("score", 999.0))), str(c.get("track_id"))),
        ),
        "method": "static_constructed_lane_network_roles",
    }, previous, pending
