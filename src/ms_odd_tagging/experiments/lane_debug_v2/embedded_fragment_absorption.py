"""Absorb standalone observed lane fragments that duplicate an inferred gap.

This stage is intentionally conservative. It runs after continuous-track
construction and before final lane ordering. A standalone observed fragment is
absorbed only when it unambiguously occupies an existing inferred-gap piece of
one host track. The host track ID is preserved.
"""
from __future__ import annotations

import copy
import math
from typing import Any


def _dist(a: list[float], b: list[float]) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _heading(a: list[float], b: list[float]) -> float:
    return math.atan2(float(b[1]) - float(a[1]), float(b[0]) - float(a[0]))


def _wrap(v: float) -> float:
    while v > math.pi:
        v -= 2.0 * math.pi
    while v < -math.pi:
        v += 2.0 * math.pi
    return v


def _polyline_length(line: list[list[float]]) -> float:
    return sum(_dist(a, b) for a, b in zip(line, line[1:]))


def _project_point_to_segment(p: list[float], a: list[float], b: list[float]) -> float:
    ax, ay, bx, by = float(a[0]), float(a[1]), float(b[0]), float(b[1])
    dx, dy = bx - ax, by - ay
    den = dx * dx + dy * dy
    if den <= 1e-12:
        return _dist(p, a)
    t = max(0.0, min(1.0, ((float(p[0]) - ax) * dx + (float(p[1]) - ay) * dy) / den))
    q = [ax + t * dx, ay + t * dy]
    return _dist(p, q)


def _polyline_distance(p: list[float], line: list[list[float]]) -> float:
    if len(line) < 2:
        return math.inf
    return min(_project_point_to_segment(p, a, b) for a, b in zip(line, line[1:]))


