"""Choose static inferred-lane affiliations from local endpoint continuation.

Adjacency is deliberately not used. BACK and FRONT affiliation is selected from
physical-track endpoints using center/boundary endpoint distances, local tangent,
local endpoint width, curvature, lateral position, and uniqueness.
"""
from __future__ import annotations

import copy
from typing import Any

from .inferred_endpoint_support import (
    evaluate_inferred_endpoint_candidate,
    select_unique_continuation,
)


def assign_static_inferred_affiliations(
    static_lanes: list[dict[str, Any]],
    tracks: list[dict[str, Any]],
    lane_geometry: list[dict[str, Any]],
    *,
    maximum_endpoint_distance_m: float = 20.0,
    maximum_boundary_endpoint_distance_m: float = 20.0,
    maximum_lateral_error_m: float = 2.0,
    maximum_heading_difference_deg: float = 30.0,
    maximum_curvature_difference_per_m: float = 0.08,
    maximum_width_difference_m: float = 1.0,
    minimum_unique_score_margin: float = 0.5,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Overwrite remembered temporal IDs with unique local endpoint continuations."""
    resolved = copy.deepcopy(static_lanes)
    lane_by_id = {str(l.get("lane_id")): l for l in lane_geometry}
    debug: list[dict[str, Any]] = []

    for inferred in resolved:
        record: dict[str, Any] = {
            "static_inferred_lane_id": inferred.get("static_inferred_lane_id"),
            "route_id": inferred.get("route_id"),
            "method": "local_boundary_aware_longitudinal_endpoint_continuation_no_adjacency",
            "remembered_start_track_id": inferred.get("start_observed_track_id"),
            "remembered_end_track_id": inferred.get("end_observed_track_id"),
        }
        chosen: dict[str, dict[str, Any] | None] = {"back": None, "front": None}

        for role in ("back", "front"):
            candidates: list[dict[str, Any]] = []
            for track in tracks:
                candidates.extend(evaluate_inferred_endpoint_candidate(
                    inferred,
                    track,
                    lane_by_id,
                    role,
                    maximum_endpoint_distance_m=maximum_endpoint_distance_m,
                    maximum_boundary_endpoint_distance_m=maximum_boundary_endpoint_distance_m,
                    maximum_lateral_error_m=maximum_lateral_error_m,
                    maximum_heading_difference_deg=maximum_heading_difference_deg,
                    maximum_curvature_difference_per_m=maximum_curvature_difference_per_m,
                    maximum_width_difference_m=maximum_width_difference_m,
                ))
            candidates.sort(key=lambda x: (
                bool(x.get("rejection_reasons")),
                float(x.get("score", float("inf"))),
                str(x.get("track_id")),
                str(x.get("track_endpoint_side")),
            ))
            selected, selection_rejection = select_unique_continuation(
                candidates,
                minimum_score_margin=minimum_unique_score_margin,
            )
            chosen[role] = selected
            # Keep the complete candidate set. The dedicated inferred-lane tuner
            # reapplies gates live, so candidates that fail the default config
            # must remain available when the user loosens a threshold.
            record[f"{role}_candidates"] = candidates
            record[f"{role}_selected_track_id"] = None if selected is None else selected.get("track_id")
            record[f"{role}_selected_support"] = selected
            record[f"{role}_selection_rejection_reason"] = selection_rejection

        inferred["tracker_start_observed_track_id"] = inferred.get("start_observed_track_id")
        inferred["tracker_end_observed_track_id"] = inferred.get("end_observed_track_id")
        inferred["start_observed_track_id"] = None if chosen["back"] is None else chosen["back"].get("track_id")
        inferred["end_observed_track_id"] = None if chosen["front"] is None else chosen["front"].get("track_id")
        inferred["back_affiliation"] = chosen["back"]
        inferred["front_affiliation"] = chosen["front"]
        inferred["bridge_complete"] = bool(chosen["back"] and chosen["front"])
        inferred["affiliation_method"] = "local_boundary_aware_longitudinal_endpoint_continuation_no_adjacency"
        record["accepted"] = bool(inferred["bridge_complete"])
        debug.append(record)

    return resolved, debug
