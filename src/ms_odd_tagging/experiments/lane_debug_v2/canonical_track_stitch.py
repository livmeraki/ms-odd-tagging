"""Conservatively stitch fragmented canonical continuous tracks.

This stage runs after the existing canonical segment-to-track reconstruction and
before any raw-LD bridge recovery. It never invents a standalone lane. It only
merges two already-constructed canonical tracks when their facing endpoints,
widths, headings, curvature trend, and physical lane boundaries support a
single-lane continuation.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


def _dist(a: list[float] | tuple[float, float], b: list[float] | tuple[float, float]) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def _heading(a, b) -> float:
    return math.atan2(float(b[1]) - float(a[1]), float(b[0]) - float(a[0]))


def _endpoint_heading(line: list[list[float]], *, at_end: bool) -> float | None:
    if len(line) < 2:
        return None
    if at_end:
        for i in range(len(line) - 1, 0, -1):
            if _dist(line[i - 1], line[i]) > 1e-4:
                return _heading(line[i - 1], line[i])
    else:
        for i in range(1, len(line)):
            if _dist(line[i - 1], line[i]) > 1e-4:
                return _heading(line[i - 1], line[i])
    return None


def _curvature_proxy(line: list[list[float]], *, at_end: bool) -> float:
    """Signed heading change per metre over a short endpoint window."""
    if len(line) < 3:
        return 0.0
    pts = line[-4:] if at_end else line[:4]
    headings: list[float] = []
    lengths: list[float] = []
    for a, b in zip(pts, pts[1:]):
        d = _dist(a, b)
        if d <= 1e-4:
            continue
        headings.append(_heading(a, b))
        lengths.append(d)
    if len(headings) < 2 or not lengths:
        return 0.0
    total_change = sum(_wrap(b - a) for a, b in zip(headings, headings[1:]))
    return total_change / max(sum(lengths), 1e-6)


def _terminal_lane(track: dict[str, Any], lane_by_id: dict[str, dict[str, Any]], *, at_end: bool) -> dict[str, Any] | None:
    members = [str(x) for x in track.get("member_lane_ids", [])]
    ordered = reversed(members) if at_end else members
    for lane_id in ordered:
        lane = lane_by_id.get(lane_id)
        if lane:
            return lane
    return None


def _boundary_terminal(boundary: list[list[float]], track_endpoint: list[float]) -> list[float] | None:
    if not boundary:
        return None
    candidates = [boundary[0], boundary[-1]]
    return min(candidates, key=lambda p: _dist(p, track_endpoint))


def _boundary_errors(
    source_track: dict[str, Any],
    destination_track: dict[str, Any],
    lane_by_id: dict[str, dict[str, Any]],
) -> tuple[float | None, float | None]:
    source_center = source_track.get("centerline_lcs_m") or []
    destination_center = destination_track.get("centerline_lcs_m") or []
    if not source_center or not destination_center:
        return None, None
    source_lane = _terminal_lane(source_track, lane_by_id, at_end=True)
    destination_lane = _terminal_lane(destination_track, lane_by_id, at_end=False)
    if not source_lane or not destination_lane:
        return None, None

    errors: list[float | None] = []
    for key in ("left_boundary_lcs_m", "right_boundary_lcs_m"):
        a = _boundary_terminal(source_lane.get(key) or [], source_center[-1])
        b = _boundary_terminal(destination_lane.get(key) or [], destination_center[0])
        errors.append(None if a is None or b is None else _dist(a, b))
    return errors[0], errors[1]


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
    if gap <= 1e-4 or gap > maximum_endpoint_gap_m:
        return None

    source_heading = _endpoint_heading(a, at_end=True)
    destination_heading = _endpoint_heading(b, at_end=False)
    if source_heading is None or destination_heading is None:
        return None
    heading_diff = abs(math.degrees(_wrap(destination_heading - source_heading)))

    dx = float(b[0][0]) - float(a[-1][0])
    dy = float(b[0][1]) - float(a[-1][1])
    forward = math.cos(source_heading) * dx + math.sin(source_heading) * dy
    lateral = abs(-math.sin(source_heading) * dx + math.cos(source_heading) * dy)

    width_a = float(source.get("median_width_m", 3.5))
    width_b = float(destination.get("median_width_m", 3.5))
    width_diff = abs(width_a - width_b)
    curvature_diff = abs(_curvature_proxy(a, at_end=True) - _curvature_proxy(b, at_end=False))
    left_error, right_error = _boundary_errors(source, destination, lane_by_id)
    available_boundary_errors = [x for x in (left_error, right_error) if x is not None]

    reasons: list[str] = []
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
    if len(available_boundary_errors) < 2:
        reasons.append("missing_boundary_endpoint_evidence")
    elif max(available_boundary_errors) > maximum_boundary_endpoint_gap_m:
        reasons.append("boundary_endpoint_gap")

    score = (
        gap
        + lateral * 4.0
        + heading_diff * 0.08
        + width_diff
        + curvature_diff * 15.0
        + (sum(available_boundary_errors) / len(available_boundary_errors) if available_boundary_errors else maximum_boundary_endpoint_gap_m)
    )
    return {
        "source_track_id": str(source.get("track_id")),
        "destination_track_id": str(destination.get("track_id")),
        "endpoint_gap_m": round(gap, 3),
        "forward_projection_m": round(forward, 3),
        "lateral_error_m": round(lateral, 3),
        "heading_difference_deg": round(heading_diff, 3),
        "width_difference_m": round(width_diff, 3),
        "curvature_difference_per_m": round(curvature_diff, 5),
        "left_boundary_endpoint_gap_m": None if left_error is None else round(left_error, 3),
        "right_boundary_endpoint_gap_m": None if right_error is None else round(right_error, 3),
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
    """Merge mutually-best one-to-one canonical endpoint continuations."""
    lane_by_id = {str(l.get("lane_id")): l for l in lane_geometry}
    by_id = {str(t.get("track_id")): t for t in tracks}
    candidates: list[dict[str, Any]] = []
    for source in tracks:
        for destination in tracks:
            if source is destination:
                continue
            record = _evaluate(
                source,
                destination,
                lane_by_id,
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

    accepted: dict[str, dict[str, Any]] = {}
    for source_id, candidate in best_out.items():
        if best_in.get(candidate["destination_track_id"]) is candidate:
            accepted[source_id] = candidate

    predecessors = {c["destination_track_id"]: source_id for source_id, c in accepted.items()}
    visited: set[str] = set()
    merged: list[dict[str, Any]] = []
    old_to_new: dict[str, str] = {}
    starts = [tid for tid in by_id if tid not in predecessors] + [tid for tid in by_id if tid in predecessors]

    for start in starts:
        if start in visited:
            continue
        current = start
        source_ids: list[str] = []
        member_ids: list[str] = []
        pieces: list[dict[str, Any]] = []
        centerline: list[list[float]] = []
        widths: list[float] = []
        stitch_records: list[dict[str, Any]] = []
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
            pieces.append({
                "kind": "canonical_track_stitch",
                "source_track_id": edge["source_track_id"],
                "destination_track_id": edge["destination_track_id"],
                "connection_evidence": edge,
            })
            current = edge["destination_track_id"]

        new_id = source_ids[0]
        width = sorted(widths)[len(widths) // 2] if widths else 3.5
        out = {
            "track_id": new_id,
            "logical_lane_id": new_id,
            "member_lane_ids": member_ids,
            "centerline_lcs_m": centerline,
            "polygon_lcs_m": [],
            "median_width_m": round(width, 3),
            "pieces": pieces,
            "piece_count": len(pieces),
            "observed_segment_count": sum(1 for p in pieces if p.get("kind") in {"observed_ld", "recovered_full_edge"}),
            "inferred_gap_count": sum(1 for p in pieces if p.get("kind") == "inferred_gap"),
            "canonical_stitch_count": len(stitch_records),
            "canonical_stitch_evidence": stitch_records,
            "merged_from_track_ids": source_ids,
            "source": "canonical_stitched_track" if stitch_records else track.get("source", "canonical_continuous_track"),
        }
        merged.append(out)
        for old in source_ids:
            old_to_new[old] = new_id

    accepted_pairs = {(c["source_track_id"], c["destination_track_id"]) for c in accepted.values()}
    debug = []
    for c in candidates:
        pair = (c["source_track_id"], c["destination_track_id"])
        record = {**c, "accepted": pair in accepted_pairs}
        if not record["accepted"] and not record["rejection_reasons"]:
            record["rejection_reasons"] = ["not_mutual_best_endpoint_continuation"]
        debug.append(record)
    return merged, old_to_new, debug
