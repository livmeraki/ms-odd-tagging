"""Final role pass using piece-local track geometry.

The existing integrated detector owns reconstruction, inferred affiliation,
connectors, and topology-supported stitching. This wrapper adds conservative
post-construction identity reconciliation before final lane ordering:
1. absorb standalone observed fragments embedded in inferred gaps;
2. merge unambiguous exact-touch canonical endpoints using local geometry;
3. classify final ego/left/right roles from piece-local geometry;
4. reassign objects and following-lane state against the final integrated track.
"""
from __future__ import annotations

import math
from typing import Any

from ms_odd_tagging.input_generator.canonical import LEAD_CLASSES

from .detector import _lane_output, _nearest_member
from .detector_baseline import segment_states
from .detector_static_order_integrated import run_lane_debug_v2 as run_integrated
from .embedded_fragment_absorption import absorb_embedded_observed_fragments
from .exact_touch_reconciliation import reconcile_exact_touch_tracks
from .static_lane_order_piece_local import (
    build_constructed_lane_network,
    build_static_lane_order,
    classify_lane_roles,
)
from .strict_track_assignment import assign_point_to_track_strict


_INFERRED_TRACK_PIECE_KINDS = {
    "ego_supported_inferred_route",
    "static_inferred_corridor",
    "static_inferred_connector",
}


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _assign_object_to_final_track(
    obj: dict[str, Any],
    tracks: list[dict[str, Any]],
    member_to_track: dict[str, str],
) -> None:
    """Attach an object to the final physical track, including inferred pieces.

    Existing canonical lane membership remains the first choice. If the object
    has no usable physical lane ID, strict center-in-polygon assignment is run
    against final track pieces. This is what lets objects inside an integrated
    static inferred corridor share the same logical track as ego.
    """
    lane_id = obj.get("lane_id")
    if lane_id is not None and str(lane_id) in member_to_track:
        track_id = member_to_track[str(lane_id)]
        obj["logical_lane_id"] = track_id
        obj["continuous_track_id"] = track_id
        obj["final_track_assignment_method"] = "physical_lane_member_map"
        return

    position = obj.get("position_lcs_m") or []
    if len(position) >= 2 and _finite(position[0]) and _finite(position[1]):
        assignment = assign_point_to_track_strict(
            (float(position[0]), float(position[1])),
            None,
            tracks,
            previous_track_id=None,
            maximum_heading_difference_deg=180.0,
            outside_tolerance_m=0.0,
        )
        track_id = assignment.get("track_id")
        if track_id:
            obj["logical_lane_id"] = str(track_id)
            obj["continuous_track_id"] = str(track_id)
            obj["final_track_assignment_method"] = "inside_final_track_piece_polygon"
            obj["final_track_matched_piece_kind"] = assignment.get("matched_piece_kind")
            obj["inside_ego_lane_area"] = True
            obj["ego_lane_area_source"] = "final_integrated_track_piece"
            return

    obj["logical_lane_id"] = None
    obj["continuous_track_id"] = None
    obj["final_track_assignment_method"] = "no_final_track_contains_object_center"


