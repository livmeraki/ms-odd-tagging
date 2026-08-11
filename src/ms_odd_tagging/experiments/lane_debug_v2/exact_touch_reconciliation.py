"""Conservative exact-touch reconciliation for already-constructed lane tracks.

This stage repairs duplicate physical-track identities caused by canonical lane
fragments that touch exactly but were not linked by the ordinary forward-gap
continuation pass. It deliberately does not create synthetic geometry.
"""
from __future__ import annotations

import math
from typing import Any


def _dist(a: list[float], b: list[float]) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _heading(a: list[float], b: list[float]) -> float:
    return math.atan2(float(b[1]) - float(a[1]), float(b[0]) - float(a[0]))


def _angle_diff_deg(a: float, b: float) -> float:
    d = (a - b + math.pi) % (2.0 * math.pi) - math.pi
    return abs(math.degrees(d))


def _append_points(dst: list[list[float]], src: list[list[float]]) -> None:
    for p in src or []:
        if len(p) < 2:
            continue
        q = [float(p[0]), float(p[1])]
        if not dst or _dist(dst[-1], q) > 1e-4:
            dst.append(q)


def _observed_piece(track: dict[str, Any], *, at_end: bool) -> dict[str, Any] | None:
    pieces = list(track.get("pieces") or [])
    iterable = reversed(pieces) if at_end else pieces
    for piece in iterable:
        if piece.get("lane_id") is None:
            continue
        center = piece.get("centerline_lcs_m") or []
        if len(center) >= 2:
            return piece
    return None


def _lane_width_at_endpoint(lane: dict[str, Any], *, at_end: bool) -> float | None:
    left = lane.get("left_boundary_lcs_m") or []
    right = lane.get("right_boundary_lcs_m") or []
    if not left or not right:
        return None
    lp = left[-1] if at_end else left[0]
    rp = right[-1] if at_end else right[0]
    if len(lp) < 2 or len(rp) < 2:
        return None
    return _dist(lp, rp)


def _boundary_endpoint_metrics(
    source_lane: dict[str, Any], destination_lane: dict[str, Any]
) -> dict[str, Any]:
    sl = source_lane.get("left_boundary_lcs_m") or []
    sr = source_lane.get("right_boundary_lcs_m") or []
    dl = destination_lane.get("left_boundary_lcs_m") or []
    dr = destination_lane.get("right_boundary_lcs_m") or []
    if not sl or not sr or not dl or not dr:
        return {
            "left_endpoint_gap_m": None,
            "right_endpoint_gap_m": None,
            "same_left_edge_id": False,
            "same_right_edge_id": False,
            "boundary_identity_score": 0,
        }
    same_left = (
        source_lane.get("left_edge_id") is not None
        and str(source_lane.get("left_edge_id")) == str(destination_lane.get("left_edge_id"))
    )
    same_right = (
        source_lane.get("right_edge_id") is not None
        and str(source_lane.get("right_edge_id")) == str(destination_lane.get("right_edge_id"))
    )
    return {
        "left_endpoint_gap_m": _dist(sl[-1], dl[0]),
        "right_endpoint_gap_m": _dist(sr[-1], dr[0]),
        "same_left_edge_id": same_left,
        "same_right_edge_id": same_right,
        "boundary_identity_score": int(same_left) + int(same_right),
    }


