"""Merge accepted anchored LD bridges into canonical continuous tracks.

A bridge is connectivity evidence, not a standalone lane identity. Only simple
one-out/one-in bridge chains are merged; ambiguous forks stay unmerged.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def _append_points(target: list[list[float]], points: list[list[float]]) -> None:
    for p in points:
        q = [float(p[0]), float(p[1])]
        if not target or abs(target[-1][0] - q[0]) > 1e-4 or abs(target[-1][1] - q[1]) > 1e-4:
            target.append(q)


def merge_tracks_with_anchored_bridges(
    canonical_tracks: list[dict[str, Any]],
    bridges: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str], list[dict[str, Any]]]:
    by_id = {str(t.get("track_id")): t for t in canonical_tracks}
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for bridge in bridges:
        src = str(bridge.get("source_track_id"))
        dst = str(bridge.get("destination_track_id"))
        if src in by_id and dst in by_id:
            outgoing[src].append(bridge)
            incoming[dst].append(bridge)

    accepted: dict[str, dict[str, Any]] = {}
    debug = []
    for src, items in outgoing.items():
        if len(items) != 1:
            for b in items:
                debug.append({"bridge_track_id": b.get("track_id"), "accepted": False, "reason": "ambiguous_multiple_outgoing_bridges"})
            continue
        bridge = items[0]
        dst = str(bridge.get("destination_track_id"))
        if len(incoming.get(dst, [])) != 1:
            debug.append({"bridge_track_id": bridge.get("track_id"), "accepted": False, "reason": "ambiguous_multiple_incoming_bridges"})
            continue
        accepted[src] = bridge

    predecessors = {str(b.get("destination_track_id")): src for src, b in accepted.items()}
    visited: set[str] = set()
    merged: list[dict[str, Any]] = []
    old_to_new: dict[str, str] = {}
    starts = [tid for tid in by_id if tid not in predecessors] + [tid for tid in by_id if tid in predecessors]

    for start in starts:
        if start in visited:
            continue
        members: list[str] = []
        pieces: list[dict[str, Any]] = []
        centerline: list[list[float]] = []
        widths: list[float] = []
        source_ids: list[str] = []
        current = start
        bridge_count = 0
        while current in by_id and current not in visited:
            visited.add(current)
            track = by_id[current]
            source_ids.append(current)
            members.extend(str(x) for x in track.get("member_lane_ids", []))
            pieces.extend(track.get("pieces") or [])
            _append_points(centerline, track.get("centerline_lcs_m") or [])
            if track.get("median_width_m") is not None:
                widths.append(float(track["median_width_m"]))
            bridge = accepted.get(current)
            if not bridge:
                break
            bridge_piece = (bridge.get("pieces") or [{}])[0]
            pieces.append({**bridge_piece, "kind": "anchored_ld_bridge", "bridge_track_id": bridge.get("track_id")})
            _append_points(centerline, bridge.get("centerline_lcs_m") or [])
            bridge_count += 1
            current = str(bridge.get("destination_track_id"))

        new_id = source_ids[0]
        width = sorted(widths)[len(widths)//2] if widths else 3.5
        merged_track = {
            "track_id": new_id,
            "logical_lane_id": new_id,
            "member_lane_ids": members,
            "centerline_lcs_m": centerline,
            "polygon_lcs_m": [],
            "median_width_m": round(width, 3),
            "pieces": pieces,
            "piece_count": len(pieces),
            "observed_segment_count": sum(1 for p in pieces if p.get("kind") in {"observed_ld", "recovered_full_edge"}),
            "inferred_gap_count": sum(1 for p in pieces if p.get("kind") in {"inferred_gap", "anchored_ld_bridge"}),
            "anchored_bridge_count": bridge_count,
            "source": "canonical_with_anchored_bridge" if bridge_count else "canonical_continuous_track",
            "merged_source_track_ids": source_ids,
        }
        merged.append(merged_track)
        for old in source_ids:
            old_to_new[old] = new_id
        debug.extend({"bridge_track_id": (accepted[src].get("track_id") if src in accepted else None), "accepted": True, "merged_track_id": new_id, "source_track_id": src, "destination_track_id": accepted[src].get("destination_track_id")} for src in source_ids if src in accepted)

    return merged, old_to_new, debug