def _refresh_final_following_lane_state(result: dict[str, Any], settings: dict[str, Any]) -> None:
    """Recompute following-lane semantics after final integrated assignment."""
    minimum_speed = float(settings.get("minimum_moving_speed_mps", 0.5))
    maximum_lead = float(settings.get("maximum_lead_distance_m", 80.0))
    lead_types = set(settings.get("lead_annotation_types", ["dynamic"]))
    enforce_direction = settings.get("lead_direction_filter_mode", "diagnostic") == "enforce"

    for frame in result.get("frames", []):
        ego_track_id = (frame.get("ego_lane") or {}).get("continuous_track_id")
        candidates = []
        for obj in frame.get("objects", []):
            same_track = bool(
                ego_track_id
                and obj.get("continuous_track_id")
                and str(obj.get("continuous_track_id")) == str(ego_track_id)
            )
            longitudinal = obj.get("longitudinal_m")
            eligible = bool(
                same_track
                and obj.get("class") in LEAD_CLASSES
                and obj.get("annotation_type") in lead_types
                and _finite(longitudinal)
                and 0.0 < float(longitudinal) <= maximum_lead
            )
            if eligible and enforce_direction and obj.get("lead_direction_eligible") is False:
                eligible = False
            obj["final_following_lane_same_track_as_ego"] = same_track
            obj["final_lead_candidate"] = eligible
            if eligible:
                obj["inside_ego_lane_area"] = True
                if not obj.get("ego_lane_area_source"):
                    obj["ego_lane_area_source"] = "same_final_integrated_track"
                candidates.append(obj)

        candidates.sort(key=lambda item: float(item["longitudinal_m"]))
        frame["lead"] = candidates[0] if candidates else None
        frame["lead_candidate_count"] = len(candidates)
        frame["lead_candidates_debug_final"] = [
            {
                "object_id": obj.get("object_id"),
                "continuous_track_id": obj.get("continuous_track_id"),
                "longitudinal_m": obj.get("longitudinal_m"),
                "matched_piece_kind": obj.get("final_track_matched_piece_kind"),
            }
            for obj in candidates
        ]

        speed = frame.get("speed_mps")
        if not _finite(speed):
            frame["state"], frame["reason"] = "unknown", "invalid_or_missing_speed"
        elif float(speed) < minimum_speed:
            frame["state"], frame["reason"] = "not_applicable", "ego_below_moving_speed"
        elif not ego_track_id:
            frame["state"], frame["reason"] = "unknown", "final_integrated_ego_track_unknown"
        elif candidates:
            frame["state"] = "following_lane_with_lead"
            frame["reason"] = "nearest_dynamic_vehicle_ahead_in_final_integrated_ego_track"
        else:
            frame["state"] = "following_lane_without_lead"
            frame["reason"] = "moving_ego_inside_final_integrated_lane_track_without_lead"

        frame["following_lane_source"] = "final_piece_local_integrated_track"

    result["intervals"] = segment_states(result.get("frames", []))
    result["final_following_lane_recomputed"] = True
    result["final_following_lane_policy"] = {
        "ego_reference": "final_integrated_continuous_track_id",
        "static_inferred_corridor_counts_as_lane": True,
        "objects_inside_integrated_inferred_piece_can_share_ego_track": True,
        "intervals_recomputed_after_final_track_assignment": True,
    }