def _max_centerline_deviation(fragment: list[list[float]], gap: list[list[float]]) -> float:
    if len(fragment) < 2 or len(gap) < 2:
        return math.inf
    sample = fragment[:: max(1, len(fragment) // 12)]
    if sample[-1] != fragment[-1]:
        sample = [*sample, fragment[-1]]
    return max(_polyline_distance(p, gap) for p in sample)


def _median_width(lane: dict[str, Any]) -> float | None:
    left = lane.get("left_boundary_lcs_m") or []
    right = lane.get("right_boundary_lcs_m") or []
    if len(left) < 2 or len(right) < 2:
        return None
    n = min(len(left), len(right), 16)
    values = []
    for i in range(n):
        li = round(i * (len(left) - 1) / max(1, n - 1))
        ri = round(i * (len(right) - 1) / max(1, n - 1))
        w = _dist(left[li], right[ri])
        if 1.5 <= w <= 7.0:
            values.append(w)
    if not values:
        return None
    values.sort()
    return values[len(values) // 2]


def _boundary_ids(lane: dict[str, Any]) -> set[str]:
    values = set()
    for key in ("left_edge_id", "right_edge_id"):
        value = lane.get(key)
        if value is not None:
            values.add(str(value))
    return values


def _append_points(target: list[list[float]], points: list[list[float]]) -> None:
    for p in points:
        if len(p) < 2:
            continue
        q = [float(p[0]), float(p[1])]
        if not target or _dist(target[-1], q) > 1e-4:
            target.append(q)


def _rebuild_track(track: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(track)
    merged: list[list[float]] = []
    for piece in out.get("pieces") or []:
        _append_points(merged, piece.get("centerline_lcs_m") or [])
    out["centerline_lcs_m"] = merged
    out["piece_count"] = len(out.get("pieces") or [])
    out["observed_segment_count"] = sum(
        1 for p in out.get("pieces") or [] if p.get("kind") in {"observed_ld", "recovered_full_edge"}
    )
    out["inferred_gap_count"] = sum(1 for p in out.get("pieces") or [] if p.get("kind") == "inferred_gap")
    return out


def absorb_embedded_observed_fragments(
    tracks: list[dict[str, Any]],
    lane_geometry: list[dict[str, Any]],
    *,
    maximum_endpoint_error_m: float = 0.35,
    maximum_heading_difference_deg: float = 12.0,
    maximum_centerline_deviation_m: float = 0.5,
    maximum_width_difference_m: float = 0.75,
    require_boundary_continuity: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Replace host inferred gaps with matching standalone observed fragments."""
    lane_by_id = {str(l.get("lane_id")): l for l in lane_geometry}
    mutable = [copy.deepcopy(t) for t in tracks]
    track_by_id = {str(t.get("track_id")): t for t in mutable}
    member_owner = {
        str(lane_id): str(track.get("track_id"))
        for track in mutable
        for lane_id in track.get("member_lane_ids", [])
    }
    debug: list[dict[str, Any]] = []
    planned: list[dict[str, Any]] = []

    # Only standalone observed fragments are candidates. Multi-piece tracks are
    # intentionally not absorbed by this conservative repair stage.
    donors = []
    for track in mutable:
        pieces = track.get("pieces") or []
        observed = [p for p in pieces if p.get("kind") in {"observed_ld", "recovered_full_edge"} and p.get("lane_id")]
        inferred = [p for p in pieces if p.get("kind") == "inferred_gap"]
        if len(track.get("member_lane_ids") or []) == 1 and len(observed) == 1 and not inferred:
            donors.append((track, observed[0]))

    for donor_track, donor_piece in donors:
        lane_id = str(donor_piece.get("lane_id"))
        lane = lane_by_id.get(lane_id) or {}
        fragment = donor_piece.get("centerline_lcs_m") or lane.get("centerline_lcs_m") or []
        if len(fragment) < 2:
            continue
        fragment_heading = _heading(fragment[0], fragment[-1])
        fragment_width = _median_width(lane)
        fragment_boundaries = _boundary_ids(lane)
        matches = []

        for host in mutable:
            host_id = str(host.get("track_id"))
            if host_id == str(donor_track.get("track_id")):
                continue
            members = [str(x) for x in host.get("member_lane_ids", [])]
            for index, piece in enumerate(host.get("pieces") or []):
                if piece.get("kind") != "inferred_gap":
                    continue
                gap = piece.get("centerline_lcs_m") or []
                if len(gap) < 2:
                    continue
                source_lane_id = str(piece.get("source_lane_id")) if piece.get("source_lane_id") is not None else None
                destination_lane_id = str(piece.get("destination_lane_id")) if piece.get("destination_lane_id") is not None else None
                source_lane = lane_by_id.get(source_lane_id or "") or {}
                destination_lane = lane_by_id.get(destination_lane_id or "") or {}

                endpoint_error = _dist(fragment[0], gap[0]) + _dist(fragment[-1], gap[-1])
                reverse_error = _dist(fragment[-1], gap[0]) + _dist(fragment[0], gap[-1])
                same_direction = endpoint_error <= reverse_error
                chosen_endpoint_error = endpoint_error if same_direction else reverse_error
                oriented_fragment = fragment if same_direction else list(reversed(fragment))
                heading_diff = abs(math.degrees(_wrap(_heading(oriented_fragment[0], oriented_fragment[-1]) - _heading(gap[0], gap[-1]))))
                deviation = _max_centerline_deviation(oriented_fragment, gap)

                host_width = host.get("median_width_m")
                width_difference = None
                if fragment_width is not None and isinstance(host_width, (int, float)):
                    width_difference = abs(float(fragment_width) - float(host_width))

                source_boundaries = _boundary_ids(source_lane)
                destination_boundaries = _boundary_ids(destination_lane)
                boundary_continuity = bool(
                    fragment_boundaries
                    and source_boundaries
                    and destination_boundaries
                    and fragment_boundaries.intersection(source_boundaries)
                    and fragment_boundaries.intersection(destination_boundaries)
                )

                reasons = []
                if not same_direction:
                    reasons.append("reverse_direction")
                if chosen_endpoint_error > maximum_endpoint_error_m * 2.0:
                    reasons.append("endpoint_mismatch")
                if heading_diff > maximum_heading_difference_deg:
                    reasons.append("heading_difference")
                if deviation > maximum_centerline_deviation_m:
                    reasons.append("centerline_deviation")
                if width_difference is not None and width_difference > maximum_width_difference_m:
                    reasons.append("width_difference")
                if require_boundary_continuity and not boundary_continuity:
                    reasons.append("boundary_discontinuity")

                record = {
                    "donor_track_id": str(donor_track.get("track_id")),
                    "fragment_lane_id": lane_id,
                    "host_track_id": host_id,
                    "host_gap_piece_index": index,
                    "source_lane_id": source_lane_id,
                    "destination_lane_id": destination_lane_id,
                    "endpoint_error_sum_m": round(chosen_endpoint_error, 4),
                    "heading_difference_deg": round(heading_diff, 3),
                    "maximum_centerline_deviation_m": round(deviation, 4),
                    "width_difference_m": None if width_difference is None else round(width_difference, 4),
                    "shared_boundary_ids": sorted(fragment_boundaries.intersection(source_boundaries).intersection(destination_boundaries)),
                    "boundary_continuity": boundary_continuity,
                    "accepted_geometrically": not reasons,
                    "rejection_reasons": reasons,
                }
                debug.append(record)
                if not reasons:
                    score = chosen_endpoint_error + deviation * 2.0 + heading_diff * 0.02 + (width_difference or 0.0)
                    matches.append((score, record, oriented_fragment))

        matches.sort(key=lambda item: (item[0], item[1]["host_track_id"], item[1]["host_gap_piece_index"]))
        if len(matches) != 1:
            if matches:
                for _, record, _ in matches:
                    record["accepted_geometrically"] = False
                    record["rejection_reasons"] = [*record["rejection_reasons"], "ambiguous_multiple_host_gaps"]
            continue
        _, record, oriented_fragment = matches[0]
        planned.append({**record, "oriented_fragment": oriented_fragment})

    # A host gap may absorb at most one donor. Resolve any collision by rejecting
    # all colliding plans rather than choosing by a tiny score difference.
    gap_to_plans: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for plan in planned:
        gap_to_plans.setdefault((plan["host_track_id"], plan["host_gap_piece_index"]), []).append(plan)

    donor_tracks_to_remove: set[str] = set()
    for key, plans in gap_to_plans.items():
        if len(plans) != 1:
            for plan in plans:
                matching_debug = next((d for d in debug if d["donor_track_id"] == plan["donor_track_id"] and d["host_track_id"] == plan["host_track_id"] and d["host_gap_piece_index"] == plan["host_gap_piece_index"]), None)
                if matching_debug is not None:
                    matching_debug["accepted_geometrically"] = False
                    matching_debug["rejection_reasons"] = [*matching_debug["rejection_reasons"], "ambiguous_multiple_fragments_for_gap"]
            continue

        plan = plans[0]
        host = track_by_id.get(plan["host_track_id"])
        donor = track_by_id.get(plan["donor_track_id"])
        if host is None or donor is None:
            continue
        lane_id = plan["fragment_lane_id"]
        lane = lane_by_id.get(lane_id) or {}
        pieces = host.get("pieces") or []
        gap_piece = pieces[plan["host_gap_piece_index"]]
        replacement = {
            "kind": "observed_ld",
            "lane_id": lane_id,
            "centerline_lcs_m": plan["oriented_fragment"],
            "polygon_lcs_m": lane.get("polygon_lcs_m") or donor.get("polygon_lcs_m") or [],
            "recovery_method": lane.get("recovery_method"),
            "absorbed_into_host_track": True,
            "replaced_inferred_gap": {
                "source_lane_id": gap_piece.get("source_lane_id"),
                "destination_lane_id": gap_piece.get("destination_lane_id"),
            },
        }
        pieces[plan["host_gap_piece_index"]] = replacement
        host["pieces"] = pieces
        if lane_id not in [str(x) for x in host.get("member_lane_ids", [])]:
            host["member_lane_ids"] = [*host.get("member_lane_ids", []), lane_id]
        donor_tracks_to_remove.add(plan["donor_track_id"])
        member_owner[lane_id] = plan["host_track_id"]
        matching_debug = next((d for d in debug if d["donor_track_id"] == plan["donor_track_id"] and d["host_track_id"] == plan["host_track_id"] and d["host_gap_piece_index"] == plan["host_gap_piece_index"]), None)
        if matching_debug is not None:
            matching_debug["accepted"] = True
            matching_debug["action"] = "replace_inferred_gap_with_observed_fragment"
            matching_debug["preserved_host_track_id"] = plan["host_track_id"]

    output = []
    for track in mutable:
        if str(track.get("track_id")) in donor_tracks_to_remove:
            continue
        output.append(_rebuild_track(track))

    return output, debug