def _candidate(
    source: dict[str, Any],
    destination: dict[str, Any],
    lane_by_id: dict[str, dict[str, Any]],
    *,
    maximum_endpoint_gap_m: float,
    maximum_heading_difference_deg: float,
    maximum_local_width_difference_m: float,
    maximum_boundary_endpoint_gap_m: float,
) -> dict[str, Any] | None:
    src_piece = _observed_piece(source, at_end=True)
    dst_piece = _observed_piece(destination, at_end=False)
    if src_piece is None or dst_piece is None:
        return None
    src_lane_id = str(src_piece.get("lane_id"))
    dst_lane_id = str(dst_piece.get("lane_id"))
    src_lane = lane_by_id.get(src_lane_id)
    dst_lane = lane_by_id.get(dst_lane_id)
    if not src_lane or not dst_lane:
        return None
    src_center = src_piece.get("centerline_lcs_m") or []
    dst_center = dst_piece.get("centerline_lcs_m") or []
    if len(src_center) < 2 or len(dst_center) < 2:
        return None

    endpoint_gap = _dist(src_center[-1], dst_center[0])
    heading_diff = _angle_diff_deg(
        _heading(src_center[-2], src_center[-1]),
        _heading(dst_center[0], dst_center[1]),
    )
    src_width = _lane_width_at_endpoint(src_lane, at_end=True)
    dst_width = _lane_width_at_endpoint(dst_lane, at_end=False)
    width_diff = None if src_width is None or dst_width is None else abs(src_width - dst_width)
    boundary = _boundary_endpoint_metrics(src_lane, dst_lane)

    reasons: list[str] = []
    if endpoint_gap > maximum_endpoint_gap_m:
        reasons.append("centerline_endpoint_gap")
    if heading_diff > maximum_heading_difference_deg:
        reasons.append("local_tangent_difference")
    if width_diff is None or width_diff > maximum_local_width_difference_m:
        reasons.append("local_endpoint_width_difference")
    if boundary["left_endpoint_gap_m"] is None or boundary["right_endpoint_gap_m"] is None:
        reasons.append("missing_boundary_endpoint_geometry")
    else:
        if boundary["left_endpoint_gap_m"] > maximum_boundary_endpoint_gap_m:
            reasons.append("left_boundary_endpoint_gap")
        if boundary["right_endpoint_gap_m"] > maximum_boundary_endpoint_gap_m:
            reasons.append("right_boundary_endpoint_gap")

    return {
        "source_track_id": str(source.get("track_id")),
        "destination_track_id": str(destination.get("track_id")),
        "source_lane_id": src_lane_id,
        "destination_lane_id": dst_lane_id,
        "centerline_endpoint_gap_m": round(endpoint_gap, 4),
        "heading_difference_deg": round(heading_diff, 3),
        "source_local_width_m": None if src_width is None else round(src_width, 3),
        "destination_local_width_m": None if dst_width is None else round(dst_width, 3),
        "local_width_difference_m": None if width_diff is None else round(width_diff, 3),
        "left_boundary_endpoint_gap_m": None if boundary["left_endpoint_gap_m"] is None else round(boundary["left_endpoint_gap_m"], 4),
        "right_boundary_endpoint_gap_m": None if boundary["right_endpoint_gap_m"] is None else round(boundary["right_endpoint_gap_m"], 4),
        "same_left_edge_id": boundary["same_left_edge_id"],
        "same_right_edge_id": boundary["same_right_edge_id"],
        "boundary_identity_score": boundary["boundary_identity_score"],
        "rejection_reasons": reasons,
        "eligible": not reasons,
    }


def _merge_tracks(source: dict[str, Any], destination: dict[str, Any]) -> dict[str, Any]:
    merged = dict(source)
    members = list(source.get("member_lane_ids") or [])
    for lane_id in destination.get("member_lane_ids") or []:
        if lane_id not in members:
            members.append(lane_id)
    pieces = list(source.get("pieces") or []) + list(destination.get("pieces") or [])
    centerline: list[list[float]] = []
    for piece in pieces:
        _append_points(centerline, piece.get("centerline_lcs_m") or [])
    if len(centerline) < 2:
        centerline = list(source.get("centerline_lcs_m") or [])
        _append_points(centerline, destination.get("centerline_lcs_m") or [])
    merged["member_lane_ids"] = members
    merged["pieces"] = pieces
    merged["piece_count"] = len(pieces)
    merged["centerline_lcs_m"] = centerline
    merged["observed_segment_count"] = sum(1 for p in pieces if p.get("lane_id") is not None)
    merged["inferred_gap_count"] = sum(1 for p in pieces if p.get("kind") == "inferred_gap")
    merged["exact_touch_merged_track_ids"] = list(source.get("exact_touch_merged_track_ids") or []) + [str(destination.get("track_id"))]
    return merged