def _recompute_frames_piece_local(
    recording: dict[str, Any],
    result: dict[str, Any],
    tracks: list[dict[str, Any]],
    lane_order: dict[str, Any],
    config: dict[str, Any],
) -> None:
    lane_geometry = result.get("lane_geometry", [])
    lane_by_id = {str(l.get("lane_id")): l for l in lane_geometry}
    track_by_id = {str(t.get("track_id")): t for t in tracks}
    member_to_track = {
        str(lane_id): str(track.get("track_id"))
        for track in tracks for lane_id in track.get("member_lane_ids", [])
    }
    source_by_frame = {f.get("frame_index"): f for f in recording.get("frames", [])}
    previous_track_id = None
    max_heading = float(config.get("continuous_track_maximum_heading_difference_deg", 60.0))
    outside_tol = float(config.get("continuous_track_outside_tolerance_m", 1.0))

    for frame in result.get("frames", []):
        src = source_by_frame.get(frame.get("frame_index"), {})
        ego = src.get("ego") or {}
        p = ego.get("position_lcs_m") or []
        heading = ego.get("heading_lcs_rad")
        if len(p) < 2 or heading is None:
            continue
        point = (float(p[0]), float(p[1]))
        assignment = assign_point_to_track_strict(
            point,
            float(heading),
            tracks,
            previous_track_id=previous_track_id,
            maximum_heading_difference_deg=max_heading,
            outside_tolerance_m=outside_tol,
        )
        frame["continuous_ego_track"] = assignment
        track_id = str(assignment.get("track_id")) if assignment.get("track_id") else None
        if track_id:
            previous_track_id = track_id
            track = track_by_id.get(track_id)
            matched_kind = assignment.get("matched_piece_kind")
            inferred_piece = matched_kind in _INFERRED_TRACK_PIECE_KINDS
            # Do not fabricate a physical LD lane ID while ego is physically in
            # an inferred piece. The physical track identity is still continuous
            # across BACK + inferred corridor + FRONT.
            physical = assignment.get("matched_lane_id")
            if physical is None and not inferred_piece:
                physical = _nearest_member(track, point, lane_by_id)
            frame["ego_lane"] = {
                "lane_id": physical,
                "logical_lane_id": track_id,
                "continuous_track_id": track_id,
                "continuous_track_member_lane_ids": assignment.get("member_lane_ids", []),
                "method": assignment.get("method"),
                "confidence": assignment.get("confidence"),
                "inside_polygon": assignment.get("inside_polygon"),
                "polygon_distance_m": assignment.get("polygon_distance_m"),
                "source": "final_piece_local_static_lane_network",
                "track_source": None if not track else track.get("source"),
                "matched_piece_kind": matched_kind,
                "inferred": inferred_piece,
                "whole_integrated_track_is_ego_lane": True,
            }
            roles = classify_lane_roles(point, track_id, tracks, lane_order, float(heading))
            frame["lane_roles"] = roles
            frame["left_lane"] = _lane_output(roles.get("left") or {}, point, track_by_id, lane_by_id)
            frame["right_lane"] = _lane_output(roles.get("right") or {}, point, track_by_id, lane_by_id)
        else:
            frame["ego_lane"] = {
                "lane_id": None,
                "logical_lane_id": None,
                "continuous_track_id": None,
                "method": assignment.get("method", "no_final_track_contains_ego"),
                "confidence": "unknown",
                "source": "final_piece_local_static_lane_network",
            }
            frame["lane_roles"] = {
                "ego_track_id": None,
                "left": {"track_id": None},
                "right": {"track_id": None},
                "roles": [
                    {"track_id": str(t.get("track_id")), "role": "irrelevant"}
                    for t in tracks
                ],
                "method": "no_final_ego_track",
            }
            frame["left_lane"] = {"lane_id": None, "method": "ego_track_unknown"}
            frame["right_lane"] = {"lane_id": None, "method": "ego_track_unknown"}

        for obj in frame.get("objects", []):
            _assign_object_to_final_track(obj, tracks, member_to_track)

    result["continuous_track_member_map"] = member_to_track
    _refresh_final_following_lane_state(result, config)


