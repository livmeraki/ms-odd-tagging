"""Conservative raw-LD gap recovery for the static lane network.

Canonical reconstructed lane tracks are the source of truth. Raw lane-lines and
road-boundaries may add a supplemental lane only inside regions not already
covered by canonical lane polygons. Candidate boundary pairs are discovered as
local nearest lateral neighbors, then clipped to a contiguous uncovered run and
rejected for unstable width, crossing/self-intersection, or wedge-like geometry.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from .lane_geometry import point_in_polygon, wrap_angle


def _dist(a, b) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _cum(line: list[list[float]]) -> list[float]:
    out = [0.0]
    for a, b in zip(line, line[1:]):
        out.append(out[-1] + _dist(a, b))
    return out


def _sample(line: list[list[float]], spacing_m: float) -> list[tuple[float, list[float], float]]:
    if len(line) < 2:
        return []
    cumulative = _cum(line)
    total = cumulative[-1]
    if total < max(2.0, spacing_m):
        return []
    count = max(2, int(math.floor(total / max(spacing_m, 0.5))) + 1)
    out = []
    seg = 0
    for i in range(count):
        station = total if i == count - 1 else total * i / (count - 1)
        while seg + 2 < len(cumulative) and cumulative[seg + 1] < station:
            seg += 1
        a, b = line[seg], line[seg + 1]
        span = cumulative[seg + 1] - cumulative[seg]
        t = 0.0 if span <= 1e-9 else (station - cumulative[seg]) / span
        p = [
            float(a[0]) + t * (float(b[0]) - float(a[0])),
            float(a[1]) + t * (float(b[1]) - float(a[1])),
        ]
        heading = math.atan2(float(b[1]) - float(a[1]), float(b[0]) - float(a[0]))
        out.append((station, p, heading))
    return out


def _project(point: list[float], line: list[list[float]]) -> tuple[float, list[float], float] | None:
    best = None
    for a, b in zip(line, line[1:]):
        ax, ay, bx, by = float(a[0]), float(a[1]), float(b[0]), float(b[1])
        dx, dy = bx - ax, by - ay
        den = dx * dx + dy * dy
        if den <= 1e-12:
            continue
        t = max(0.0, min(1.0, ((float(point[0]) - ax) * dx + (float(point[1]) - ay) * dy) / den))
        q = [ax + t * dx, ay + t * dy]
        d = _dist(point, q)
        h = math.atan2(dy, dx)
        if best is None or d < best[0]:
            best = (d, q, h)
    return best


def _orientation_diff_deg(a: float, b: float) -> float:
    diff = abs(math.degrees(wrap_angle(a - b)))
    return min(diff, abs(180.0 - diff))


def _raw_boundaries(recording: dict[str, Any]) -> list[dict[str, Any]]:
    store = recording.get("ld_feature_store") or {}
    lookup = {
        str(p.get("point_id")): p.get("position_lcs_m", [])[:2]
        for p in store.get("points", [])
        if len(p.get("position_lcs_m") or []) >= 2
    }
    out = []
    for collection, key, kind in (
        ("lane_lines", "line_id", "lane_line"),
        ("road_boundaries", "road_boundary_id", "road_boundary"),
    ):
        for feature in store.get(collection, []):
            ids = list(feature.get("point_ids") or []) or [e.get("point_id") for e in feature.get("elements") or []]
            pts = [lookup[str(pid)] for pid in ids if str(pid) in lookup]
            if len(pts) >= 2:
                out.append({"boundary_id": str(feature.get(key)), "kind": kind, "points": pts})
    return out


def _canonical_polygons(lane_geometry: list[dict[str, Any]]) -> list[list[list[float]]]:
    return [
        lane.get("polygon_lcs_m") or []
        for lane in lane_geometry
        if lane.get("assignment_valid") and len(lane.get("polygon_lcs_m") or []) >= 3
    ]


def _covered(point: list[float], polygons: list[list[list[float]]]) -> bool:
    p = (float(point[0]), float(point[1]))
    return any(point_in_polygon(p, polygon) for polygon in polygons)


def _segments_intersect(a, b, c, d) -> bool:
    def orient(p, q, r):
        return (float(q[0]) - float(p[0])) * (float(r[1]) - float(p[1])) - (float(q[1]) - float(p[1])) * (float(r[0]) - float(p[0]))
    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    eps = 1e-8
    return (o1 * o2 < -eps) and (o3 * o4 < -eps)


def _polyline_crosses(a: list[list[float]], b: list[list[float]]) -> bool:
    return any(_segments_intersect(a0, a1, b0, b1) for a0, a1 in zip(a, a[1:]) for b0, b1 in zip(b, b[1:]))


def _polygon_self_intersects(poly: list[list[float]]) -> bool:
    if len(poly) < 4:
        return True
    closed = poly + [poly[0]] if poly[0] != poly[-1] else poly
    segments = list(zip(closed, closed[1:]))
    n = len(segments)
    for i, (a, b) in enumerate(segments):
        for j in range(i + 1, n):
            if abs(i - j) <= 1 or (i == 0 and j == n - 1):
                continue
            c, d = segments[j]
            if _segments_intersect(a, b, c, d):
                return True
    return False


def _longest_contiguous(records: list[dict[str, Any]], maximum_gap_m: float) -> list[dict[str, Any]]:
    if not records:
        return []
    records = sorted(records, key=lambda r: r["station_m"])
    groups = [[records[0]]]
    for record in records[1:]:
        if record["station_m"] - groups[-1][-1]["station_m"] <= maximum_gap_m:
            groups[-1].append(record)
        else:
            groups.append([record])
    return max(groups, key=lambda g: (g[-1]["station_m"] - g[0]["station_m"], len(g)))


def build_raw_ld_gap_tracks(
    recording: dict[str, Any],
    lane_geometry: list[dict[str, Any]],
    *,
    sample_spacing_m: float = 2.0,
    minimum_width_m: float = 2.2,
    maximum_width_m: float = 6.5,
    maximum_heading_difference_deg: float = 18.0,
    minimum_gap_overlap_m: float = 6.0,
    maximum_width_std_m: float = 0.65,
    maximum_width_range_m: float = 1.5,
    maximum_wedge_ratio: float = 1.6,
    maximum_canonical_coverage_fraction: float = 0.35,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Recover only uncovered lane corridors from immediate neighboring raw lines."""
    boundaries = _raw_boundaries(recording)
    canonical_polygons = _canonical_polygons(lane_geometry)
    represented_pairs = {
        frozenset((str(lane.get("left_edge_id")), str(lane.get("right_edge_id"))))
        for lane in lane_geometry
        if lane.get("assignment_valid") and lane.get("left_edge_id") is not None and lane.get("right_edge_id") is not None
    }

    # Each boundary samples the nearest valid raw boundary on each lateral side.
    # This enforces local lateral ordering: non-neighboring lines never become a pair.
    observations: dict[frozenset[str], list[dict[str, Any]]] = defaultdict(list)
    for anchor in boundaries:
        for station, p, heading in _sample(anchor["points"], sample_spacing_m):
            best_side: dict[str, tuple[float, dict[str, Any], list[float], float, float] | None] = {"left": None, "right": None}
            nx, ny = -math.sin(heading), math.cos(heading)
            for other in boundaries:
                if other is anchor:
                    continue
                projection = _project(p, other["points"])
                if projection is None:
                    continue
                distance_m, q, other_heading = projection
                heading_diff = _orientation_diff_deg(other_heading, heading)
                if heading_diff > maximum_heading_difference_deg:
                    continue
                lateral = (q[0] - p[0]) * nx + (q[1] - p[1]) * ny
                width = abs(lateral)
                if not (minimum_width_m <= width <= maximum_width_m):
                    continue
                side = "left" if lateral > 0 else "right"
                candidate = (width, other, q, heading_diff, lateral)
                if best_side[side] is None or candidate[0] < best_side[side][0]:
                    best_side[side] = candidate
            for side, chosen in best_side.items():
                if chosen is None:
                    continue
                width, other, q, heading_diff, lateral = chosen
                pair = frozenset((anchor["boundary_id"], other["boundary_id"]))
                if pair in represented_pairs:
                    continue
                center = [(p[0] + q[0]) / 2.0, (p[1] + q[1]) / 2.0]
                observations[pair].append({
                    "anchor_id": anchor["boundary_id"],
                    "other_id": other["boundary_id"],
                    "anchor_point": p,
                    "other_point": q,
                    "station_m": station,
                    "heading_rad": heading,
                    "heading_difference_deg": heading_diff,
                    "signed_lateral_m": lateral,
                    "width_m": width,
                    "center": center,
                    "covered_by_canonical": _covered(center, canonical_polygons),
                    "side": side,
                })

    tracks: list[dict[str, Any]] = []
    debug: list[dict[str, Any]] = []
    accepted_pairs: set[frozenset[str]] = set()
    max_sample_gap = max(3.0, sample_spacing_m * 2.5)

    for pair, pair_records in observations.items():
        if pair in accepted_pairs:
            continue
        # Prefer one anchor orientation so duplicate A->B/B->A observations do not
        # get stitched into a false cross-boundary polygon.
        by_anchor: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in pair_records:
            by_anchor[record["anchor_id"]].append(record)
        candidates = []
        for anchor_id, records in by_anchor.items():
            # Gap recovery is deliberately clipped to uncovered samples only.
            uncovered = [r for r in records if not r["covered_by_canonical"]]
            run = _longest_contiguous(uncovered, max_sample_gap)
            if len(run) < 2:
                continue
            overlap = run[-1]["station_m"] - run[0]["station_m"]
            if overlap < minimum_gap_overlap_m:
                continue
            candidates.append((overlap, len(run), anchor_id, run))
        if not candidates:
            continue
        _, _, anchor_id, run = max(candidates)

        widths = [r["width_m"] for r in run]
        mean_width = sum(widths) / len(widths)
        width_std = math.sqrt(sum((w - mean_width) ** 2 for w in widths) / len(widths))
        width_range = max(widths) - min(widths)
        wedge_ratio = max(widths) / max(min(widths), 1e-6)
        coverage_fraction = sum(1 for r in run if r["covered_by_canonical"]) / len(run)
        if width_std > maximum_width_std_m or width_range > maximum_width_range_m or wedge_ratio > maximum_wedge_ratio or coverage_fraction > maximum_canonical_coverage_fraction:
            debug.append({"boundary_pair": sorted(pair), "accepted": False, "reason": "unstable_width_or_existing_coverage", "width_std_m": round(width_std, 3), "width_range_m": round(width_range, 3), "wedge_ratio": round(wedge_ratio, 3), "canonical_coverage_fraction": round(coverage_fraction, 3)})
            continue

        # Reorient each sample into physical left/right according to anchor heading.
        left, right = [], []
        for record in run:
            if record["signed_lateral_m"] > 0:
                left.append(record["other_point"])
                right.append(record["anchor_point"])
            else:
                left.append(record["anchor_point"])
                right.append(record["other_point"])
        if _polyline_crosses(left, right):
            debug.append({"boundary_pair": sorted(pair), "accepted": False, "reason": "boundaries_cross"})
            continue
        polygon = left + list(reversed(right))
        if _polygon_self_intersects(polygon):
            debug.append({"boundary_pair": sorted(pair), "accepted": False, "reason": "self_intersecting_polygon"})
            continue
        centerline = [[(l[0] + r[0]) / 2.0, (l[1] + r[1]) / 2.0] for l, r in zip(left, right)]
        if len(centerline) < 2:
            continue

        ids = sorted(pair)
        first = run[0]
        if first["signed_lateral_m"] > 0:
            left_id, right_id = first["other_id"], first["anchor_id"]
        else:
            left_id, right_id = first["anchor_id"], first["other_id"]
        track_id = f"raw_ld_gap_track_{len(tracks) + 1:04d}"
        track = {
            "track_id": track_id,
            "logical_lane_id": track_id,
            "member_lane_ids": [],
            "centerline_lcs_m": centerline,
            "polygon_lcs_m": polygon,
            "median_width_m": round(sorted(widths)[len(widths) // 2], 3),
            "pieces": [{
                "kind": "observed_ld",
                "source": "raw_ld_gap_recovery",
                "polygon_lcs_m": polygon,
                "centerline_lcs_m": centerline,
                "left_boundary_lcs_m": left,
                "right_boundary_lcs_m": right,
                "left_boundary_id": left_id,
                "right_boundary_id": right_id,
            }],
            "piece_count": 1,
            "observed_segment_count": 0,
            "inferred_gap_count": 0,
            "source": "raw_ld_gap_recovery",
            "left_boundary_id": left_id,
            "right_boundary_id": right_id,
            "left_boundary_lcs_m": left,
            "right_boundary_lcs_m": right,
            "recovery_overlap_m": round(run[-1]["station_m"] - run[0]["station_m"], 3),
        }
        tracks.append(track)
        accepted_pairs.add(pair)
        debug.append({
            "track_id": track_id,
            "boundary_pair": ids,
            "accepted": True,
            "reason": "nearest_neighbor_uncovered_contiguous_gap",
            "overlap_m": track["recovery_overlap_m"],
            "median_width_m": track["median_width_m"],
            "width_std_m": round(width_std, 3),
            "width_range_m": round(width_range, 3),
            "wedge_ratio": round(wedge_ratio, 3),
            "canonical_coverage_fraction": round(coverage_fraction, 3),
        })
    return tracks, debug