def reconcile_exact_touch_tracks(
    tracks: list[dict[str, Any]],
    lane_geometry: list[dict[str, Any]],
    *,
    maximum_endpoint_gap_m: float = 0.25,
    maximum_heading_difference_deg: float = 8.0,
    maximum_local_width_difference_m: float = 0.5,
    maximum_boundary_endpoint_gap_m: float = 0.25,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Merge unambiguous exact-touch track endpoints without synthetic fills."""
    lane_by_id = {str(l.get("lane_id")): l for l in lane_geometry}
    working = [dict(t) for t in tracks]
    debug: list[dict[str, Any]] = []

    changed = True
    while changed:
        changed = False
        candidates_by_source: dict[str, list[dict[str, Any]]] = {}
        track_by_id = {str(t.get("track_id")): t for t in working}
        for source in working:
            sid = str(source.get("track_id"))
            rows: list[dict[str, Any]] = []
            for destination in working:
                if destination is source:
                    continue
                row = _candidate(
                    source,
                    destination,
                    lane_by_id,
                    maximum_endpoint_gap_m=maximum_endpoint_gap_m,
                    maximum_heading_difference_deg=maximum_heading_difference_deg,
                    maximum_local_width_difference_m=maximum_local_width_difference_m,
                    maximum_boundary_endpoint_gap_m=maximum_boundary_endpoint_gap_m,
                )
                if row is not None:
                    rows.append(row)
            candidates_by_source[sid] = rows

        selected: tuple[str, str, dict[str, Any]] | None = None
        for sid in sorted(candidates_by_source):
            eligible = [r for r in candidates_by_source[sid] if r.get("eligible")]
            if not eligible:
                debug.extend(candidates_by_source[sid])
                continue
            if len(eligible) > 1:
                max_identity = max(int(r.get("boundary_identity_score", 0)) for r in eligible)
                strongest = [r for r in eligible if int(r.get("boundary_identity_score", 0)) == max_identity]
                if max_identity <= 0 or len(strongest) != 1:
                    for row in candidates_by_source[sid]:
                        row = dict(row)
                        if row.get("eligible"):
                            row["eligible"] = False
                            row["rejection_reasons"] = list(row.get("rejection_reasons") or []) + ["ambiguous_fork_multiple_exact_touch_destinations"]
                        debug.append(row)
                    continue
                eligible = strongest
            chosen = min(
                eligible,
                key=lambda r: (
                    -int(r.get("boundary_identity_score", 0)),
                    float(r.get("centerline_endpoint_gap_m", math.inf)),
                    float(r.get("heading_difference_deg", math.inf)),
                    str(r.get("destination_track_id")),
                ),
            )
            selected = (sid, str(chosen["destination_track_id"]), chosen)
            for row in candidates_by_source[sid]:
                row = dict(row)
                row["accepted"] = row is chosen or (
                    row.get("destination_track_id") == chosen.get("destination_track_id")
                    and row.get("source_track_id") == chosen.get("source_track_id")
                )
                debug.append(row)
            break

        if selected is None:
            break
        sid, did, chosen = selected
        source = track_by_id.get(sid)
        destination = track_by_id.get(did)
        if source is None or destination is None:
            break
        merged = _merge_tracks(source, destination)
        working = [t for t in working if str(t.get("track_id")) not in {sid, did}]
        working.append(merged)
        working.sort(key=lambda t: str(t.get("track_id")))
        debug.append({**chosen, "accepted": True, "action": "merge_exact_touch_tracks_preserve_source_id"})
        changed = True

    return working, debug
