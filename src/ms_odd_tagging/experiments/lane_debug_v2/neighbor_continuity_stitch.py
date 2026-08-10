"""Topology-supported stitching for fragmented physical lane tracks.

This is a second-pass stitcher.  It only considers pairs that appear as the same
immediate left/right neighbor of one reference track on consecutive static
cross-sections.  That lane-order evidence makes it safe to use a more permissive
curvature-aware continuation than the global endpoint matcher.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from .curvature_gap_fill import build_curvature_gap, endpoint_state


def _dist(a, b) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _wrap(a: float) -> float:
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def _heading(a, b) -> float:
    return math.atan2(float(b[1]) - float(a[1]), float(b[0]) - float(a[0]))


def _angle_diff_deg(a: float, b: float) -> float:
    return abs(math.degrees(_wrap(a - b)))


def find_neighbor_continuity_support(
    topology: dict[str, Any],
    *,
    maximum_reference_station_gap_m: float = 16.0,
) -> dict[frozenset[str], list[dict[str, Any]]]:
    """Find A->B neighbor transitions along the same reference track/side."""
    support: dict[frozenset[str], list[dict[str, Any]]] = defaultdict(list)
    for reference_id, rows in (topology.get("samples_by_track") or {}).items():
        for side in ("left", "right"):
            previous_id = None
            previous_station = None
            for row in rows:
                candidate = row.get(side) or {}
                current_id = str(candidate.get("track_id")) if candidate.get("track_id") is not None else None
                station = float(row.get("station_m", 0.0))
                if current_id is None:
                    continue
                if previous_id and current_id != previous_id and previous_station is not None:
                    station_gap = abs(station - previous_station)
                    if station_gap <= maximum_reference_station_gap_m:
                        key = frozenset((previous_id, current_id))
                        support[key].append({
                            "reference_track_id": str(reference_id),
                            "side": side,
                            "previous_neighbor_track_id": previous_id,
                            "next_neighbor_track_id": current_id,
                            "reference_station_gap_m": round(station_gap, 3),
                            "reference_station_m": round(station, 3),
                        })
                previous_id = current_id
                previous_station = station
    return dict(support)


def _oriented_line(line: list[list[float]], entry_side: str) -> list[list[float]]:
    pts = [[float(p[0]), float(p[1])] for p in line if len(p) >= 2]
    return pts if entry_side == "start" else list(reversed(pts))


def _other_side(side: str) -> str:
    return "end" if side == "start" else "start"


def _append_points(target: list[list[float]], points: list[list[float]]) -> None:
    for p in points:
        q = [float(p[0]), float(p[1])]
        if not target or _dist(target[-1], q) > 1e-4:
            target.append(q)


def _best_endpoint_bridge(a: dict[str, Any], b: dict[str, Any], *, maximum_gap_m: float) -> dict[str, Any] | None:
    best = None
    width_a = float(a.get("median_width_m", 3.5))
    width_b = float(b.get("median_width_m", 3.5))
    if abs(width_a - width_b) > 1.2:
        return None
    for side_a in ("start", "end"):
        for side_b in ("start", "end"):
            line_a = a.get("centerline_lcs_m") or []
            line_b = b.get("centerline_lcs_m") or []
            sa = endpoint_state(line_a, side_a)
            sb = endpoint_state(line_b, side_b)
            if sa is None or sb is None:
                continue
            pa = [sa["x"], sa["y"]]
            pb = [sb["x"], sb["y"]]
            gap = _dist(pa, pb)
            if gap <= 1e-4 or gap > maximum_gap_m:
                continue
            chord_h = _heading(pa, pb)
            source_chord = _angle_diff_deg(float(sa["heading"]), chord_h)
            destination_chord = _angle_diff_deg(float(sb["heading"]), _wrap(chord_h + math.pi))
            if source_chord > 80.0 or destination_chord > 80.0:
                continue
            fill = build_curvature_gap(
                line_a, side_a, line_b, side_b,
                width_a_m=width_a, width_b_m=width_b,
            )
            if fill is None:
                continue
            arc_ratio = float(fill["arc_to_chord_ratio"])
            bridge_curvature = float(fill["maximum_abs_bridge_curvature_per_m"])
            endpoint_k = max(abs(float(sa["curvature"])), abs(float(sb["curvature"])))
            if arc_ratio > 1.50 or bridge_curvature > max(0.20, endpoint_k + 0.14):
                continue
            score = gap + 0.02 * (source_chord + destination_chord) + 8.0 * max(0.0, arc_ratio - 1.0) + 4.0 * bridge_curvature
            record = {
                "endpoint_a": side_a,
                "endpoint_b": side_b,
                "endpoint_gap_m": round(gap, 3),
                "source_to_chord_deg": round(source_chord, 3),
                "destination_to_chord_deg": round(destination_chord, 3),
                "bridge_arc_to_chord_ratio": round(arc_ratio, 4),
                "bridge_max_abs_curvature_per_m": round(bridge_curvature, 5),
                "score": round(score, 4),
                "fill": fill,
            }
            if best is None or record["score"] < best["score"]:
                best = record
    return best


def stitch_topology_supported_neighbors(
    tracks: list[dict[str, Any]],
    topology: dict[str, Any],
    *,
    maximum_gap_m: float = 15.0,
    maximum_reference_station_gap_m: float = 16.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Merge topology-supported fragmented neighbors and add smooth gap pieces."""
    support = find_neighbor_continuity_support(
        topology, maximum_reference_station_gap_m=maximum_reference_station_gap_m
    )
    by_id = {str(t.get("track_id")): t for t in tracks}
    candidates = []
    for key, evidence in support.items():
        if len(key) != 2:
            continue
        a_id, b_id = sorted(key)
        a, b = by_id.get(a_id), by_id.get(b_id)
        if not a or not b:
            continue
        bridge = _best_endpoint_bridge(a, b, maximum_gap_m=maximum_gap_m)
        if bridge:
            candidates.append({"track_a_id": a_id, "track_b_id": b_id, "support": evidence, **bridge})

    # Greedy low-score pair selection; one track may only be consumed once here.
    used: set[str] = set()
    accepted = []
    for c in sorted(candidates, key=lambda x: (x["score"], x["track_a_id"], x["track_b_id"])):
        if c["track_a_id"] in used or c["track_b_id"] in used:
            continue
        used.update((c["track_a_id"], c["track_b_id"]))
        accepted.append(c)

    merged = []
    consumed: set[str] = set()
    for c in accepted:
        a, b = by_id[c["track_a_id"]], by_id[c["track_b_id"]]
        side_a, side_b = c["endpoint_a"], c["endpoint_b"]
        # Orient A so selected endpoint is exit; B so selected endpoint is entry.
        entry_a = _other_side(side_a)
        entry_b = side_b
        center_a = _oriented_line(a.get("centerline_lcs_m") or [], entry_a)
        center_b = _oriented_line(b.get("centerline_lcs_m") or [], entry_b)
        members_a = list(a.get("member_lane_ids") or [])
        pieces_a = list(a.get("pieces") or [])
        if entry_a == "end":
            members_a.reverse(); pieces_a.reverse()
        members_b = list(b.get("member_lane_ids") or [])
        pieces_b = list(b.get("pieces") or [])
        if entry_b == "end":
            members_b.reverse(); pieces_b.reverse()

        fill = c["fill"]
        gap_piece = {
            "kind": "topology_supported_curvature_stitch",
            "source_track_id": str(a.get("track_id")),
            "destination_track_id": str(b.get("track_id")),
            "centerline_lcs_m": fill["centerline_lcs_m"],
            "left_boundary_lcs_m": fill["left_boundary_lcs_m"],
            "right_boundary_lcs_m": fill["right_boundary_lcs_m"],
            "polygon_lcs_m": fill["polygon_lcs_m"],
            "connection_evidence": {k:v for k,v in c.items() if k != "fill"},
        }
        center = []
        _append_points(center, center_a)
        _append_points(center, fill["centerline_lcs_m"])
        _append_points(center, center_b)
        source_ids = list(dict.fromkeys(
            [str(x) for x in (a.get("merged_from_track_ids") or [a.get("track_id")])]
            + [str(x) for x in (b.get("merged_from_track_ids") or [b.get("track_id")])]
        ))
        width = (float(a.get("median_width_m", 3.5)) + float(b.get("median_width_m", 3.5))) / 2.0
        new_id = source_ids[0]
        merged.append({
            "track_id": new_id,
            "logical_lane_id": new_id,
            "member_lane_ids": members_a + members_b,
            "centerline_lcs_m": center,
            "polygon_lcs_m": [],
            "median_width_m": round(width, 3),
            "pieces": pieces_a + [gap_piece] + pieces_b,
            "piece_count": len(pieces_a) + len(pieces_b) + 1,
            "observed_segment_count": int(a.get("observed_segment_count", 0)) + int(b.get("observed_segment_count", 0)),
            "inferred_gap_count": int(a.get("inferred_gap_count", 0)) + int(b.get("inferred_gap_count", 0)) + 1,
            "canonical_stitch_count": int(a.get("canonical_stitch_count", 0)) + int(b.get("canonical_stitch_count", 0)),
            "topology_supported_stitch_count": 1,
            "merged_from_track_ids": source_ids,
            "source": "topology_supported_stitched_track",
        })
        consumed.update((str(a.get("track_id")), str(b.get("track_id"))))

    merged.extend(t for t in tracks if str(t.get("track_id")) not in consumed)
    debug = []
    accepted_pairs = {(c["track_a_id"], c["track_b_id"]) for c in accepted}
    for c in candidates:
        debug.append({
            **{k:v for k,v in c.items() if k != "fill"},
            "accepted": (c["track_a_id"], c["track_b_id"]) in accepted_pairs,
            "rejection_reason": None if (c["track_a_id"], c["track_b_id"]) in accepted_pairs else "competing_topology_supported_pair",
        })
    return merged, debug
