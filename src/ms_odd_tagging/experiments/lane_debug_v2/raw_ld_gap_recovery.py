"""Anchored raw-LD bridge recovery for lane-debug v2.

Raw LD is never allowed to create a standalone lane. A bridge is considered only
between two existing canonical continuous-track endpoints, and only when the
terminal canonical lane fragments reference the same physical left and right raw
LD boundaries. This intentionally prefers no bridge over an invented wedge.
"""
from __future__ import annotations

import math
from typing import Any

from .lane_geometry import wrap_angle


def _dist(a, b) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _heading(a, b) -> float:
    return math.atan2(float(b[1]) - float(a[1]), float(b[0]) - float(a[0]))


def _heading_diff_deg(a: float, b: float) -> float:
    return abs(math.degrees(wrap_angle(a - b)))


def _raw_boundary_lookup(recording: dict[str, Any]) -> dict[str, list[list[float]]]:
    store = recording.get("ld_feature_store") or {}
    points = {
        str(p.get("point_id")): p.get("position_lcs_m", [])[:2]
        for p in store.get("points", [])
        if len(p.get("position_lcs_m") or []) >= 2
    }
    out: dict[str, list[list[float]]] = {}
    for collection, key in (("lane_lines", "line_id"), ("road_boundaries", "road_boundary_id")):
        for feature in store.get(collection, []):
            ids = list(feature.get("point_ids") or []) or [e.get("point_id") for e in feature.get("elements") or []]
            pts = [points[str(pid)] for pid in ids if str(pid) in points]
            if len(pts) >= 2:
                out[str(feature.get(key))] = [[float(p[0]), float(p[1])] for p in pts]
    return out


def _nearest_index(line: list[list[float]], point: list[float]) -> int:
    return min(range(len(line)), key=lambda i: _dist(line[i], point))


def _subline_between(line: list[list[float]], start: list[float], end: list[float]) -> list[list[float]]:
    i = _nearest_index(line, start)
    j = _nearest_index(line, end)
    pts = line[i:j + 1] if i <= j else list(reversed(line[j:i + 1]))
    out = [[float(start[0]), float(start[1])]]
    for p in pts:
        if _dist(out[-1], p) > 0.15:
            out.append(p)
    if _dist(out[-1], end) > 0.15:
        out.append([float(end[0]), float(end[1])])
    return out


def _terminal_lane(track: dict[str, Any], lane_by_id: dict[str, dict[str, Any]], tail: bool) -> dict[str, Any] | None:
    members = list(track.get("member_lane_ids") or [])
    if not members:
        return None
    return lane_by_id.get(str(members[-1] if tail else members[0]))


def _boundary_end(lane: dict[str, Any], key: str, tail: bool) -> list[float] | None:
    pts = lane.get(key) or []
    if not pts:
        return None
    p = pts[-1] if tail else pts[0]
    return [float(p[0]), float(p[1])]


