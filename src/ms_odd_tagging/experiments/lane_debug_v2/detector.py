"""Experimental lane detector using a static constructed LD lane network.

Canonical LD lanes are constructed once into continuous tracks. Raw LD is not
allowed to create arbitrary global lane pairs; it may only recover conservative
uncovered gaps between immediate neighboring physical boundaries. Frames then
classify the static tracks as ego, left-adjacent, right-adjacent, or irrelevant.
"""
from __future__ import annotations

import copy
import math
from typing import Any

from .boundary_corridor import infer_ego_corridor_from_boundaries
from .continuous_tracks import adjacent_tracks, build_continuous_tracks
from .detector_baseline import run_following_lane as run_baseline
from .inferred_ego_route import InferredEgoRouteTracker
from .lane_geometry import nearest_heading, polyline_distance, wrap_angle
from .lane_network_roles import build_constructed_lane_network, classify_all_lane_roles
from .object_motion import build_object_motion_evidence
from .raw_ld_gap_recovery import build_raw_ld_gap_tracks
from .strict_track_assignment import assign_point_to_track_strict
from .track_topology import build_track_adjacency_graph


DEFAULT_DEBUG = {
    "object_motion_history_frames": 3,
    "object_motion_minimum_displacement_m": 0.5,
    "lead_direction_filter_mode": "diagnostic",
    "maximum_lead_direction_difference_deg": None,
    "reject_ambiguous_stationary_lead": False,
    "continuous_track_assignment_enabled": True,
    "continuous_track_maximum_heading_difference_deg": 60.0,
    "continuous_track_outside_tolerance_m": 1.0,
    "continuous_track_adjacent_heading_difference_deg": 20.0,
    "continuous_track_adjacent_minimum_lateral_m": 1.5,
    "continuous_track_adjacent_maximum_lateral_m": 8.0,
    "continuous_track_adjacent_local_window_m": 20.0,
    "track_topology_sample_spacing_m": 2.0,
    "track_topology_minimum_overlap_m": 8.0,
    "track_topology_minimum_side_consistency": 0.8,
    "track_topology_maximum_lateral_std_m": 1.5,
    "track_topology_station_margin_m": 4.0,
    "track_topology_hysteresis_enabled": True,
    "track_topology_switch_score_margin": 0.75,
    "track_topology_switch_confirmation_frames": 3,
    "raw_ld_gap_recovery_enabled": True,
    "raw_ld_gap_sample_spacing_m": 2.0,
    "raw_ld_gap_minimum_overlap_m": 6.0,
    "raw_ld_gap_maximum_heading_difference_deg": 18.0,
    "raw_ld_gap_maximum_width_std_m": 0.65,
    "raw_ld_gap_maximum_width_range_m": 1.5,
    "raw_ld_gap_maximum_wedge_ratio": 1.6,
    "raw_ld_gap_maximum_canonical_coverage_fraction": 0.35,
    "boundary_ego_corridor_enabled": True,
    "boundary_ego_corridor_maximum_heading_difference_deg": 25.0,
    "boundary_ego_corridor_minimum_width_m": 2.2,
    "boundary_ego_corridor_maximum_width_m": 6.5,
    "boundary_ego_corridor_maximum_boundary_distance_m": 7.0,
    "boundary_ego_corridor_half_length_m": 15.0,
    "inferred_ego_route_maximum_endpoint_gap_m": 5.0,
    "inferred_ego_route_maximum_heading_difference_deg": 25.0,
}


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _nearest_member(track: dict[str, Any] | None, point: tuple[float, float], lane_by_id: dict[str, dict[str, Any]]) -> str | None:
    if not track:
        return None
    candidates = []
    for lane_id in track.get("member_lane_ids", []):
        lane = lane_by_id.get(str(lane_id)) or {}
        center = lane.get("centerline_lcs_m") or []
        if len(center) >= 2:
            candidates.append((polyline_distance(point, center), str(lane_id)))
    return min(candidates)[1] if candidates else None


