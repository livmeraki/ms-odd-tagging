"""Orientation-aware, curvature-aware stitching for fragmented canonical tracks.

Every physical endpoint combination is considered.  A continuation is evaluated
by constructing a smooth quintic Hermite lane completion using endpoint position,
tangent and curvature.  The straight chord across a gap is diagnostic only; it is
not treated as the road shape.  Accepted fills remain local pieces of an existing
canonical track and never create standalone lanes.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from .curvature_gap_fill import build_curvature_gap, endpoint_state


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


def _oriented_line(line: list[list[float]], entry_side: str) -> list[list[float]]:
    pts = [[float(p[0]), float(p[1])] for p in line if len(p) >= 2]
    return pts if entry_side == "start" else list(reversed(pts))


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


def _endpoint_width(track: dict[str, Any], lane_by_id: dict[str, dict[str, Any]], endpoint: list[float]) -> float:
    lane = _terminal_lane(track, lane_by_id, endpoint)
    if lane:
        left = _boundary_endpoint(lane.get("left_boundary_lcs_m") or [], endpoint)
        right = _boundary_endpoint(lane.get("right_boundary_lcs_m") or [], endpoint)
        if left is not None and right is not None:
            return _dist(left, right)
    return float(track.get("median_width_m", 3.5))


def _boundary_pair_debug(
    track_a: dict[str, Any], side_a: str,
    track_b: dict[str, Any], side_b: str,
    lane_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    line_a = track_a.get("centerline_lcs_m") or []
    line_b = track_b.get("centerline_lcs_m") or []
    if not line_a or not line_b:
        return {}
    pa, pb = _endpoint_point(line_a, side_a), _endpoint_point(line_b, side_b)
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
    a: dict[str, Any], side_a: str,
    b: dict[str, Any], side_b: str,
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
    pa, pb = _endpoint_point(line_a, side_a), _endpoint_point(line_b, side_b)
    gap = _dist(pa, pb)
    if gap <= 1e-4 or gap > maximum_endpoint_gap_m:
        return None

    sa = endpoint_state(line_a, side_a)
    sb = endpoint_state(line_b, side_b)
    if sa is None or sb is None:
        return None
    gap_heading = _heading(pa, pb)
    source_to_chord = _angle_diff_deg(sa["heading"], gap_heading)
    destination_to_chord = _angle_diff_deg(sb["heading"], _wrap(gap_heading + math.pi))
    tangent_opposition = abs(180.0 - _angle_diff_deg(sa["heading"], sb["heading"]))

    width_a = _endpoint_width(a, lane_by_id, pa)
    width_b = _endpoint_width(b, lane_by_id, pb)
    width_diff = abs(width_a - width_b)
    endpoint_curvature_diff = abs(abs(sa["curvature"]) - abs(sb["curvature"]))

    fill = build_curvature_gap(
        line_a, side_a, line_b, side_b,
        width_a_m=width_a,
        width_b_m=width_b,
    )
    if fill is None:
        return None

    # Curved roads need not point at the straight chord.  These wider gates only
    # reject geometrically implausible back-facing/cross-road endpoint matches.
    chord_heading_limit = max(45.0, maximum_heading_difference_deg * 3.0)
    tangent_turn_limit = max(55.0, maximum_heading_difference_deg * 4.0)
    endpoint_k = max(abs(float(sa["curvature"])), abs(float(sb["curvature"])))
    max_bridge_curvature = float(fill["maximum_abs_bridge_curvature_per_m"])
    curvature_limit = max(0.16, endpoint_k + max(0.08, maximum_curvature_difference_per_m))
    arc_ratio = float(fill["arc_to_chord_ratio"])

    boundary = _boundary_pair_debug(a, side_a, b, side_b, lane_by_id)
    reasons: list[str] = []
    if source_to_chord > chord_heading_limit:
        reasons.append("source_endpoint_faces_away_from_gap")
    if destination_to_chord > chord_heading_limit:
        reasons.append("destination_endpoint_faces_away_from_gap")
    if tangent_opposition > tangent_turn_limit:
        reasons.append("endpoint_tangent_turn_too_large")
    if width_diff > maximum_width_difference_m:
        reasons.append("width_difference")
    if endpoint_curvature_diff > max(0.12, maximum_curvature_difference_per_m * 2.0):
        reasons.append("endpoint_curvature_mismatch")
    if arc_ratio > 1.40:
        reasons.append("bridge_arc_excessive_for_gap")
    if max_bridge_curvature > curvature_limit:
        reasons.append("bridge_curvature_excessive")
    if not boundary:
        reasons.append("missing_boundary_endpoint_evidence")

    # Lower score is better.  Chord/tangent differences influence selection but
    # do not force a straight bridge.
    score = (
        gap
        + width_diff * 2.0
        + source_to_chord * 0.025
        + destination_to_chord * 0.025
        + tangent_opposition * 0.03
        + endpoint_curvature_diff * 12.0
        + max(0.0, arc_ratio - 1.0) * 12.0
        + max_bridge_curvature * 8.0
    )

    return {
        "track_a_id": str(a.get("track_id")),
        "track_b_id": str(b.get("track_id")),
        "endpoint_a": side_a,
        "endpoint_b": side_b,
        "endpoint_gap_m": round(gap, 3),
        "source_to_chord_heading_difference_deg": round(source_to_chord, 3),
        "destination_to_chord_heading_difference_deg": round(destination_to_chord, 3),
        "endpoint_tangent_opposition_error_deg": round(tangent_opposition, 3),
        "endpoint_a_curvature_per_m": round(float(sa["curvature"]), 5),
        "endpoint_b_curvature_per_m": round(float(sb["curvature"]), 5),
        "endpoint_curvature_difference_per_m": round(endpoint_curvature_diff, 5),
        "width_a_m": round(width_a, 3),
        "width_b_m": round(width_b, 3),
        "width_difference_m": round(width_diff, 3),
        "bridge_method": fill["method"],
        "bridge_arc_length_m": round(float(fill["arc_length_m"]), 3),
        "bridge_chord_length_m": round(float(fill["chord_length_m"]), 3),
        "bridge_arc_to_chord_ratio": round(arc_ratio, 4),
        "bridge_max_abs_curvature_per_m": round(max_bridge_curvature, 5),
        "bridge_curvature_limit_per_m": round(curvature_limit, 5),
        "boundary_side_mapping_swapped": None if not boundary else boundary["side_mapping_swapped"],
        "stitch_centerline_lcs_m": fill["centerline_lcs_m"],
        "stitch_left_boundary_lcs_m": fill["left_boundary_lcs_m"],
        "stitch_right_boundary_lcs_m": fill["right_boundary_lcs_m"],
        "stitch_polygon_lcs_m": fill["polygon_lcs_m"],
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
        current, previous, entry_side = start, None, None

        while current in by_id and current not in visited:
            visited.add(current)
            track = by_id[current]
            component_ids.extend(str(x) for x in (track.get("merged_from_track_ids") or [current]))
            current_links = links.get(current, [])
            if entry_side is None:
                entry_side = _other_side(current_links[0][0]) if current_links else "start"

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
                if other_id == previous or local_side != _other_side(entry_side):
                    continue
                next_link = (other_id, other_side, edge)
                break
            if next_link is None:
                break

            other_id, other_side, edge = next_link
            stitch_records.append(edge)
            if edge["track_a_id"] == current:
                stitch_center = edge.get("stitch_centerline_lcs_m") or []
                stitch_left = edge.get("stitch_left_boundary_lcs_m") or []
                stitch_right = edge.get("stitch_right_boundary_lcs_m") or []
                stitch_poly = edge.get("stitch_polygon_lcs_m") or []
            else:
                stitch_center = list(reversed(edge.get("stitch_centerline_lcs_m") or []))
                # Traversal reversal swaps semantic left/right.
                stitch_left = list(reversed(edge.get("stitch_right_boundary_lcs_m") or []))
                stitch_right = list(reversed(edge.get("stitch_left_boundary_lcs_m") or []))
                stitch_poly = stitch_left + list(reversed(stitch_right))
            stitch_piece = {
                "kind": "canonical_track_stitch",
                "source_track_id": current,
                "destination_track_id": other_id,
                "centerline_lcs_m": stitch_center,
                "left_boundary_lcs_m": stitch_left,
                "right_boundary_lcs_m": stitch_right,
                "polygon_lcs_m": stitch_poly,
                "geometry_method": "curvature_aware_quintic_hermite",
                "connection_evidence": edge,
            }
            pieces.append(stitch_piece)
            _append_points(centerline, stitch_center)
            previous, current, entry_side = current, other_id, other_side

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

    accepted_keys = {(c["track_a_id"], c["endpoint_a"], c["track_b_id"], c["endpoint_b"]) for c in accepted}
    debug = []
    for c in candidates:
        key = (c["track_a_id"], c["endpoint_a"], c["track_b_id"], c["endpoint_b"])
        record = {**c, "accepted": key in accepted_keys}
        if not record["accepted"] and not record["rejection_reasons"]:
            ea, eb = (c["track_a_id"], c["endpoint_a"]), (c["track_b_id"], c["endpoint_b"])
            record["rejection_reasons"] = ["endpoint_already_matched" if ea in used_endpoints or eb in used_endpoints else "would_create_stitch_cycle"]
        debug.append(record)
    return merged, old_to_new, debug