def build_raw_ld_gap_tracks(
    recording: dict[str, Any],
    lane_geometry: list[dict[str, Any]],
    canonical_tracks: list[dict[str, Any]] | None = None,
    *,
    maximum_endpoint_gap_m: float = 15.0,
    minimum_endpoint_gap_m: float = 1.0,
    maximum_heading_difference_deg: float = 12.0,
    maximum_width_difference_m: float = 0.8,
    minimum_width_m: float = 2.2,
    maximum_width_m: float = 6.5,
    **_: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build only raw-LD bridges anchored by canonical track endpoints."""
    tracks = list(canonical_tracks or [])
    lane_by_id = {str(l.get("lane_id")): l for l in lane_geometry}
    raw = _raw_boundary_lookup(recording)
    bridges: list[dict[str, Any]] = []
    debug: list[dict[str, Any]] = []

    for source in tracks:
        source_line = source.get("centerline_lcs_m") or []
        if len(source_line) < 2:
            continue
        source_lane = _terminal_lane(source, lane_by_id, True)
        if not source_lane:
            continue
        source_end = source_line[-1]
        source_h = _heading(source_line[-2], source_line[-1])
        for dest in tracks:
            if dest is source:
                continue
            dest_line = dest.get("centerline_lcs_m") or []
            if len(dest_line) < 2:
                continue
            dest_lane = _terminal_lane(dest, lane_by_id, False)
            if not dest_lane:
                continue
            dest_start = dest_line[0]
            gap = _dist(source_end, dest_start)
            if not (minimum_endpoint_gap_m <= gap <= maximum_endpoint_gap_m):
                continue
            dest_h = _heading(dest_line[0], dest_line[1])
            hdiff = _heading_diff_deg(source_h, dest_h)
            if hdiff > maximum_heading_difference_deg:
                debug.append({"source_track_id": source.get("track_id"), "destination_track_id": dest.get("track_id"), "accepted": False, "reason": "endpoint_heading_difference", "gap_m": round(gap, 3), "heading_difference_deg": round(hdiff, 2)})
                continue

            s_left_id, s_right_id = source_lane.get("left_edge_id"), source_lane.get("right_edge_id")
            d_left_id, d_right_id = dest_lane.get("left_edge_id"), dest_lane.get("right_edge_id")
            if None in (s_left_id, s_right_id, d_left_id, d_right_id) or str(s_left_id) != str(d_left_id) or str(s_right_id) != str(d_right_id):
                debug.append({"source_track_id": source.get("track_id"), "destination_track_id": dest.get("track_id"), "accepted": False, "reason": "not_same_physical_boundary_pair", "gap_m": round(gap, 3)})
                continue
            if str(s_left_id) not in raw or str(s_right_id) not in raw:
                debug.append({"source_track_id": source.get("track_id"), "destination_track_id": dest.get("track_id"), "accepted": False, "reason": "referenced_raw_boundaries_unavailable"})
                continue

            sl = _boundary_end(source_lane, "left_boundary_lcs_m", True)
            sr = _boundary_end(source_lane, "right_boundary_lcs_m", True)
            dl = _boundary_end(dest_lane, "left_boundary_lcs_m", False)
            dr = _boundary_end(dest_lane, "right_boundary_lcs_m", False)
            if not all((sl, sr, dl, dr)):
                continue
            source_width = _dist(sl, sr)
            dest_width = _dist(dl, dr)
            if not (minimum_width_m <= source_width <= maximum_width_m and minimum_width_m <= dest_width <= maximum_width_m) or abs(source_width - dest_width) > maximum_width_difference_m:
                debug.append({"source_track_id": source.get("track_id"), "destination_track_id": dest.get("track_id"), "accepted": False, "reason": "endpoint_width_mismatch", "source_width_m": round(source_width, 3), "destination_width_m": round(dest_width, 3)})
                continue

            left = _subline_between(raw[str(s_left_id)], sl, dl)
            right = _subline_between(raw[str(s_right_id)], sr, dr)
            n = min(len(left), len(right))
            if n < 2:
                continue
            # Resample by index only after both sides were physically anchored.
            left = [left[round(i * (len(left) - 1) / (n - 1))] for i in range(n)]
            right = [right[round(i * (len(right) - 1) / (n - 1))] for i in range(n)]
            widths = [_dist(l, r) for l, r in zip(left, right)]
            if any(w < minimum_width_m or w > maximum_width_m for w in widths) or max(widths) - min(widths) > maximum_width_difference_m:
                debug.append({"source_track_id": source.get("track_id"), "destination_track_id": dest.get("track_id"), "accepted": False, "reason": "bridge_width_not_stable", "width_range_m": round(max(widths) - min(widths), 3)})
                continue
            center = [[(l[0] + r[0]) / 2.0, (l[1] + r[1]) / 2.0] for l, r in zip(left, right)]
            polygon = left + list(reversed(right))
            track_id = f"anchored_ld_bridge_{len(bridges) + 1:04d}"
            bridge = {
                "track_id": track_id,
                "logical_lane_id": track_id,
                "member_lane_ids": [],
                "centerline_lcs_m": center,
                "polygon_lcs_m": polygon,
                "median_width_m": round(sorted(widths)[len(widths) // 2], 3),
                "pieces": [{"kind": "anchored_ld_bridge", "polygon_lcs_m": polygon, "centerline_lcs_m": center, "source_track_id": source.get("track_id"), "destination_track_id": dest.get("track_id")}],
                "piece_count": 1,
                "observed_segment_count": 0,
                "inferred_gap_count": 1,
                "source": "anchored_ld_bridge",
                "source_track_id": source.get("track_id"),
                "destination_track_id": dest.get("track_id"),
                "left_boundary_id": str(s_left_id),
                "right_boundary_id": str(s_right_id),
                "left_boundary_lcs_m": left,
                "right_boundary_lcs_m": right,
                "endpoint_gap_m": round(gap, 3),
            }
            bridges.append(bridge)
            debug.append({"track_id": track_id, "source_track_id": source.get("track_id"), "destination_track_id": dest.get("track_id"), "accepted": True, "reason": "same_raw_boundary_pair_between_canonical_endpoints", "gap_m": round(gap, 3), "heading_difference_deg": round(hdiff, 2)})
    return bridges, debug
