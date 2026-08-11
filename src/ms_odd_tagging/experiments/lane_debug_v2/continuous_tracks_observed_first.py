"""Observed-first continuous track construction for lane-debug v2.

Continuation priority is intentionally evidence-first:
1. exact canonical observed touch;
2. unique local interior endpoint affiliation between fragmented observed lanes;
3. curvature-based inferred gap.

This prevents leapfrog tracks while allowing short/noisy canonical fragments of
the same physical lane to integrate before synthetic curvature inference.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from .continuous_tracks import (
    _append_points,
    _corridor_polygon,
    _median_lane_width,
    _piece_kind,
    _trajectory_cost,
    _trajectory_points,
)
from .observed_local_affiliation import build_observed_local_affiliation_graph
from .observed_touch_graph import (
    build_observed_touch_graph,
    inferred_gap_occupied_by_observed_fragment,
)


def build_continuous_tracks(
    lane_geometry: list[dict[str, Any]],
    recording: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, str], list[dict[str, Any]]]:
    """Construct physical tracks using exact, local-affiliation, then curvature evidence."""
    lanes = {str(l["lane_id"]): l for l in lane_geometry if l.get("assignment_valid")}
    trajectory = _trajectory_points(recording)

    observed_edges, observed_debug = build_observed_touch_graph(lane_geometry)
    local_edges, local_debug = build_observed_local_affiliation_graph(
        lane_geometry,
        excluded_source_ids=set(observed_edges),
    )
    proposals: list[dict[str, Any]] = []

    # Priority 0: real observed canonical continuations. These contain no
    # synthetic gap geometry and therefore cannot create a leapfrog fill.
    for source_id, edge in observed_edges.items():
        destination_id = str(edge["destination_lane_id"])
        if source_id not in lanes or destination_id not in lanes:
            continue
        proposals.append({
            "source": source_id,
            "destination": destination_id,
            "priority": 0,
            "connection_kind": "observed_exact_touch",
            "score": float(edge.get("center_gap_m", 0.0))
            + float(edge.get("heading_difference_deg", 0.0)) * 0.01,
            "gap_m": edge.get("center_gap_m"),
            "projected": [],
            "gap_polygon": [],
            "evidence": edge,
        })

    # Priority 1: fragmented observed lanes that are not exact-touch but have a
    # unique longitudinal continuation under the same 3/4.5/6 m interior
    # geometry evidence used for inferred-lane BACK/FRONT affiliation.
    for source_id, edge in local_edges.items():
        destination_id = str(edge["destination_lane_id"])
        if source_id not in lanes or destination_id not in lanes:
            continue
        proposals.append({
            "source": source_id,
            "destination": destination_id,
            "priority": 1,
            "connection_kind": "observed_local_interior_affiliation",
            "score": float(edge.get("score", math.inf)),
            "gap_m": edge.get("center_gap_m"),
            "projected": edge.get("connection_centerline_lcs_m") or [],
            "gap_polygon": edge.get("connection_polygon_lcs_m") or [],
            "evidence": edge,
        })

    inferred_rejections: list[dict[str, Any]] = []
    for source_id, lane in lanes.items():
        # Higher-confidence observed evidence blocks curvature inference from the
        # same source. Exact touch is strongest; local affiliation is next.
        higher_kind = (
            "observed_exact_touch"
            if source_id in observed_edges
            else "observed_local_interior_affiliation"
            if source_id in local_edges
            else None
        )
        if higher_kind is not None:
            for cont in lane.get("curvature_continuations") or []:
                destination_id = cont.get("destination_lane_id")
                if destination_id:
                    inferred_rejections.append({
                        "source": source_id,
                        "destination": str(destination_id),
                        "connection_kind": "inferred_gap",
                        "accepted": False,
                        "rejection_reason": f"{higher_kind}_has_priority",
                    })
            continue

        for cont in lane.get("curvature_continuations") or []:
            destination_id = cont.get("destination_lane_id")
            accepted = cont.get("accepted_candidate")
            if not destination_id or str(destination_id) not in lanes or not accepted:
                continue
            if accepted.get("rejection_reasons"):
                continue
            destination_id = str(destination_id)

            # Defensive audit: never create an inferred span when one compatible
            # observed fragment already fills that source→destination interval.
            occupied = inferred_gap_occupied_by_observed_fragment(
                lane,
                lanes[destination_id],
                lane_geometry,
            )
            if occupied is not None:
                inferred_rejections.append({
                    "source": source_id,
                    "destination": destination_id,
                    "connection_kind": "inferred_gap",
                    "accepted": False,
                    "rejection_reason": "observed_fragment_occupies_inferred_gap",
                    "occupancy_evidence": occupied,
                    "evidence": accepted,
                })
                continue

            proposals.append({
                "source": source_id,
                "destination": destination_id,
                "priority": 2,
                "connection_kind": "inferred_gap",
                "score": float(accepted.get("score", math.inf)),
                "gap_m": accepted.get("gap_m"),
                "projected": cont.get("projected_centerline_lcs_m") or [],
                "gap_polygon": cont.get("inferred_gap_polygon_lcs_m") or [],
                "evidence": accepted,
            })

    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for proposal in proposals:
        outgoing[proposal["source"]].append(proposal)
        incoming[proposal["destination"]].append(proposal)

    # Higher-confidence evidence always beats lower-confidence evidence. Score
    # remains the secondary discriminator within the same evidence class.
    best_out = {
        src: min(items, key=lambda p: (p["priority"], p["score"], p["destination"]))
        for src, items in outgoing.items()
    }
    best_in: dict[str, dict[str, Any]] = {}
    for dst, items in incoming.items():
        best_in[dst] = min(
            items,
            key=lambda p: (
                p["priority"],
                p["score"],
                _trajectory_cost(trajectory, lanes[p["source"]].get("centerline_lcs_m") or []),
                p["source"],
            ),
        )

    accepted_edges: dict[str, dict[str, Any]] = {}
    rejected_edges: list[dict[str, Any]] = []
    for src, proposal in best_out.items():
        if best_in.get(proposal["destination"]) is proposal:
            accepted_edges[src] = proposal
        else:
            rejected_edges.append({
                **proposal,
                "accepted": False,
                "rejection_reason": "bidirectional_incoming_conflict",
            })

    predecessors = {proposal["destination"]: src for src, proposal in accepted_edges.items()}
    visited: set[str] = set()
    tracks: list[dict[str, Any]] = []
    member_to_track: dict[str, str] = {}

    starts = [lane_id for lane_id in lanes if lane_id not in predecessors]
    starts += [lane_id for lane_id in lanes if lane_id not in starts]
    for start in starts:
        if start in visited:
            continue
        members: list[str] = []
        pieces: list[dict[str, Any]] = []
        merged: list[list[float]] = []
        widths: list[float] = []
        current = start
        seen_local: set[str] = set()

        while current in lanes and current not in seen_local and current not in visited:
            seen_local.add(current)
            visited.add(current)
            lane = lanes[current]
            members.append(current)
            widths.append(_median_lane_width(lane))
            center = lane.get("centerline_lcs_m") or []
            pieces.append({
                "kind": _piece_kind(lane),
                "lane_id": current,
                "centerline_lcs_m": center,
                "polygon_lcs_m": lane.get("polygon_lcs_m") or [],
                "recovery_method": lane.get("recovery_method"),
            })
            _append_points(merged, center)

            edge = accepted_edges.get(current)
            if not edge:
                break
            connection_kind = edge.get("connection_kind")
            gap = edge.get("projected") or []
            if connection_kind == "inferred_gap" and gap:
                pieces.append({
                    "kind": "inferred_gap",
                    "source_lane_id": current,
                    "destination_lane_id": edge["destination"],
                    "centerline_lcs_m": gap,
                    "polygon_lcs_m": edge.get("gap_polygon") or [],
                    "connection_evidence": edge.get("evidence"),
                })
                _append_points(merged, gap)
            elif connection_kind == "observed_local_interior_affiliation" and gap:
                pieces.append({
                    "kind": "canonical_track_stitch",
                    "source_lane_id": current,
                    "destination_lane_id": edge["destination"],
                    "centerline_lcs_m": gap,
                    "polygon_lcs_m": edge.get("gap_polygon") or [],
                    "connection_method": "observed_fragment_local_interior_endpoint_affiliation",
                    "connection_evidence": edge.get("evidence"),
                })
                _append_points(merged, gap)
            # observed_exact_touch intentionally inserts no connector piece.
            current = edge["destination"]

        if not members:
            continue
        track_id = f"physical_track_{len(tracks)+1:04d}"
        width = sorted(widths)[len(widths) // 2] if widths else 3.5
        track = {
            "track_id": track_id,
            "logical_lane_id": track_id,
            "member_lane_ids": members,
            "centerline_lcs_m": merged,
            "polygon_lcs_m": _corridor_polygon(merged, width),
            "median_width_m": round(width, 3),
            "pieces": pieces,
            "piece_count": len(pieces),
            "observed_segment_count": len(members),
            "inferred_gap_count": sum(1 for p in pieces if p["kind"] == "inferred_gap"),
            "observed_exact_touch_edge_count": sum(
                1
                for lane_id in members
                if accepted_edges.get(lane_id, {}).get("connection_kind") == "observed_exact_touch"
            ),
            "observed_local_affiliation_edge_count": sum(
                1
                for lane_id in members
                if accepted_edges.get(lane_id, {}).get("connection_kind") == "observed_local_interior_affiliation"
            ),
        }
        tracks.append(track)
        for lane_id in members:
            member_to_track[lane_id] = track_id

    proposal_debug = [
        {
            **proposal,
            "accepted": accepted_edges.get(proposal["source"]) is proposal,
        }
        for proposal in proposals
    ]
    edge_debug = (
        [{"debug_stage": "observed_touch_graph", **row} for row in observed_debug]
        + [{"debug_stage": "observed_local_affiliation", **row} for row in local_debug]
        + proposal_debug
        + rejected_edges
        + inferred_rejections
    )
    return tracks, member_to_track, edge_debug
