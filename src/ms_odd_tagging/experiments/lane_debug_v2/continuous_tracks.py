"""Continuous lane-track reconstruction for lane-debug v2.

Raw/recovered LD lane polygons remain immutable observations. Accepted
continuations are promoted into persistent directed tracks with piece-level
provenance. Track assignment and adjacency operate on the merged centerline so
short physical lane fragments do not force ego/logical-lane ID churn.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from .lane_geometry import nearest_heading, point_in_polygon, polyline_distance, wrap_angle


def _finite(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _dist(a, b) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _trajectory_points(recording: dict[str, Any]) -> list[tuple[float, float]]:
    out = []
    for frame in recording.get("frames", []):
        p = ((frame.get("ego") or {}).get("position_lcs_m") or [])
        if len(p) >= 2 and _finite(p[0]) and _finite(p[1]):
            out.append((float(p[0]), float(p[1])))
    return out


def _trajectory_cost(points: list[tuple[float, float]], centerline: list[list[float]]) -> float:
    if not points or len(centerline) < 2:
        return 0.0
    # Route context is only a tie-breaker. Subsample to keep this cheap.
    sample = points[:: max(1, len(points) // 80)]
    distances = [polyline_distance(p, centerline) for p in sample]
    distances.sort()
    keep = distances[: max(1, len(distances) // 4)]
    return sum(keep) / len(keep)


def _piece_kind(lane: dict[str, Any]) -> str:
    if lane.get("geometry_recovered"):
        return "recovered_full_edge"
    return "observed_ld"


def _append_points(target: list[list[float]], pts: list[list[float]]) -> None:
    for p in pts:
        if len(p) < 2:
            continue
        q = [float(p[0]), float(p[1])]
        if not target or _dist(target[-1], q) > 1e-4:
            target.append(q)


def _corridor_polygon(centerline: list[list[float]], width_m: float) -> list[list[float]]:
    if len(centerline) < 2:
        return []
    half = max(1.0, min(4.0, width_m / 2.0))
    left, right = [], []
    for i, p in enumerate(centerline):
        if i + 1 < len(centerline):
            q = centerline[i + 1]
        else:
            q = centerline[i - 1]
            p, q = q, p
        heading = math.atan2(float(q[1]) - float(p[1]), float(q[0]) - float(p[0]))
        if i == len(centerline) - 1:
            p = centerline[i]
        nx, ny = -math.sin(heading), math.cos(heading)
        left.append([float(p[0]) + nx * half, float(p[1]) + ny * half])
        right.append([float(p[0]) - nx * half, float(p[1]) - ny * half])
    return left + list(reversed(right))


def _median_lane_width(lane: dict[str, Any]) -> float:
    left = lane.get("left_boundary_lcs_m") or []
    right = lane.get("right_boundary_lcs_m") or []
    if not left or not right:
        return 3.5
    n = min(len(left), len(right))
    widths = [_dist(left[round(i * (len(left)-1)/(n-1))], right[round(i * (len(right)-1)/(n-1))]) for i in range(n)] if n > 1 else []
    widths = [w for w in widths if 1.0 <= w <= 10.0]
    return sorted(widths)[len(widths)//2] if widths else 3.5


def build_continuous_tracks(
    lane_geometry: list[dict[str, Any]],
    recording: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, str], list[dict[str, Any]]]:
    """Promote accepted segment continuations into recursively merged tracks.

    Outgoing connections already passed the existing gap/lateral/heading/
    curvature/width gates. We add a bidirectional one-in/one-out consistency
    check. Competing incoming connections are resolved by connection score,
    then ego-trajectory proximity as a contextual tie-breaker.
    """
    lanes = {str(l["lane_id"]): l for l in lane_geometry if l.get("assignment_valid")}
    trajectory = _trajectory_points(recording)
    proposals: list[dict[str, Any]] = []
    for source_id, lane in lanes.items():
        for cont in lane.get("curvature_continuations") or []:
            destination_id = cont.get("destination_lane_id")
            accepted = cont.get("accepted_candidate")
            if not destination_id or destination_id not in lanes or not accepted:
                continue
            if accepted.get("rejection_reasons"):
                continue
            proposals.append({
                "source": source_id,
                "destination": str(destination_id),
                "score": float(accepted.get("score", math.inf)),
                "gap_m": accepted.get("gap_m"),
                "projected": cont.get("projected_centerline_lcs_m") or [],
                "gap_polygon": cont.get("inferred_gap_polygon_lcs_m") or [],
                "evidence": accepted,
            })

    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in proposals:
        outgoing[p["source"]].append(p)
        incoming[p["destination"]].append(p)

    best_out = {src: min(items, key=lambda p: (p["score"], p["destination"])) for src, items in outgoing.items()}
    best_in: dict[str, dict[str, Any]] = {}
    for dst, items in incoming.items():
        best_in[dst] = min(
            items,
            key=lambda p: (
                p["score"],
                _trajectory_cost(trajectory, lanes[p["source"]].get("centerline_lcs_m") or []),
                p["source"],
            ),
        )

    accepted_edges: dict[str, dict[str, Any]] = {}
    rejected_edges: list[dict[str, Any]] = []
    for src, proposal in best_out.items():
        if best_in.get(proposal["destination"]) is proposal:
            accepted_edges[src] = proposal
        else:
            rejected_edges.append({**proposal, "rejection_reason": "bidirectional_incoming_conflict"})

    predecessors = {p["destination"]: src for src, p in accepted_edges.items()}
    visited: set[str] = set()
    tracks: list[dict[str, Any]] = []
    member_to_track: dict[str, str] = {}

    starts = [lane_id for lane_id in lanes if lane_id not in predecessors]
    starts += [lane_id for lane_id in lanes if lane_id not in starts]
    for start in starts:
        if start in visited:
            continue
        members, pieces, merged = [], [], []
        widths = []
        current = start
        seen_local: set[str] = set()
        while current in lanes and current not in seen_local and current not in visited:
            seen_local.add(current)
            visited.add(current)
            lane = lanes[current]
            members.append(current)
            widths.append(_median_lane_width(lane))
            center = lane.get("centerline_lcs_m") or []
            pieces.append({
                "kind": _piece_kind(lane),
                "lane_id": current,
                "centerline_lcs_m": center,
                "polygon_lcs_m": lane.get("polygon_lcs_m") or [],
                "recovery_method": lane.get("recovery_method"),
            })
            _append_points(merged, center)
            edge = accepted_edges.get(current)
            if not edge:
                break
            gap = edge.get("projected") or []
            if gap:
                pieces.append({
                    "kind": "inferred_gap",
                    "source_lane_id": current,
                    "destination_lane_id": edge["destination"],
                    "centerline_lcs_m": gap,
                    "polygon_lcs_m": edge.get("gap_polygon") or [],
                    "connection_evidence": edge.get("evidence"),
                })
                _append_points(merged, gap)
            current = edge["destination"]

        if not members:
            continue
        track_id = f"physical_track_{len(tracks)+1:04d}"
        width = sorted(widths)[len(widths)//2] if widths else 3.5
        polygon = _corridor_polygon(merged, width)
        track = {
            "track_id": track_id,
            "logical_lane_id": track_id,
            "member_lane_ids": members,
            "centerline_lcs_m": merged,
            "polygon_lcs_m": polygon,
            "median_width_m": round(width, 3),
            "pieces": pieces,
            "piece_count": len(pieces),
            "observed_segment_count": len(members),
            "inferred_gap_count": sum(1 for p in pieces if p["kind"] == "inferred_gap"),
        }
        tracks.append(track)
        for lane_id in members:
            member_to_track[lane_id] = track_id

    edge_debug = [
        {**p, "accepted": accepted_edges.get(p["source"]) is p}
        for p in proposals
    ] + rejected_edges
    return tracks, member_to_track, edge_debug


def assign_point_to_track(
    point: tuple[float, float],
    heading: float | None,
    tracks: list[dict[str, Any]],
    *,
    previous_track_id: str | None = None,
    maximum_heading_difference_deg: float = 60.0,
    outside_tolerance_m: float = 1.0,
) -> dict[str, Any]:
    candidates = []
    for track in tracks:
        center = track.get("centerline_lcs_m") or []
        polygon = track.get("polygon_lcs_m") or []
        if len(center) < 2:
            continue
        lane_heading = nearest_heading(point, center)
        diff = 0.0 if heading is None or lane_heading is None else abs(math.degrees(wrap_angle(heading-lane_heading)))
        if diff > maximum_heading_difference_deg:
            continue
        inside = bool(polygon) and point_in_polygon(point, polygon)
        center_distance = polyline_distance(point, center)
        allowed = float(track.get("median_width_m", 3.5))/2.0 + outside_tolerance_m
        if not inside and center_distance > allowed:
            continue
        score = center_distance + diff*0.04
        if track["track_id"] == previous_track_id:
            score -= 0.9
        candidates.append((score, track, inside, center_distance, diff))
    candidates.sort(key=lambda x: (x[0], x[1]["track_id"]))
    if not candidates:
        return {"track_id": None, "logical_lane_id": None, "method": "no_valid_continuous_track", "confidence": "unknown", "candidates": []}
    best = candidates[0]
    margin = candidates[1][0]-best[0] if len(candidates)>1 else None
    confidence = "high" if best[2] and (margin is None or margin >= 1.0) else "medium" if best[2] else "low"
    return {
        "track_id": best[1]["track_id"],
        "logical_lane_id": best[1]["logical_lane_id"],
        "member_lane_ids": best[1]["member_lane_ids"],
        "method": "continuous_track_polygon_and_heading",
        "confidence": confidence,
        "inside_polygon": best[2],
        "center_distance_m": round(best[3],3),
        "heading_difference_deg": round(best[4],2),
        "runner_up_score_margin": None if margin is None else round(margin,3),
        "candidates": [
            {"track_id": x[1]["track_id"], "score": round(x[0],3), "center_distance_m": round(x[3],3), "heading_difference_deg": round(x[4],2)}
            for x in candidates[:5]
        ],
    }


def adjacent_tracks(
    ego_track_id: str | None,
    point: tuple[float, float],
    tracks: list[dict[str, Any]],
    *,
    maximum_heading_difference_deg: float = 20.0,
    minimum_lateral_m: float = 1.5,
    maximum_lateral_m: float = 8.0,
    local_window_m: float = 20.0,
) -> dict[str, Any]:
    output = {"left": {"track_id": None, "method": "not_found"}, "right": {"track_id": None, "method": "not_found"}, "candidates": []}
    ego = next((t for t in tracks if t["track_id"] == ego_track_id), None)
    if ego is None:
        return output
    ego_heading = nearest_heading(point, ego.get("centerline_lcs_m") or [])
    if ego_heading is None:
        return output
    c, s = math.cos(ego_heading), math.sin(ego_heading)
    records = []
    for track in tracks:
        if track["track_id"] == ego_track_id or len(track.get("centerline_lcs_m") or []) < 2:
            continue
        projected = []
        for p in track["centerline_lcs_m"]:
            dx, dy = float(p[0])-point[0], float(p[1])-point[1]
            lon = c*dx+s*dy
            lat = -s*dx+c*dy
            if abs(lon) <= local_window_m:
                projected.append((lon, lat, p))
        if not projected:
            continue
        nearest = min(projected, key=lambda x: abs(x[1])+0.1*abs(x[0]))
        lon, lat, _ = nearest
        candidate_heading = nearest_heading(point, track["centerline_lcs_m"])
        diff = math.inf if candidate_heading is None else abs(math.degrees(wrap_angle(candidate_heading-ego_heading)))
        side = "left" if lat > 0 else "right"
        reasons = []
        if diff > maximum_heading_difference_deg:
            reasons.append("heading_difference")
        if not (minimum_lateral_m <= abs(lat) <= maximum_lateral_m):
            reasons.append("lateral_offset")
        # Require the candidate to occupy more than a single isolated local point.
        local_count = len(projected)
        if local_count < 2:
            reasons.append("insufficient_local_longitudinal_overlap")
        record = {
            "track_id": track["track_id"], "side": side,
            "lateral_offset_m": round(lat,3), "longitudinal_offset_m": round(lon,3),
            "heading_difference_deg": None if not math.isfinite(diff) else round(diff,2),
            "local_overlap_point_count": local_count,
            "eligible": not reasons, "rejection_reasons": reasons,
        }
        records.append(record)
    for side in ("left", "right"):
        eligible = [r for r in records if r["side"] == side and r["eligible"]]
        if eligible:
            chosen = min(eligible, key=lambda r: (abs(r["lateral_offset_m"]), abs(r["longitudinal_offset_m"]), r["track_id"]))
            output[side] = {**chosen, "method": "continuous_track_local_overlap", "confidence": "medium"}
    output["candidates"] = sorted(records, key=lambda r: (r["side"], abs(r["lateral_offset_m"]), r["track_id"]))
    return output
