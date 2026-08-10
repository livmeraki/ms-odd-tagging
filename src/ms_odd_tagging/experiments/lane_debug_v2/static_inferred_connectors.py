"""Curvature-aware connector polygons between static inferred corridors and observed lane pieces."""
from __future__ import annotations

import copy
import math
from typing import Any

from .curvature_gap_fill import build_curvature_gap

_OBSERVED_KINDS = {
    "observed_ld",
    "recovered_full_edge",
    "inferred_gap",
    "anchored_ld_bridge",
    "canonical_track_stitch",
    "topology_supported_curvature_stitch",
}


def _dist(a: list[float], b: list[float]) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _best_piece_endpoint(
    track: dict[str, Any],
    target: list[float],
    *,
    excluded_kinds: set[str] | None = None,
) -> tuple[dict[str, Any], str, float] | None:
    excluded_kinds = excluded_kinds or set()
    best = None
    for piece in track.get("pieces") or []:
        kind = str(piece.get("kind"))
        if kind in excluded_kinds or kind not in _OBSERVED_KINDS:
            continue
        line = piece.get("centerline_lcs_m") or []
        if len(line) < 2:
            continue
        for side, point in (("start", line[0]), ("end", line[-1])):
            gap = _dist(point, target)
            candidate = (gap, piece, side)
            if best is None or candidate[0] < best[0]:
                best = candidate
    if best is None:
        return None
    return best[1], best[2], best[0]


def _connector(
    line_a: list[list[float]],
    side_a: str,
    width_a: float,
    line_b: list[list[float]],
    side_b: str,
    width_b: float,
    *,
    route_id: str | None,
    role: str,
    maximum_gap_m: float,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    endpoint_a = line_a[0] if side_a == "start" else line_a[-1]
    endpoint_b = line_b[0] if side_b == "start" else line_b[-1]
    gap = _dist(endpoint_a, endpoint_b)
    debug = {"role": role, "gap_m": round(gap, 3), "accepted": False}
    if gap <= 0.25:
        debug.update({"accepted": True, "status": "already_touching"})
        return None, debug
    if gap > maximum_gap_m:
        debug["rejection_reason"] = "gap_too_large"
        return None, debug

    fill = build_curvature_gap(
        line_a,
        side_a,
        line_b,
        side_b,
        width_a_m=width_a,
        width_b_m=width_b,
    )
    if fill is None:
        debug["rejection_reason"] = "curvature_gap_generation_failed"
        return None, debug
    arc_ratio = float(fill.get("arc_to_chord_ratio", 999.0))
    max_curvature = float(fill.get("maximum_abs_bridge_curvature_per_m", 999.0))
    debug.update({
        "arc_to_chord_ratio": round(arc_ratio, 4),
        "maximum_abs_curvature_per_m": round(max_curvature, 5),
    })
    if arc_ratio > 1.6:
        debug["rejection_reason"] = "connector_arc_too_long"
        return None, debug
    if max_curvature > 0.25:
        debug["rejection_reason"] = "connector_curvature_too_high"
        return None, debug

    piece = {
        "kind": "static_inferred_connector",
        "route_id": route_id,
        "connector_role": role,
        "source": "curvature_aware_static_inferred_gap_fill",
        "centerline_lcs_m": fill["centerline_lcs_m"],
        "left_boundary_lcs_m": fill["left_boundary_lcs_m"],
        "right_boundary_lcs_m": fill["right_boundary_lcs_m"],
        "polygon_lcs_m": fill["polygon_lcs_m"],
        "connection_evidence": {
            "gap_m": round(gap, 3),
            "arc_to_chord_ratio": round(arc_ratio, 4),
            "maximum_abs_curvature_per_m": round(max_curvature, 5),
            "method": fill.get("method"),
        },
    }
    debug.update({"accepted": True, "status": "connector_created"})
    return piece, debug


def fill_static_inferred_endpoint_gaps(
    tracks: list[dict[str, Any]],
    *,
    maximum_gap_m: float = 20.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Add back/front connector polygons around every static inferred corridor."""
    out = copy.deepcopy(tracks)
    debug: list[dict[str, Any]] = []

    for track in out:
        static_pieces = [p for p in track.get("pieces") or [] if p.get("kind") == "static_inferred_corridor"]
        additions: list[dict[str, Any]] = []
        for static_piece in static_pieces:
            center = static_piece.get("centerline_lcs_m") or []
            if len(center) < 2:
                continue
            width_static = float(track.get("median_width_m", 3.5))
            route_id = static_piece.get("route_id")

            back_match = _best_piece_endpoint(track, center[0])
            front_match = _best_piece_endpoint(track, center[-1])
            for role, match, static_side in (("back", back_match, "start"), ("front", front_match, "end")):
                record = {"track_id": track.get("track_id"), "route_id": route_id, "role": role}
                if match is None:
                    record.update({"accepted": False, "rejection_reason": "no_observed_piece_endpoint"})
                    debug.append(record)
                    continue
                observed_piece, observed_side, observed_gap = match
                observed_line = observed_piece.get("centerline_lcs_m") or []
                observed_width = float(track.get("median_width_m", 3.5))
                if role == "back":
                    connector, evidence = _connector(
                        observed_line, observed_side, observed_width,
                        center, "start", width_static,
                        route_id=route_id, role=role, maximum_gap_m=maximum_gap_m,
                    )
                else:
                    connector, evidence = _connector(
                        center, "end", width_static,
                        observed_line, observed_side, observed_width,
                        route_id=route_id, role=role, maximum_gap_m=maximum_gap_m,
                    )
                evidence.update({
                    "track_id": track.get("track_id"),
                    "route_id": route_id,
                    "observed_piece_kind": observed_piece.get("kind"),
                    "observed_lane_id": observed_piece.get("lane_id"),
                    "observed_endpoint_side": observed_side,
                    "nearest_observed_endpoint_gap_m": round(observed_gap, 3),
                })
                debug.append(evidence)
                if connector is not None:
                    additions.append(connector)
        if additions:
            track.setdefault("pieces", []).extend(additions)
            track["piece_count"] = len(track.get("pieces") or [])
            track["static_inferred_connector_count"] = int(track.get("static_inferred_connector_count", 0)) + len(additions)
            track["inferred_gap_count"] = int(track.get("inferred_gap_count", 0)) + len(additions)

    return out, debug
