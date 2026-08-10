"""Static track-topology adjacency for lane-debug v2.

Adjacency is estimated once between continuous tracks from sustained geometric
overlap. Per-frame selection then activates the precomputed relation near the
ego station instead of rediscovering the closest lane from scratch.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from .lane_geometry import nearest_heading, point_segment_distance, wrap_angle


def _dist(a: list[float] | tuple[float, float], b: list[float] | tuple[float, float]) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _polyline_cumulative(points: list[list[float]]) -> list[float]:
    out = [0.0]
    for a, b in zip(points, points[1:]):
        out.append(out[-1] + _dist(a, b))
    return out


def _nearest_projection(point: tuple[float, float], line: list[list[float]]) -> tuple[float, float, list[float], float] | None:
    if len(line) < 2:
        return None
    cumulative = _polyline_cumulative(line)
    best = None
    for i, (a, b) in enumerate(zip(line, line[1:])):
        ax, ay, bx, by = float(a[0]), float(a[1]), float(b[0]), float(b[1])
        dx, dy = bx - ax, by - ay
        denom = dx * dx + dy * dy
        if denom <= 1e-12:
            continue
        t = max(0.0, min(1.0, ((point[0] - ax) * dx + (point[1] - ay) * dy) / denom))
        q = [ax + t * dx, ay + t * dy]
        d = _dist(point, q)
        s = cumulative[i] + t * math.sqrt(denom)
        heading = math.atan2(dy, dx)
        candidate = (d, s, q, heading)
        if best is None or candidate[0] < best[0]:
            best = candidate
    return best


def _resample_with_station(line: list[list[float]], spacing_m: float) -> list[tuple[float, list[float], float]]:
    if len(line) < 2:
        return []
    cumulative = _polyline_cumulative(line)
    total = cumulative[-1]
    if total <= 1e-6:
        return []
    count = max(2, int(math.floor(total / max(spacing_m, 0.5))) + 1)
    samples = []
    seg = 0
    for i in range(count):
        target = total if i == count - 1 else total * i / (count - 1)
        while seg + 2 < len(cumulative) and cumulative[seg + 1] < target:
            seg += 1
        a, b = line[seg], line[seg + 1]
        span = cumulative[seg + 1] - cumulative[seg]
        t = 0.0 if span <= 1e-9 else (target - cumulative[seg]) / span
        p = [float(a[0]) + t * (float(b[0]) - float(a[0])), float(a[1]) + t * (float(b[1]) - float(a[1]))]
        heading = math.atan2(float(b[1]) - float(a[1]), float(b[0]) - float(a[0]))
        samples.append((target, p, heading))
    return samples


def _shared_boundary_evidence(track_a: dict[str, Any], track_b: dict[str, Any], lane_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    a_left, a_right, b_left, b_right = set(), set(), set(), set()
    for lane_id in track_a.get("member_lane_ids", []):
        lane = lane_by_id.get(str(lane_id)) or {}
        if lane.get("left_edge_id") is not None:
            a_left.add(str(lane["left_edge_id"]))
        if lane.get("right_edge_id") is not None:
            a_right.add(str(lane["right_edge_id"]))
    for lane_id in track_b.get("member_lane_ids", []):
        lane = lane_by_id.get(str(lane_id)) or {}
        if lane.get("left_edge_id") is not None:
            b_left.add(str(lane["left_edge_id"]))
        if lane.get("right_edge_id") is not None:
            b_right.add(str(lane["right_edge_id"]))
    return {
        "a_left_b_right": sorted(a_left & b_right),
        "a_right_b_left": sorted(a_right & b_left),
    }


def build_track_adjacency_graph(
    tracks: list[dict[str, Any]],
    lane_geometry: list[dict[str, Any]],
    *,
    sample_spacing_m: float = 2.0,
    maximum_heading_difference_deg: float = 20.0,
    minimum_lateral_m: float = 1.5,
    maximum_lateral_m: float = 8.0,
    minimum_overlap_m: float = 8.0,
    minimum_side_consistency: float = 0.8,
    maximum_lateral_std_m: float = 1.5,
) -> dict[str, Any]:
    """Build directed left/right relations between persistent tracks."""
    lane_by_id = {str(l.get("lane_id")): l for l in lane_geometry}
    relations: list[dict[str, Any]] = []
    by_ego: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: {"left": [], "right": []})

    for ego in tracks:
        ego_line = ego.get("centerline_lcs_m") or []
        samples = _resample_with_station(ego_line, sample_spacing_m)
        if not samples:
            continue
        for candidate in tracks:
            if candidate.get("track_id") == ego.get("track_id"):
                continue
            cand_line = candidate.get("centerline_lcs_m") or []
            if len(cand_line) < 2:
                continue
            accepted = []
            for ego_s, p, ego_heading in samples:
                proj = _nearest_projection((p[0], p[1]), cand_line)
                if proj is None:
                    continue
                d, cand_s, q, cand_heading = proj
                heading_diff = abs(math.degrees(wrap_angle(cand_heading - ego_heading)))
                nx, ny = -math.sin(ego_heading), math.cos(ego_heading)
                signed_lat = (q[0] - p[0]) * nx + (q[1] - p[1]) * ny
                if heading_diff <= maximum_heading_difference_deg and minimum_lateral_m <= abs(signed_lat) <= maximum_lateral_m:
                    accepted.append((ego_s, cand_s, signed_lat, heading_diff, d))
            if len(accepted) < 2:
                continue
            signs = [1 if x[2] > 0 else -1 for x in accepted]
            majority = 1 if sum(signs) >= 0 else -1
            consistent = [x for x in accepted if (1 if x[2] > 0 else -1) == majority]
            consistency = len(consistent) / len(accepted)
            if consistency < minimum_side_consistency or len(consistent) < 2:
                continue
            s_values = [x[0] for x in consistent]
            overlap_m = max(s_values) - min(s_values)
            if overlap_m < minimum_overlap_m:
                continue
            lateral = [abs(x[2]) for x in consistent]
            median_lat = sorted(lateral)[len(lateral) // 2]
            mean_lat = sum(lateral) / len(lateral)
            std_lat = math.sqrt(sum((x - mean_lat) ** 2 for x in lateral) / len(lateral))
            if std_lat > maximum_lateral_std_m:
                continue
            heading_values = sorted(x[3] for x in consistent)
            p90 = heading_values[min(len(heading_values) - 1, int(round(0.9 * (len(heading_values) - 1))))]
            side = "left" if majority > 0 else "right"
            shared = _shared_boundary_evidence(ego, candidate, lane_by_id)
            shared_count = len(shared["a_left_b_right"]) + len(shared["a_right_b_left"])
            score = median_lat + p90 * 0.08 + std_lat * 1.5 - min(shared_count, 3) * 0.5
            relation = {
                "ego_track_id": str(ego.get("track_id")),
                "adjacent_track_id": str(candidate.get("track_id")),
                "side": side,
                "ego_s_start_m": round(min(s_values), 3),
                "ego_s_end_m": round(max(s_values), 3),
                "overlap_m": round(overlap_m, 3),
                "sample_count": len(consistent),
                "side_consistency": round(consistency, 3),
                "median_lateral_m": round(median_lat, 3),
                "lateral_std_m": round(std_lat, 3),
                "heading_difference_deg_p90": round(p90, 2),
                "shared_boundary_evidence": shared,
                "score": round(score, 3),
                "confidence": "high" if shared_count > 0 and overlap_m >= 15.0 else "medium",
            }
            relations.append(relation)
            by_ego[relation["ego_track_id"]][side].append(relation)

    for sides in by_ego.values():
        for side in ("left", "right"):
            sides[side].sort(key=lambda r: (r["score"], -r["overlap_m"], r["adjacent_track_id"]))
    return {"relations": relations, "by_ego_track": dict(by_ego)}


def _relation_at_point(relation: dict[str, Any], ego_track: dict[str, Any], point: tuple[float, float], station_margin_m: float) -> dict[str, Any] | None:
    proj = _nearest_projection(point, ego_track.get("centerline_lcs_m") or [])
    if proj is None:
        return None
    ego_s = proj[1]
    if ego_s < float(relation["ego_s_start_m"]) - station_margin_m or ego_s > float(relation["ego_s_end_m"]) + station_margin_m:
        return None
    return {**relation, "ego_station_m": round(ego_s, 3)}


def select_topology_adjacency(
    ego_track_id: str | None,
    point: tuple[float, float],
    tracks: list[dict[str, Any]],
    graph: dict[str, Any],
    *,
    previous: dict[str, str | None] | None = None,
    pending: dict[str, dict[str, Any] | None] | None = None,
    hysteresis_enabled: bool = True,
    switch_score_margin: float = 0.75,
    switch_confirmation_frames: int = 3,
    station_margin_m: float = 4.0,
) -> tuple[dict[str, Any], dict[str, str | None], dict[str, dict[str, Any] | None]]:
    """Activate static adjacency relations and optionally apply temporal hysteresis."""
    previous = dict(previous or {"left": None, "right": None})
    pending = dict(pending or {"left": None, "right": None})
    output = {"left": {"track_id": None, "method": "not_found"}, "right": {"track_id": None, "method": "not_found"}, "candidates": []}
    ego = next((t for t in tracks if str(t.get("track_id")) == str(ego_track_id)), None)
    if ego is None:
        return output, previous, pending
    relations = (graph.get("by_ego_track") or {}).get(str(ego_track_id), {"left": [], "right": []})

    for side in ("left", "right"):
        active = []
        for relation in relations.get(side, []):
            local = _relation_at_point(relation, ego, point, station_margin_m)
            if local is not None:
                active.append(local)
                output["candidates"].append(local)
        active.sort(key=lambda r: (r["score"], -r["overlap_m"], r["adjacent_track_id"]))
        if not active:
            previous[side] = None
            pending[side] = None
            continue
        best = active[0]
        chosen = best
        method = "track_topology_adjacency"
        held = False
        prior_id = previous.get(side)
        prior = next((r for r in active if r["adjacent_track_id"] == prior_id), None)
        if hysteresis_enabled and prior is not None and best["adjacent_track_id"] != prior_id:
            improvement = float(prior["score"]) - float(best["score"])
            if improvement < switch_score_margin:
                chosen = prior
                method = "track_topology_hysteresis_hold"
                held = True
                pending[side] = None
            else:
                state = pending.get(side)
                if state and state.get("track_id") == best["adjacent_track_id"]:
                    state = {**state, "count": int(state.get("count", 0)) + 1}
                else:
                    state = {"track_id": best["adjacent_track_id"], "count": 1}
                pending[side] = state
                if int(state["count"]) < max(1, switch_confirmation_frames):
                    chosen = prior
                    method = "track_topology_hysteresis_pending"
                    held = True
                else:
                    pending[side] = None
        else:
            pending[side] = None
        previous[side] = chosen["adjacent_track_id"]
        output[side] = {
            **chosen,
            "track_id": chosen["adjacent_track_id"],
            "method": method,
            "held_from_previous_frame": held,
            "hysteresis_enabled": hysteresis_enabled,
        }
    return output, previous, pending
