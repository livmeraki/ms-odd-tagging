"""Orientation-aware stitching for fragmented canonical lane tracks.

Canonical LD fragments are not guaranteed to use a consistent point order.  This
module therefore treats each preliminary track as an undirected physical corridor
while deciding continuity.  Every start/end endpoint combination is evaluated;
accepted endpoint links are then traversed to produce consistently oriented final
tracks.  Raw LD is not used here and no standalone lane is invented.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


def _dist(a, b) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def _heading(a, b) -> float:
    return math.atan2(float(b[1]) - float(a[1]), float(b[0]) - float(a[0]))


def _angle_diff_deg(a: float, b: float) -> float:
    return abs(math.degrees(_wrap(a - b)))


def _endpoint_point(line: list[list[float]], side: str) -> list[float]:
    return line[0] if side == "start" else line[-1]


def _outward_heading(line: list[list[float]], side: str) -> float | None:
    """Heading pointing out of the track through the selected endpoint."""
    if len(line) < 2:
        return None
    if side == "end":
        for i in range(len(line) - 1, 0, -1):
            if _dist(line[i - 1], line[i]) > 1e-4:
                return _heading(line[i - 1], line[i])
    else:
        for i in range(1, len(line)):
            if _dist(line[i - 1], line[i]) > 1e-4:
                return _heading(line[i], line[i - 1])
    return None


def _oriented_line(line: list[list[float]], entry_side: str) -> list[list[float]]:
    """Orient a track so entry_side becomes the first endpoint."""
    pts = [[float(p[0]), float(p[1])] for p in line if len(p) >= 2]
    return pts if entry_side == "start" else list(reversed(pts))


def _curvature_proxy_oriented(line: list[list[float]], entry_side: str, at_exit: bool) -> float:
    pts = _oriented_line(line, entry_side)
    if len(pts) < 3:
        return 0.0
    sample = pts[-4:] if at_exit else pts[:4]
    headings, lengths = [], []
    for a, b in zip(sample, sample[1:]):
        d = _dist(a, b)
        if d <= 1e-4:
            continue
        headings.append(_heading(a, b))
        lengths.append(d)
    if len(headings) < 2 or not lengths:
        return 0.0
    return sum(_wrap(b - a) for a, b in zip(headings, headings[1:])) / max(sum(lengths), 1e-6)


def _terminal_lane(track: dict[str, Any], lane_by_id: dict[str, dict[str, Any]], endpoint: list[float]):
    best = None
    best_d = math.inf
    for lane_id in track.get("member_lane_ids", []) or []:
        lane = lane_by_id.get(str(lane_id))
        if not lane:
            continue
        center = lane.get("centerline_lcs_m") or []
        if not center:
            continue
        d = min(_dist(endpoint, center[0]), _dist(endpoint, center[-1]))
        if d < best_d:
            best_d = d
            best = lane
    return best


def _boundary_endpoint(boundary: list[list[float]], endpoint: list[float]):
    if not boundary:
        return None
    return min((boundary[0], boundary[-1]), key=lambda p: _dist(p, endpoint))


def _boundary_pair(
    track_a: dict[str, Any],
    side_a: str,
    track_b: dict[str, Any],
    side_b: str,
    lane_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    line_a = track_a.get("centerline_lcs_m") or []
    line_b = track_b.get("centerline_lcs_m") or []
    if not line_a or not line_b:
        return {}
    pa = _endpoint_point(line_a, side_a)
    pb = _endpoint_point(line_b, side_b)
    lane_a = _terminal_lane(track_a, lane_by_id, pa)
    lane_b = _terminal_lane(track_b, lane_by_id, pb)
    if not lane_a or not lane_b:
        return {}

    a_left = _boundary_endpoint(lane_a.get("left_boundary_lcs_m") or [], pa)
    a_right = _boundary_endpoint(lane_a.get("right_boundary_lcs_m") or [], pa)
    b_left = _boundary_endpoint(lane_b.get("left_boundary_lcs_m") or [], pb)
    b_right = _boundary_endpoint(lane_b.get("right_boundary_lcs_m") or [], pb)
    if any(x is None for x in (a_left, a_right, b_left, b_right)):
        return {}

    same = _dist(a_left, b_left) + _dist(a_right, b_right)
    swapped = _dist(a_left, b_right) + _dist(a_right, b_left)
    if swapped < same:
        b1, b2, swapped_flag = b_right, b_left, True
    else:
        b1, b2, swapped_flag = b_left, b_right, False
    return {
        "a1": [float(a_left[0]), float(a_left[1])],
        "a2": [float(a_right[0]), float(a_right[1])],
        "b1": [float(b1[0]), float(b1[1])],
        "b2": [float(b2[0]), float(b2[1])],
        "side_mapping_swapped": swapped_flag,
    }


def _append_points(target: list[list[float]], points: list[list[float]]) -> None:
    for p in points:
        if len(p) < 2:
            continue
        q = [float(p[0]), float(p[1])]
        if not target or _dist(target[-1], q) > 1e-4:
            target.append(q)


def _evaluate_endpoint_pair(
    a: dict[str, Any],
    side_a: str,
    b: dict[str, Any],
    side_b: str,
    lane_by_id: dict[str, dict[str, Any]],
    *,
    maximum_endpoint_gap_m: float,
    maximum_heading_difference_deg: float,
    maximum_lateral_error_m: float,
    maximum_width_difference_m: float,
    maximum_boundary_endpoint_gap_m: float,
    maximum_curvature_difference_per_m: float,
) -> dict[str, Any] | None:
    line_a = a.get("centerline_lcs_m") or []
    line_b = b.get("centerline_lcs_m") or []
    if len(line_a) < 2 or len(line_b) < 2:
        return None
    pa = _endpoint_point(line_a, side_a)
    pb = _endpoint_point(line_b, side_b)
    gap = _dist(pa, pb)
    if gap <= 1e-4 or gap > maximum_endpoint_gap_m:
        return None

    out_a = _outward_heading(line_a, side_a)
    out_b = _outward_heading(line_b, side_b)
    if out_a is None or out_b is None:
        return None
    gap_heading = _heading(pa, pb)
    a_to_gap = _angle_diff_deg(out_a, gap_heading)
    b_to_gap = _angle_diff_deg(out_b, _wrap(gap_heading + math.pi))
    tangent_opposition = abs(180.0 - _angle_diff_deg(out_a, out_b))

    dx, dy = float(pb[0]) - float(pa[0]), float(pb[1]) - float(pa[1])
    forward = math.cos(out_a) * dx + math.sin(out_a) * dy
    lateral = abs(-math.sin(out_a) * dx + math.cos(out_a) * dy)
    width_diff = abs(float(a.get("median_width_m", 3.5)) - float(b.get("median_width_m", 3.5)))

    # Orient A so side_a is its exit, B so side_b is its entry.
    entry_a = "start" if side_a == "end" else "end"
    entry_b = side_b
    curvature_diff = abs(
        _curvature_proxy_oriented(line_a, entry_a, True)
        - _curvature_proxy_oriented(line_b, entry_b, False)
    )

    boundary = _boundary_pair(a, side_a, b, side_b, lane_by_id)
    boundary_lateral_limit = min(float(maximum_lateral_error_m), float(maximum_boundary_endpoint_gap_m))
    boundary_forward_diff_limit = max(2.0, float(maximum_boundary_endpoint_gap_m))
    boundary_records = []
    if boundary:
        for p, q in ((boundary["a1"], boundary["b1"]), (boundary["a2"], boundary["b2"])):
            bdx, bdy = q[0] - p[0], q[1] - p[1]
            bf = math.cos(out_a) * bdx + math.sin(out_a) * bdy
            bl = abs(-math.sin(out_a) * bdx + math.cos(out_a) * bdy)
            boundary_records.append({
                "endpoint_gap_m": _dist(p, q),
                "forward_m": bf,
                "lateral_error_m": bl,
                "forward_gap_difference_m": abs(bf - forward),
            })

    reasons = []
    if forward <= 0.0:
        reasons.append("destination_not_forward_from_endpoint")
    if a_to_gap > maximum_heading_difference_deg:
        reasons.append("source_endpoint_heading_difference")
    if b_to_gap > maximum_heading_difference_deg:
        reasons.append("destination_endpoint_heading_difference")
    if tangent_opposition > maximum_heading_difference_deg:
        reasons.append("endpoint_tangents_not_opposed")
    if lateral > maximum_lateral_error_m:
        reasons.append("centerline_lateral_error")
    if width_diff > maximum_width_difference_m:
        reasons.append("width_difference")
    if curvature_diff > maximum_curvature_difference_per_m:
        reasons.append("curvature_difference")
    if len(boundary_records) != 2:
        reasons.append("missing_boundary_endpoint_evidence")
    else:
        if any(x["forward_m"] <= 0.0 for x in boundary_records):
            reasons.append("boundary_not_forward")
        if any(x["lateral_error_m"] > boundary_lateral_limit for x in boundary_records):
            reasons.append("boundary_lateral_error")
        if any(x["forward_gap_difference_m"] > boundary_forward_diff_limit for x in boundary_records):
            reasons.append("boundary_forward_gap_inconsistent")

    boundary_lateral_mean = (
        sum(x["lateral_error_m"] for x in boundary_records) / len(boundary_records)
        if boundary_records else boundary_lateral_limit
    )
    boundary_forward_mean = (
        sum(x["forward_gap_difference_m"] for x in boundary_records) / len(boundary_records)
        if boundary_records else boundary_forward_diff_limit
    )
    score = (
        gap + lateral * 4.0 + (a_to_gap + b_to_gap + tangent_opposition) * 0.05
        + width_diff + curvature_diff * 15.0
        + boundary_lateral_mean * 3.0 + boundary_forward_mean * 0.5
    )

    polygon = []
    if boundary:
        polygon = [boundary["a1"], boundary["b1"], boundary["b2"], boundary["a2"]]

    return {
        "track_a_id": str(a.get("track_id")),
        "track_b_id": str(b.get("track_id")),
        "endpoint_a": side_a,
        "endpoint_b": side_b,
        "endpoint_gap_m": round(gap, 3),
        "forward_projection_m": round(forward, 3),
        "centerline_lateral_error_m": round(lateral, 3),
        "source_to_gap_heading_difference_deg": round(a_to_gap, 3),
        "destination_to_gap_heading_difference_deg": round(b_to_gap, 3),
        "endpoint_tangent_opposition_error_deg": round(tangent_opposition, 3),
        "width_difference_m": round(width_diff, 3),
        "curvature_difference_per_m": round(curvature_diff, 5),
        "boundary_side_mapping_swapped": None if not boundary else boundary["side_mapping_swapped"],
        "boundary_1": None if len(boundary_records) < 1 else {k: round(v, 3) for k, v in boundary_records[0].items()},
        "boundary_2": None if len(boundary_records) < 2 else {k: round(v, 3) for k, v in boundary_records[1].items()},
        "stitch_centerline_lcs_m": [[float(pa[0]), float(pa[1])], [float(pb[0]), float(pb[1])]],
        "stitch_polygon_lcs_m": polygon,
        "score": round(score, 4),
        "rejection_reasons": reasons,
    }


def _other_side(side: str) -> str:
    return "end" if side == "start" else "start"


def stitch_canonical_tracks(
    tracks: list[dict[str, Any]],
    lane_geometry: list[dict[str, Any]],
    *,
    maximum_endpoint_gap_m: float = 8.0,
    maximum_heading_difference_deg: float = 12.0,
    maximum_lateral_error_m: float = 1.0,
    maximum_width_difference_m: float = 0.8,
    maximum_boundary_endpoint_gap_m: float = 3.0,
    maximum_curvature_difference_per_m: float = 0.08,
) -> tuple[list[dict[str, Any]], dict[str, str], list[dict[str, Any]]]:
    lane_by_id = {str(l.get("lane_id")): l for l in lane_geometry}
    by_id = {str(t.get("track_id")): t for t in tracks}

    # Evaluate every physical endpoint combination once per unordered track pair.
    candidates: list[dict[str, Any]] = []
    for i, a in enumerate(tracks):
        for b in tracks[i + 1:]:
            for side_a in ("start", "end"):
                for side_b in ("start", "end"):
                    rec = _evaluate_endpoint_pair(
                        a, side_a, b, side_b, lane_by_id,
                        maximum_endpoint_gap_m=maximum_endpoint_gap_m,
                        maximum_heading_difference_deg=maximum_heading_difference_deg,
                        maximum_lateral_error_m=maximum_lateral_error_m,
                        maximum_width_difference_m=maximum_width_difference_m,
                        maximum_boundary_endpoint_gap_m=maximum_boundary_endpoint_gap_m,
                        maximum_curvature_difference_per_m=maximum_curvature_difference_per_m,
                    )
                    if rec is not None:
                        candidates.append(rec)

    eligible = sorted(
        (c for c in candidates if not c["rejection_reasons"]),
        key=lambda c: (c["score"], c["track_a_id"], c["track_b_id"], c["endpoint_a"], c["endpoint_b"]),
    )

    # Greedy endpoint matching: each physical endpoint can participate in at most
    # one stitch.  Union-find prevents accidental closed loops.
    parent = {tid: tid for tid in by_id}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    used_endpoints: set[tuple[str, str]] = set()
    accepted: list[dict[str, Any]] = []
    for c in eligible:
        ea = (c["track_a_id"], c["endpoint_a"])
        eb = (c["track_b_id"], c["endpoint_b"])
        if ea in used_endpoints or eb in used_endpoints:
            continue
        if find(c["track_a_id"]) == find(c["track_b_id"]):
            continue
        used_endpoints.add(ea)
        used_endpoints.add(eb)
        union(c["track_a_id"], c["track_b_id"])
        accepted.append(c)

    links: dict[str, list[tuple[str, str, str, dict[str, Any]]]] = defaultdict(list)
    for c in accepted:
        links[c["track_a_id"]].append((c["endpoint_a"], c["track_b_id"], c["endpoint_b"], c))
        links[c["track_b_id"]].append((c["endpoint_b"], c["track_a_id"], c["endpoint_a"], c))

    visited: set[str] = set()
    merged: list[dict[str, Any]] = []
    old_to_new: dict[str, str] = {}

    # Path components first, then isolated tracks.
    starts = [tid for tid in by_id if len(links.get(tid, [])) <= 1]
    starts += [tid for tid in by_id if tid not in starts]

    for start in starts:
        if start in visited:
            continue

        component_ids: list[str] = []
        member_ids: list[str] = []
        pieces: list[dict[str, Any]] = []
        centerline: list[list[float]] = []
        widths: list[float] = []
        stitch_records: list[dict[str, Any]] = []

        current = start
        previous = None
        entry_side = None

        while current in by_id and current not in visited:
            visited.add(current)
            track = by_id[current]
            component_ids.extend(str(x) for x in (track.get("merged_from_track_ids") or [current]))

            current_links = links.get(current, [])
            if entry_side is None:
                if current_links:
                    exit_side = current_links[0][0]
                    entry_side = _other_side(exit_side)
                else:
                    entry_side = "start"

            oriented_center = _oriented_line(track.get("centerline_lcs_m") or [], entry_side)
            oriented_members = list(track.get("member_lane_ids", []) or [])
            oriented_pieces = list(track.get("pieces") or [])
            if entry_side == "end":
                oriented_members.reverse()
                oriented_pieces.reverse()

            member_ids.extend(str(x) for x in oriented_members)
            pieces.extend(oriented_pieces)
            _append_points(centerline, oriented_center)
            if track.get("median_width_m") is not None:
                widths.append(float(track["median_width_m"]))

            next_link = None
            for local_side, other_id, other_side, edge in current_links:
                if other_id == previous:
                    continue
                if local_side != _other_side(entry_side):
                    continue
                next_link = (local_side, other_id, other_side, edge)
                break
            if next_link is None:
                break

            _, other_id, other_side, edge = next_link
            stitch_records.append(edge)
            # Ensure stitch geometry follows current -> other traversal direction.
            if edge["track_a_id"] == current:
                stitch_center = edge.get("stitch_centerline_lcs_m") or []
                stitch_poly = edge.get("stitch_polygon_lcs_m") or []
            else:
                stitch_center = list(reversed(edge.get("stitch_centerline_lcs_m") or []))
                stitch_poly = list(reversed(edge.get("stitch_polygon_lcs_m") or []))
            stitch_piece = {
                "kind": "canonical_track_stitch",
                "source_track_id": current,
                "destination_track_id": other_id,
                "centerline_lcs_m": stitch_center,
                "polygon_lcs_m": stitch_poly,
                "connection_evidence": edge,
            }
            pieces.append(stitch_piece)
            _append_points(centerline, stitch_center)

            previous = current
            current = other_id
            entry_side = other_side

        new_id = component_ids[0]
        width = sorted(widths)[len(widths) // 2] if widths else 3.5
        merged.append({
            "track_id": new_id,
            "logical_lane_id": new_id,
            "member_lane_ids": member_ids,
            "centerline_lcs_m": centerline,
            "polygon_lcs_m": [],
            "median_width_m": round(width, 3),
            "pieces": pieces,
            "piece_count": len(pieces),
            "observed_segment_count": sum(1 for p in pieces if p.get("kind") in {"observed_ld", "recovered_full_edge"}),
            "inferred_gap_count": sum(1 for p in pieces if p.get("kind") in {"inferred_gap", "canonical_track_stitch"}),
            "canonical_stitch_count": len(stitch_records),
            "canonical_stitch_evidence": stitch_records,
            "merged_from_track_ids": component_ids,
            "source": "canonical_stitched_track" if stitch_records else "canonical_continuous_track",
        })
        for old in component_ids:
            old_to_new[old] = new_id

    accepted_keys = {
        (c["track_a_id"], c["endpoint_a"], c["track_b_id"], c["endpoint_b"])
        for c in accepted
    }
    debug = []
    for c in candidates:
        key = (c["track_a_id"], c["endpoint_a"], c["track_b_id"], c["endpoint_b"])
        record = {**c, "accepted": key in accepted_keys}
        if not record["accepted"] and not record["rejection_reasons"]:
            ea = (c["track_a_id"], c["endpoint_a"])
            eb = (c["track_b_id"], c["endpoint_b"])
            record["rejection_reasons"] = [
                "endpoint_already_matched" if ea in used_endpoints or eb in used_endpoints
                else "would_create_stitch_cycle"
            ]
        debug.append(record)

    return merged, old_to_new, debug
