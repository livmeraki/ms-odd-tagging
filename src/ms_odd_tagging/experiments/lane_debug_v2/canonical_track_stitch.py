"""Conservatively stitch fragmented canonical continuous tracks.

This stage runs after the existing canonical segment-to-track reconstruction and
before raw-LD bridge recovery. Boundary endpoint distance is diagnostic only:
a real longitudinal lane gap naturally produces the same gap between boundary
endpoints. Stitch eligibility therefore uses forward/lateral boundary
continuation instead of an absolute boundary-endpoint-distance gate.
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


def _endpoint_heading(line: list[list[float]], *, at_end: bool) -> float | None:
    if len(line) < 2:
        return None
    indices = range(len(line) - 1, 0, -1) if at_end else range(1, len(line))
    for i in indices:
        a, b = line[i - 1], line[i]
        if _dist(a, b) > 1e-4:
            return _heading(a, b)
    return None


def _curvature_proxy(line: list[list[float]], *, at_end: bool) -> float:
    if len(line) < 3:
        return 0.0
    pts = line[-4:] if at_end else line[:4]
    headings, lengths = [], []
    for a, b in zip(pts, pts[1:]):
        d = _dist(a, b)
        if d <= 1e-4:
            continue
        headings.append(_heading(a, b))
        lengths.append(d)
    if len(headings) < 2 or not lengths:
        return 0.0
    return sum(_wrap(b - a) for a, b in zip(headings, headings[1:])) / max(sum(lengths), 1e-6)


def _terminal_lane(track: dict[str, Any], lane_by_id: dict[str, dict[str, Any]], *, at_end: bool):
    members = [str(x) for x in track.get("member_lane_ids", [])]
    ordered = reversed(members) if at_end else members
    for lane_id in ordered:
        if lane_id in lane_by_id:
            return lane_by_id[lane_id]
    return None


def _boundary_terminal(boundary: list[list[float]], track_endpoint: list[float]):
    if not boundary:
        return None
    return min((boundary[0], boundary[-1]), key=lambda p: _dist(p, track_endpoint))


def _boundary_continuation(
    source_track: dict[str, Any],
    destination_track: dict[str, Any],
    lane_by_id: dict[str, dict[str, Any]],
    source_heading: float,
    center_forward_m: float,
) -> dict[str, dict[str, Any]]:
    source_center = source_track.get("centerline_lcs_m") or []
    destination_center = destination_track.get("centerline_lcs_m") or []
    source_lane = _terminal_lane(source_track, lane_by_id, at_end=True)
    destination_lane = _terminal_lane(destination_track, lane_by_id, at_end=False)
    if not source_center or not destination_center or not source_lane or not destination_lane:
        return {}

    output: dict[str, dict[str, Any]] = {}
    for side, key in (("left", "left_boundary_lcs_m"), ("right", "right_boundary_lcs_m")):
        a = _boundary_terminal(source_lane.get(key) or [], source_center[-1])
        b = _boundary_terminal(destination_lane.get(key) or [], destination_center[0])
        if a is None or b is None:
            continue
        dx, dy = float(b[0]) - float(a[0]), float(b[1]) - float(a[1])
        forward = math.cos(source_heading) * dx + math.sin(source_heading) * dy
        lateral = abs(-math.sin(source_heading) * dx + math.cos(source_heading) * dy)
        output[side] = {
            "source_endpoint": [float(a[0]), float(a[1])],
            "destination_endpoint": [float(b[0]), float(b[1])],
            "endpoint_gap_m": _dist(a, b),
            "forward_m": forward,
            "lateral_error_m": lateral,
            "forward_gap_difference_m": abs(forward - center_forward_m),
        }
    return output


def _append_points(target: list[list[float]], points: list[list[float]]) -> None:
    for p in points:
        if len(p) < 2:
            continue
        q = [float(p[0]), float(p[1])]
        if not target or _dist(target[-1], q) > 1e-4:
            target.append(q)


def _evaluate(
    source: dict[str, Any],
    destination: dict[str, Any],
    lane_by_id: dict[str, dict[str, Any]],
    *,
    maximum_endpoint_gap_m: float,
    maximum_heading_difference_deg: float,
    maximum_lateral_error_m: float,
    maximum_width_difference_m: float,
    maximum_boundary_endpoint_gap_m: float,
    maximum_curvature_difference_per_m: float,
) -> dict[str, Any] | None:
    a = source.get("centerline_lcs_m") or []
    b = destination.get("centerline_lcs_m") or []
    if len(a) < 2 or len(b) < 2:
        return None

    gap = _dist(a[-1], b[0])
    source_heading = _endpoint_heading(a, at_end=True)
    destination_heading = _endpoint_heading(b, at_end=False)
    if source_heading is None or destination_heading is None:
        return None

    dx, dy = float(b[0][0]) - float(a[-1][0]), float(b[0][1]) - float(a[-1][1])
    forward = math.cos(source_heading) * dx + math.sin(source_heading) * dy
    lateral = abs(-math.sin(source_heading) * dx + math.cos(source_heading) * dy)
    heading_diff = abs(math.degrees(_wrap(destination_heading - source_heading)))
    width_diff = abs(float(source.get("median_width_m", 3.5)) - float(destination.get("median_width_m", 3.5)))
    curvature_diff = abs(_curvature_proxy(a, at_end=True) - _curvature_proxy(b, at_end=False))

    boundary = _boundary_continuation(source, destination, lane_by_id, source_heading, forward)
    boundary_lateral_limit = min(float(maximum_lateral_error_m), float(maximum_boundary_endpoint_gap_m))
    boundary_forward_difference_limit = max(2.0, float(maximum_boundary_endpoint_gap_m))

    reasons: list[str] = []
    if gap <= 1e-4 or gap > maximum_endpoint_gap_m:
        reasons.append("endpoint_gap")
    if forward <= 0.0:
        reasons.append("destination_not_forward")
    if heading_diff > maximum_heading_difference_deg:
        reasons.append("heading_difference")
    if lateral > maximum_lateral_error_m:
        reasons.append("lateral_error")
    if width_diff > maximum_width_difference_m:
        reasons.append("width_difference")
    if curvature_diff > maximum_curvature_difference_per_m:
        reasons.append("curvature_difference")
    if len(boundary) < 2:
        reasons.append("missing_boundary_endpoint_evidence")
    else:
        if any(v["forward_m"] <= 0.0 for v in boundary.values()):
            reasons.append("boundary_not_forward")
        if any(v["lateral_error_m"] > boundary_lateral_limit for v in boundary.values()):
            reasons.append("boundary_lateral_error")
        if any(v["forward_gap_difference_m"] > boundary_forward_difference_limit for v in boundary.values()):
            reasons.append("boundary_forward_gap_inconsistent")

    boundary_lateral_mean = sum(v["lateral_error_m"] for v in boundary.values()) / len(boundary) if boundary else boundary_lateral_limit
    boundary_forward_diff_mean = sum(v["forward_gap_difference_m"] for v in boundary.values()) / len(boundary) if boundary else boundary_forward_difference_limit
    score = (
        gap + lateral * 4.0 + heading_diff * 0.08 + width_diff + curvature_diff * 15.0
        + boundary_lateral_mean * 3.0 + boundary_forward_diff_mean * 0.5
    )

    left = boundary.get("left")
    right = boundary.get("right")
    polygon = []
    if left and right:
        polygon = [left["source_endpoint"], left["destination_endpoint"], right["destination_endpoint"], right["source_endpoint"]]

    return {
        "source_track_id": str(source.get("track_id")),
        "destination_track_id": str(destination.get("track_id")),
        "endpoint_gap_m": round(gap, 3),
        "forward_projection_m": round(forward, 3),
        "lateral_error_m": round(lateral, 3),
        "heading_difference_deg": round(heading_diff, 3),
        "width_difference_m": round(width_diff, 3),
        "curvature_difference_per_m": round(curvature_diff, 5),
        "boundary_continuation_method": "forward_and_lateral_alignment",
        "boundary_lateral_limit_m": round(boundary_lateral_limit, 3),
        "boundary_forward_gap_difference_limit_m": round(boundary_forward_difference_limit, 3),
        "left_boundary_endpoint_gap_m": None if not left else round(left["endpoint_gap_m"], 3),
        "right_boundary_endpoint_gap_m": None if not right else round(right["endpoint_gap_m"], 3),
        "left_boundary_forward_m": None if not left else round(left["forward_m"], 3),
        "right_boundary_forward_m": None if not right else round(right["forward_m"], 3),
        "left_boundary_lateral_error_m": None if not left else round(left["lateral_error_m"], 3),
        "right_boundary_lateral_error_m": None if not right else round(right["lateral_error_m"], 3),
        "left_boundary_forward_gap_difference_m": None if not left else round(left["forward_gap_difference_m"], 3),
        "right_boundary_forward_gap_difference_m": None if not right else round(right["forward_gap_difference_m"], 3),
        "stitch_centerline_lcs_m": [[float(a[-1][0]), float(a[-1][1])], [float(b[0][0]), float(b[0][1])]],
        "stitch_polygon_lcs_m": polygon,
        "score": round(score, 4),
        "rejection_reasons": reasons,
    }


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
    candidates = []
    for source in tracks:
        for destination in tracks:
            if source is destination:
                continue
            record = _evaluate(
                source, destination, lane_by_id,
                maximum_endpoint_gap_m=maximum_endpoint_gap_m,
                maximum_heading_difference_deg=maximum_heading_difference_deg,
                maximum_lateral_error_m=maximum_lateral_error_m,
                maximum_width_difference_m=maximum_width_difference_m,
                maximum_boundary_endpoint_gap_m=maximum_boundary_endpoint_gap_m,
                maximum_curvature_difference_per_m=maximum_curvature_difference_per_m,
            )
            if record is not None:
                candidates.append(record)

    eligible = [c for c in candidates if not c["rejection_reasons"]]
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in eligible:
        outgoing[c["source_track_id"]].append(c)
        incoming[c["destination_track_id"]].append(c)
    best_out = {k: min(v, key=lambda x: (x["score"], x["destination_track_id"])) for k, v in outgoing.items()}
    best_in = {k: min(v, key=lambda x: (x["score"], x["source_track_id"])) for k, v in incoming.items()}
    accepted = {src: c for src, c in best_out.items() if best_in.get(c["destination_track_id"]) is c}

    predecessors = {c["destination_track_id"]: src for src, c in accepted.items()}
    starts = [tid for tid in by_id if tid not in predecessors] + [tid for tid in by_id if tid in predecessors]
    visited, merged, old_to_new = set(), [], {}

    for start in starts:
        if start in visited:
            continue
        current = start
        source_ids, member_ids, pieces, centerline, widths, stitch_records = [], [], [], [], [], []
        while current in by_id and current not in visited:
            visited.add(current)
            track = by_id[current]
            source_ids.extend(str(x) for x in (track.get("merged_from_track_ids") or [current]))
            member_ids.extend(str(x) for x in track.get("member_lane_ids", []))
            pieces.extend(track.get("pieces") or [])
            _append_points(centerline, track.get("centerline_lcs_m") or [])
            if track.get("median_width_m") is not None:
                widths.append(float(track["median_width_m"]))
            edge = accepted.get(current)
            if not edge:
                break
            stitch_records.append(edge)
            stitch_piece = {
                "kind": "canonical_track_stitch",
                "source_track_id": edge["source_track_id"],
                "destination_track_id": edge["destination_track_id"],
                "centerline_lcs_m": edge.get("stitch_centerline_lcs_m") or [],
                "polygon_lcs_m": edge.get("stitch_polygon_lcs_m") or [],
                "connection_evidence": edge,
            }
            pieces.append(stitch_piece)
            _append_points(centerline, stitch_piece["centerline_lcs_m"])
            current = edge["destination_track_id"]

        new_id = source_ids[0]
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
            "merged_from_track_ids": source_ids,
            "source": "canonical_stitched_track" if stitch_records else "canonical_continuous_track",
        })
        for old in source_ids:
            old_to_new[old] = new_id

    accepted_pairs = {(c["source_track_id"], c["destination_track_id"]) for c in accepted.values()}
    debug = []
    for c in candidates:
        record = {**c, "accepted": (c["source_track_id"], c["destination_track_id"]) in accepted_pairs}
        if not record["accepted"] and not record["rejection_reasons"]:
            record["rejection_reasons"] = ["not_mutual_best_endpoint_continuation"]
        debug.append(record)
    return merged, old_to_new, debug