def run_lane_debug_v2(recording: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = dict(config or {})
    result = run_integrated(recording, cfg)
    settings = {**(result.get("debug_config") or {}), **cfg}

    # Stage 1: repair duplicate identities where a standalone observed fragment
    # already occupies one host track's inferred-gap geometry.
    tracks, absorption_debug = absorb_embedded_observed_fragments(
        result.get("continuous_lane_tracks", []),
        result.get("lane_geometry", []),
        maximum_endpoint_error_m=float(cfg.get("embedded_fragment_maximum_endpoint_error_m", 0.35)),
        maximum_heading_difference_deg=float(cfg.get("embedded_fragment_maximum_heading_difference_deg", 12.0)),
        maximum_centerline_deviation_m=float(cfg.get("embedded_fragment_maximum_centerline_deviation_m", 0.5)),
        maximum_width_difference_m=float(cfg.get("embedded_fragment_maximum_width_difference_m", 0.75)),
        require_boundary_continuity=bool(cfg.get("embedded_fragment_require_boundary_continuity", True)),
    )
    result["embedded_observed_fragment_absorption_debug"] = absorption_debug
    result["embedded_observed_fragment_absorption_count"] = sum(
        1 for row in absorption_debug if row.get("accepted")
    )

    # Stage 2: reconcile direct canonical touches that ordinary forward-gap
    # continuation intentionally skipped. Use local endpoint width and boundary
    # endpoints; never whole-lane median width and never a synthetic connector.
    tracks, exact_touch_debug = reconcile_exact_touch_tracks(
        tracks,
        result.get("lane_geometry", []),
        maximum_endpoint_gap_m=float(cfg.get("exact_touch_maximum_endpoint_gap_m", 0.25)),
        maximum_heading_difference_deg=float(cfg.get("exact_touch_maximum_heading_difference_deg", 8.0)),
        maximum_local_width_difference_m=float(cfg.get("exact_touch_maximum_local_width_difference_m", 0.5)),
        maximum_boundary_endpoint_gap_m=float(cfg.get("exact_touch_maximum_boundary_endpoint_gap_m", 0.25)),
    )
    result["continuous_lane_tracks"] = tracks
    result["exact_touch_reconciliation_debug"] = exact_touch_debug
    result["exact_touch_reconciliation_count"] = sum(
        1 for row in exact_touch_debug if row.get("accepted") and row.get("action") == "merge_exact_touch_tracks_preserve_source_id"
    )
    result["post_construction_identity_audit"] = {
        "embedded_fragment_candidates_rejected": sum(
            1 for row in absorption_debug if not row.get("accepted")
        ),
        "exact_touch_candidates_rejected": sum(
            1 for row in exact_touch_debug if row.get("eligible") is False
        ),
        "ambiguous_exact_touch_candidates": sum(
            1 for row in exact_touch_debug
            if "ambiguous_fork_multiple_exact_touch_destinations" in (row.get("rejection_reasons") or [])
        ),
    }

    lane_order = build_static_lane_order(
        tracks,
        sample_spacing_m=float(settings.get("lane_order_sample_spacing_m", 2.0)),
        maximum_heading_difference_deg=float(settings.get("lane_order_maximum_heading_difference_deg", 20.0)),
        minimum_lateral_m=float(settings.get("lane_order_minimum_lateral_m", 1.5)),
        maximum_lateral_m=float(settings.get("lane_order_maximum_lateral_m", 8.0)),
        maximum_longitudinal_m=float(settings.get("lane_order_maximum_longitudinal_m", 8.0)),
    )
    result["static_lane_order_topology"] = lane_order
    result["constructed_lane_network"] = build_constructed_lane_network(tracks, lane_order)
    _recompute_frames_piece_local(recording, result, tracks, lane_order, settings)
    result["final_lane_role_policy"] = {
        "method": "static_cross_section_piece_local_lane_order",
        "candidate_projection": "nearest_valid_track_piece_centerline",
        "static_inferred_corridor_participates": True,
        "integrated_track_is_single_ego_lane_across_inferred_piece": True,
        "objects_reassigned_against_final_track_pieces": True,
        "following_lane_recomputed_after_final_assignment": True,
        "embedded_observed_fragment_absorption_before_final_order": True,
        "exact_touch_reconciliation_before_final_order": True,
    }
    result["embedded_fragment_absorption_policy"] = {
        "method": "replace_unambiguous_host_inferred_gap_with_standalone_observed_fragment",
        "preserve_host_track_id": True,
        "global_zero_gap_relaxation": False,
    }
    result["exact_touch_reconciliation_policy"] = {
        "method": "canonical_local_endpoint_touch_merge",
        "preserve_source_track_id": True,
        "synthetic_connector": False,
        "whole_lane_median_width_used": False,
        "fork_policy": "reject_ambiguous_unless_unique_boundary_identity_winner",
    }
    result["schema_version"] = "lane-debug-v2-piece-local-final-role-v5-integrated-inferred-following"
    return result