def _lane_output(selected: dict[str, Any], point: tuple[float, float], track_by_id: dict[str, dict[str, Any]], lane_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    track_id = selected.get("track_id")
    track = track_by_id.get(str(track_id)) if track_id else None
    physical = _nearest_member(track, point, lane_by_id) if track else None
    return {
        "lane_id": physical,
        "logical_lane_id": track_id,
        "continuous_track_id": track_id,
        "method": selected.get("method", "not_found"),
        "confidence": selected.get("confidence", "unknown"),
        "held_from_previous_frame": selected.get("held_from_previous_frame", False),
        "topology_overlap_m": selected.get("overlap_m"),
        "topology_score": selected.get("score"),
        "reciprocal_relation": selected.get("reciprocal", False),
        "track_source": None if not track else track.get("source", "canonical_continuous_track"),
    }


def _corridor_role_table(corridor: dict[str, Any], tracks: list[dict[str, Any]]) -> dict[str, Any]:
    left, right = corridor.get("left_track_id"), corridor.get("right_track_id")
    roles = []
    for track in tracks:
        tid = str(track.get("track_id"))
        role = "left_adjacent" if left and tid == str(left) else "right_adjacent" if right and tid == str(right) else "irrelevant"
        roles.append({"track_id": tid, "role": role, "member_lane_ids": list(track.get("member_lane_ids", [])), "source": track.get("source", "canonical_continuous_track")})
    return {
        "ego_track_id": None,
        "left": {"track_id": left, "method": "boundary_inferred_adjacent_track" if left else "boundary_only_no_track", "confidence": "medium" if left else "unknown"},
        "right": {"track_id": right, "method": "boundary_inferred_adjacent_track" if right else "boundary_only_no_track", "confidence": "medium" if right else "unknown"},
        "roles": roles,
        "active_adjacency_candidates": [],
        "method": "boundary_corridor_lane_roles",
    }


def _lead_base_candidate(obj: dict[str, Any], frame: dict[str, Any], settings: dict[str, Any]) -> bool:
    ego_route = (frame.get("ego_lane") or {}).get("logical_lane_id")
    return bool(
        ego_route
        and not str(ego_route).startswith("inferred_ego_route_")
        and obj.get("logical_lane_id") == ego_route
        and obj.get("annotation_type") in settings.get("lead_annotation_types", ["dynamic"])
        and obj.get("class") in {"car", "truck", "truck_head", "bus", "trailer", "special_vehicle"}
        and _finite(obj.get("longitudinal_m"))
        and 0.0 < float(obj["longitudinal_m"]) <= float(settings.get("maximum_lead_distance_m", 80.0))
    )


def _apply_static_lane_network(recording: dict[str, Any], result: dict[str, Any], settings: dict[str, Any]) -> None:
    lane_geometry = result.get("lane_geometry", [])
    canonical_tracks, member_to_track, connection_debug = build_continuous_tracks(lane_geometry, recording)
    recovered_tracks: list[dict[str, Any]] = []
    recovery_debug: list[dict[str, Any]] = []
    if settings.get("raw_ld_gap_recovery_enabled", True):
        recovered_tracks, recovery_debug = build_raw_ld_gap_tracks(
            recording,
            lane_geometry,
            sample_spacing_m=float(settings["raw_ld_gap_sample_spacing_m"]),
            minimum_width_m=float(settings["boundary_ego_corridor_minimum_width_m"]),
            maximum_width_m=float(settings["boundary_ego_corridor_maximum_width_m"]),
            maximum_heading_difference_deg=float(settings["raw_ld_gap_maximum_heading_difference_deg"]),
            minimum_gap_overlap_m=float(settings["raw_ld_gap_minimum_overlap_m"]),
            maximum_width_std_m=float(settings["raw_ld_gap_maximum_width_std_m"]),
            maximum_width_range_m=float(settings["raw_ld_gap_maximum_width_range_m"]),
            maximum_wedge_ratio=float(settings["raw_ld_gap_maximum_wedge_ratio"]),
            maximum_canonical_coverage_fraction=float(settings["raw_ld_gap_maximum_canonical_coverage_fraction"]),
        )
    tracks = canonical_tracks + recovered_tracks
    topology_graph = build_track_adjacency_graph(
        tracks,
        lane_geometry,
        sample_spacing_m=float(settings["track_topology_sample_spacing_m"]),
        maximum_heading_difference_deg=float(settings["continuous_track_adjacent_heading_difference_deg"]),
        minimum_lateral_m=float(settings["continuous_track_adjacent_minimum_lateral_m"]),
        maximum_lateral_m=float(settings["continuous_track_adjacent_maximum_lateral_m"]),
        minimum_overlap_m=float(settings["track_topology_minimum_overlap_m"]),
        minimum_side_consistency=float(settings["track_topology_minimum_side_consistency"]),
        maximum_lateral_std_m=float(settings["track_topology_maximum_lateral_std_m"]),
    )
    result["continuous_lane_tracks"] = tracks
    result["canonical_continuous_lane_track_count"] = len(canonical_tracks)
    result["raw_ld_gap_recovery_track_count"] = len(recovered_tracks)
    result["raw_ld_gap_recovery_debug"] = recovery_debug
    # Explicitly record that the former arbitrary pairwise constructor is gone.
    result["raw_ld_global_pair_constructor_enabled"] = False
    result["continuous_track_member_map"] = member_to_track
    result["continuous_track_connection_debug"] = connection_debug
    result["track_adjacency_graph"] = topology_graph
    result["constructed_lane_network"] = build_constructed_lane_network(tracks, topology_graph)
    if not settings.get("continuous_track_assignment_enabled", True):
        return

    track_by_id = {str(t.get("track_id")): t for t in tracks}
    lane_by_id = {str(l.get("lane_id")): l for l in lane_geometry}
    source_by_frame = {f.get("frame_index"): f for f in recording.get("frames", [])}
    previous_track_id = None
    previous_adjacency = {"left": None, "right": None}
    pending_adjacency = {"left": None, "right": None}
    previous_boundary_ids = (None, None)
    route_tracker = InferredEgoRouteTracker(
        maximum_endpoint_gap_m=float(settings["inferred_ego_route_maximum_endpoint_gap_m"]),
        maximum_heading_difference_deg=float(settings["inferred_ego_route_maximum_heading_difference_deg"]),
    )

    for frame in result.get("frames", []):
        source = source_by_frame.get(frame.get("frame_index"), {})
        ego = source.get("ego") or {}
        p = ego.get("position_lcs_m") or []
        heading = ego.get("heading_lcs_rad")
        frame["segment_ego_lane"] = copy.deepcopy(frame.get("ego_lane"))
        frame["segment_left_lane"] = copy.deepcopy(frame.get("left_lane"))
        frame["segment_right_lane"] = copy.deepcopy(frame.get("right_lane"))
        if len(p) < 2 or not all(_finite(x) for x in p[:2]) or not _finite(heading):
            frame["ego_lane"] = {"lane_id": None, "logical_lane_id": None, "method": "invalid_ego_pose", "confidence": "unknown"}
            frame["lane_roles"] = {"ego_track_id": None, "left": {"track_id": None}, "right": {"track_id": None}, "roles": [], "method": "invalid_ego_pose"}
            continue

        point = (float(p[0]), float(p[1]))
        old_track_id = previous_track_id
        assignment = assign_point_to_track_strict(
            point,
            float(heading),
            tracks,
            previous_track_id=previous_track_id,
            maximum_heading_difference_deg=float(settings["continuous_track_maximum_heading_difference_deg"]),
            outside_tolerance_m=float(settings["continuous_track_outside_tolerance_m"]),
        )
        frame["continuous_ego_track"] = assignment
        track_id = str(assignment.get("track_id")) if assignment.get("track_id") else None
        if track_id:
            if old_track_id and track_id != old_track_id:
                if str(previous_adjacency.get("left")) == track_id:
                    previous_adjacency = {"left": None, "right": old_track_id}
                    pending_adjacency = {"left": None, "right": None}
                    frame["lane_role_transition_hint"] = "old_ego_should_become_right_after_left_lane_change"
                elif str(previous_adjacency.get("right")) == track_id:
                    previous_adjacency = {"left": old_track_id, "right": None}
                    pending_adjacency = {"left": None, "right": None}
                    frame["lane_role_transition_hint"] = "old_ego_should_become_left_after_right_lane_change"
            previous_track_id = track_id
            route_tracker.observe_actual_track(track_id, int(frame.get("frame_index", 0)))
            track = track_by_id.get(track_id)
            physical = assignment.get("matched_lane_id") or _nearest_member(track, point, lane_by_id)
            frame["ego_lane"] = {
                "lane_id": physical,
                "logical_lane_id": track_id,
                "continuous_track_id": track_id,
                "continuous_track_member_lane_ids": assignment.get("member_lane_ids", []),
                "method": assignment.get("method"),
                "confidence": assignment.get("confidence"),
                "inside_polygon": assignment.get("inside_polygon"),
                "polygon_distance_m": assignment.get("polygon_distance_m"),
                "source": "constructed_static_lane_network",
                "track_source": None if not track else track.get("source", "canonical_continuous_track"),
            }
            frame["inferred_ego_corridor"] = {"valid": False, "method": "not_needed_actual_ego_track_valid"}
            roles, previous_adjacency, pending_adjacency = classify_all_lane_roles(
                point,
                track_id,
                tracks,
                topology_graph,
                previous_adjacency=previous_adjacency,
                pending_adjacency=pending_adjacency,
                hysteresis_enabled=bool(settings["track_topology_hysteresis_enabled"]),
                switch_score_margin=float(settings["track_topology_switch_score_margin"]),
                switch_confirmation_frames=int(settings["track_topology_switch_confirmation_frames"]),
                station_margin_m=float(settings["track_topology_station_margin_m"]),
            )
        else:
            corridor = infer_ego_corridor_from_boundaries(
                recording,
                lane_geometry,
                member_to_track,
                point,
                float(heading),
                maximum_heading_difference_deg=float(settings["boundary_ego_corridor_maximum_heading_difference_deg"]),
                minimum_corridor_width_m=float(settings["boundary_ego_corridor_minimum_width_m"]),
                maximum_corridor_width_m=float(settings["boundary_ego_corridor_maximum_width_m"]),
                maximum_boundary_distance_m=float(settings["boundary_ego_corridor_maximum_boundary_distance_m"]),
                half_length_m=float(settings["boundary_ego_corridor_half_length_m"]),
                previous_boundary_ids=previous_boundary_ids,
            ) if settings.get("boundary_ego_corridor_enabled", True) else {"valid": False, "method": "boundary_ego_corridor_disabled"}
            frame["inferred_ego_corridor"] = corridor
            if corridor.get("valid"):
                previous_boundary_ids = (corridor.get("left_boundary_id"), corridor.get("right_boundary_id"))
                route_state = route_tracker.observe_corridor(corridor, int(frame.get("frame_index", 0)))
                corridor["inferred_ego_route"] = route_state
                frame["ego_lane"] = {
                    "lane_id": None,
                    "logical_lane_id": route_state["route_id"],
                    "continuous_track_id": None,
                    "method": "connected_inferred_ego_route",
                    "confidence": corridor.get("confidence", "medium"),
                    "source": "inferred_from_physical_boundaries",
                    "inferred": True,
                    "left_boundary_id": corridor.get("left_boundary_id"),
                    "right_boundary_id": corridor.get("right_boundary_id"),
                    "centerline_lcs_m": corridor.get("centerline_lcs_m"),
                    "polygon_lcs_m": corridor.get("polygon_lcs_m"),
                }
                roles = _corridor_role_table(corridor, tracks)
                if corridor.get("left_track_id"):
                    previous_adjacency["left"] = str(corridor["left_track_id"])
                if corridor.get("right_track_id"):
                    previous_adjacency["right"] = str(corridor["right_track_id"])
            else:
                frame["ego_lane"] = {"lane_id": None, "logical_lane_id": None, "continuous_track_id": None, "method": assignment.get("method", "no_constructed_lane_contains_ego"), "confidence": "unknown", "rejected_candidates": assignment.get("rejected_candidates", [])}
                roles = {"ego_track_id": None, "left": {"track_id": None, "method": "not_found"}, "right": {"track_id": None, "method": "not_found"}, "roles": [{"track_id": str(t.get("track_id")), "role": "irrelevant", "member_lane_ids": list(t.get("member_lane_ids", [])), "source": t.get("source", "canonical_continuous_track")} for t in tracks], "active_adjacency_candidates": [], "method": "no_ego_reference_for_roles"}
        frame["lane_roles"] = roles
        frame["continuous_adjacency"] = {"left": roles.get("left", {}), "right": roles.get("right", {}), "candidates": roles.get("active_adjacency_candidates", [])}
        frame["left_lane"] = _lane_output(roles.get("left") or {}, point, track_by_id, lane_by_id)
        frame["right_lane"] = _lane_output(roles.get("right") or {}, point, track_by_id, lane_by_id)
        frame["frame_local_adjacency_debug"] = adjacent_tracks(
            track_id,
            point,
            tracks,
            maximum_heading_difference_deg=float(settings["continuous_track_adjacent_heading_difference_deg"]),
            minimum_lateral_m=float(settings["continuous_track_adjacent_minimum_lateral_m"]),
            maximum_lateral_m=float(settings["continuous_track_adjacent_maximum_lateral_m"]),
            local_window_m=float(settings["continuous_track_adjacent_local_window_m"]),
        )
        for obj in frame.get("objects", []):
            lane_id = obj.get("lane_id")
            if lane_id is not None and str(lane_id) in member_to_track:
                obj["segment_logical_lane_id"] = obj.get("logical_lane_id")
                obj["logical_lane_id"] = member_to_track[str(lane_id)]
                obj["continuous_track_id"] = member_to_track[str(lane_id)]
    result["inferred_ego_routes"] = route_tracker.snapshot()


def run_lane_debug_v2(recording: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = {**DEFAULT_DEBUG, **(config or {})}
    result = copy.deepcopy(run_baseline(recording, config))
    _apply_static_lane_network(recording, result, settings)
    lane_by_id = {str(l.get("lane_id")): l for l in result.get("lane_geometry", [])}
    motion = build_object_motion_evidence(
        recording,
        history_frames=int(settings["object_motion_history_frames"]),
        minimum_displacement_m=float(settings["object_motion_minimum_displacement_m"]),
    )
    angle_samples = []
    for frame in result.get("frames", []):
        fi = frame["frame_index"]
        ego_lane_id = (frame.get("ego_lane") or {}).get("lane_id")
        ego_lane = lane_by_id.get(str(ego_lane_id)) if ego_lane_id is not None else None
        candidates = []
        for obj in frame.get("objects", []):
            obj.update(motion.get((fi, str(obj.get("object_id"))), {"object_motion_heading_rad": None, "object_motion_heading_deg": None, "object_motion_speed_mps": None, "object_motion_source": "unavailable", "object_motion_status": "unavailable"}))
            lane_heading = None
            if ego_lane and obj.get("position_lcs_m"):
                lane_heading = nearest_heading(tuple(obj["position_lcs_m"][:2]), ego_lane.get("centerline_lcs_m", []))
            motion_heading = obj.get("object_motion_heading_rad")
            diff = None
            if lane_heading is not None and motion_heading is not None:
                diff = abs(math.degrees(wrap_angle(float(motion_heading) - float(lane_heading))))
                angle_samples.append(diff)
            obj["ego_lane_heading_at_object_rad"] = lane_heading
            obj["ego_lane_heading_at_object_deg"] = None if lane_heading is None else round(math.degrees(lane_heading), 2)
            obj["lead_direction_difference_deg"] = None if diff is None else round(diff, 2)
            threshold = settings.get("maximum_lead_direction_difference_deg")
            compatibility = "ambiguous" if diff is None else "unthresholded_observation" if threshold is None else "same_direction" if diff <= float(threshold) else "opposite_direction" if diff >= 180.0 - float(threshold) else "crossing_or_diverging"
            obj["lead_direction_compatibility"] = compatibility
            obj["lead_base_candidate"] = _lead_base_candidate(obj, frame, result.get("config", {}))
            eligible = obj["lead_base_candidate"]
            rejection = None
            if eligible and settings.get("lead_direction_filter_mode", "diagnostic") == "enforce":
                if threshold is None:
                    eligible = False
                    rejection = "direction_threshold_not_configured"
                elif compatibility != "same_direction" and not (compatibility == "ambiguous" and not settings.get("reject_ambiguous_stationary_lead", False)):
                    eligible = False
                    rejection = "direction_mismatch_or_ambiguous"
            obj["lead_direction_eligible"] = eligible
            obj["lead_rejection_reason"] = rejection
            if eligible:
                candidates.append(obj)
        candidates.sort(key=lambda x: float(x["longitudinal_m"]))
        frame["lead_candidates_debug"] = [{"object_id": o.get("object_id"), "longitudinal_m": o.get("longitudinal_m"), "direction_difference_deg": o.get("lead_direction_difference_deg"), "direction_compatibility": o.get("lead_direction_compatibility"), "eligible": o.get("lead_direction_eligible"), "rejection_reason": o.get("lead_rejection_reason")} for o in frame.get("objects", []) if o.get("lead_base_candidate")]
        if settings.get("lead_direction_filter_mode") == "enforce":
            frame["lead"] = candidates[0] if candidates else None
            frame["lead_candidate_count"] = len(candidates)
    result["schema_version"] = "lane-debug-v2-static-canonical-plus-gap-recovery-v1"
    result["debug_config"] = settings
    result["lead_direction_angle_samples_deg"] = [round(v, 2) for v in angle_samples]
    result["lead_direction_distribution"] = {"sample_count": len(angle_samples), "minimum_deg": None if not angle_samples else round(min(angle_samples), 2), "maximum_deg": None if not angle_samples else round(max(angle_samples), 2), "note": "Inspect before configuring an enforced lead-direction threshold."}
    return result
