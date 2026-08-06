"""Per-frame following-lane detector.

States are calculated independently at each original frame. Consecutive frames
with the same scenario state are emitted as inclusive intervals; ``unknown``
and ``not_applicable`` frames always break scenario intervals.
"""

from __future__ import annotations

import math
from typing import Any

from ms_odd_tagging.input_generator.canonical import LEAD_CLASSES

from .lane_geometry import (
    adjacent_lanes,
    assign_point_to_lane,
    build_lane_geometries,
    build_logical_lane_groups,
    build_probable_route_bridges,
    assign_point_to_probable_bridge,
    assign_point_to_probable_route,
    nearest_heading,
    refine_groups_from_observed_ego_path,
    split_adjacent_roles,
    point_in_polygon,
    wrap_angle,
)


DEFAULT_CONFIG = {
    "minimum_moving_speed_mps": 0.5,
    "maximum_lead_distance_m": 80.0,
    "maximum_lane_heading_difference_deg": 60.0,
    "outside_lane_tolerance_m": 1.0,
    "lead_annotation_types": ["dynamic"],
    "probable_lane_max_bounded_extension_m": 65.0,
    "probable_lane_max_unbounded_extension_m": 20.0,
    "probable_lane_max_frame_gap": 80,
    "probable_lane_lateral_padding_m": 0.75,
    "lead_switch_margin_m": 8.0,
    "lead_switch_confirmation_frames": 5,
    "lead_missing_grace_frames": 5,
    "maximum_virtual_lane_curvature_deg": 25.0,
    "maximum_adjacent_lane_heading_difference_deg": 20.0,
    "virtual_only_score_penalty": 1.5,
    "mixed_virtual_score_penalty": 0.35,
    "dashed_drivable_boundary_score_bonus": 0.75,
    "same_logical_lane_score_bonus": 0.9,
    "minimum_recovered_boundary_overlap_m": 3.0,
    "lane_continuation_maximum_gap_m": 15.0,
    "lane_continuation_maximum_lateral_error_m": 1.25,
    "lane_continuation_maximum_heading_difference_deg": 18.0,
    "lane_continuation_maximum_curvature_difference_per_m": 0.08,
    "lane_continuation_maximum_lane_width_difference_m": 0.9,
    "maximum_observed_route_upstream_gap_m": 25.0,
}

SCENARIO_STATES = {"following_lane_with_lead", "following_lane_without_lead"}


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def _successors(topologies: list[dict[str, Any]], lane_id: str | None) -> set[str]:
    if lane_id is None:
        return set()
    return {
        str(item["destination_lane_id"])
        for item in topologies
        if str(item.get("source_lane_id")) == lane_id
        and item.get("validity", {}).get("lane_references_resolve", True)
    }


def segment_states(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    intervals = []
    start = None
    for index, item in enumerate(frames + [{"state": None}]):
        state = item.get("state")
        if start is None and state in SCENARIO_STATES:
            start = index
        if start is not None and (state != frames[start]["state"]):
            first, last = frames[start], frames[index - 1]
            intervals.append(
                {
                    "scenario": first["state"],
                    "start_frame_index": first["frame_index"],
                    "end_frame_index": last["frame_index"],
                    "start_timestamp_unix_s": first["timestamp_unix_s"],
                    "end_timestamp_unix_s": last["timestamp_unix_s"],
                    "start_time_since_start_s": first["time_since_start_s"],
                    "end_time_since_start_s": last["time_since_start_s"],
                    "frame_count": index - start,
                    "boundary_convention": "inclusive_observed_frames",
                }
            )
            start = index if state in SCENARIO_STATES else None
    return intervals


def run_following_lane(recording: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = {**DEFAULT_CONFIG, **(config or {})}
    lanes, topologies = build_lane_geometries(
        recording,
        minimum_recovered_boundary_overlap_m=settings[
            "minimum_recovered_boundary_overlap_m"
        ],
        continuation_maximum_gap_m=settings["lane_continuation_maximum_gap_m"],
        continuation_maximum_lateral_error_m=settings[
            "lane_continuation_maximum_lateral_error_m"
        ],
        continuation_maximum_heading_difference_deg=settings[
            "lane_continuation_maximum_heading_difference_deg"
        ],
        continuation_maximum_curvature_difference_per_m=settings[
            "lane_continuation_maximum_curvature_difference_per_m"
        ],
        continuation_maximum_lane_width_difference_m=settings[
            "lane_continuation_maximum_lane_width_difference_m"
        ],
    )
    logical_lane_ids = build_logical_lane_groups(lanes, topologies)
    observations = []
    previous_lane_id = None
    for frame in recording.get("frames", []):
        ego = frame.get("ego") or {}
        position = ego.get("position_lcs_m") or []
        heading = ego.get("heading_lcs_rad")
        nearby_ids = ((frame.get("ld") or {}).get("nearby_feature_ids") or {}).get("lanes", [])
        if len(position) < 2 or not all(_finite(value) for value in position[:2]) or not _finite(heading):
            ego_assignment = {"lane_id": None, "confidence": "unknown", "method": "invalid_ego_pose", "candidates": []}
        else:
            ego_assignment = assign_point_to_lane(
                (float(position[0]), float(position[1])), float(heading), nearby_ids, lanes,
                maximum_heading_difference_deg=settings["maximum_lane_heading_difference_deg"],
                outside_lane_tolerance_m=settings["outside_lane_tolerance_m"],
                previous_lane_id=previous_lane_id, successor_ids=_successors(topologies, previous_lane_id),
                logical_lane_ids=logical_lane_ids,
                preferred_logical_lane_id=logical_lane_ids.get(previous_lane_id),
                same_logical_lane_score_bonus=settings["same_logical_lane_score_bonus"],
                virtual_only_score_penalty=settings["virtual_only_score_penalty"],
                mixed_virtual_score_penalty=settings["mixed_virtual_score_penalty"],
                dashed_drivable_boundary_score_bonus=settings["dashed_drivable_boundary_score_bonus"],
                maximum_virtual_lane_curvature_deg=settings["maximum_virtual_lane_curvature_deg"],
            )
        ego_lane_id = ego_assignment.get("lane_id")
        ego_assignment["logical_lane_id"] = logical_lane_ids.get(ego_lane_id)
        ego_assignment["intersection_connector"] = bool(
            ego_lane_id and lanes[ego_lane_id].intersection_connector
        )
        if ego_lane_id:
            previous_lane_id = ego_lane_id
            adjacency = adjacent_lanes(
                ego_lane_id,
                (float(position[0]), float(position[1])),
                float(heading),
                nearby_ids,
                lanes,
                maximum_virtual_lane_curvature_deg=settings[
                    "maximum_virtual_lane_curvature_deg"
                ],
                maximum_same_direction_heading_difference_deg=settings[
                    "maximum_adjacent_lane_heading_difference_deg"
                ],
            )
        else:
            adjacency = {"left": {"lane_id": None, "method": "ego_lane_unknown"}, "right": {"lane_id": None, "method": "ego_lane_unknown"}}
        for side in ("left", "right"):
            adjacent_id = adjacency[side].get("lane_id")
            adjacency[side]["logical_lane_id"] = logical_lane_ids.get(adjacent_id)
            adjacency[side]["intersection_connector"] = bool(
                adjacent_id and lanes[adjacent_id].intersection_connector
            )

        object_assignments = []
        lead_candidates = []
        for obj in frame.get("objects", []):
            object_position = obj.get("position_lcs_m") or []
            if len(object_position) < 2 or not all(_finite(value) for value in object_position[:2]):
                assignment = {"lane_id": None, "confidence": "unknown", "method": "invalid_object_pose", "candidates": []}
            else:
                assignment = assign_point_to_lane(
                    (float(object_position[0]), float(object_position[1])), None, nearby_ids, lanes,
                    maximum_heading_difference_deg=180.0,
                    outside_lane_tolerance_m=settings["outside_lane_tolerance_m"],
                    virtual_only_score_penalty=settings["virtual_only_score_penalty"],
                    mixed_virtual_score_penalty=settings["mixed_virtual_score_penalty"],
                    dashed_drivable_boundary_score_bonus=settings["dashed_drivable_boundary_score_bonus"],
                    maximum_virtual_lane_curvature_deg=settings["maximum_virtual_lane_curvature_deg"],
                )
            relative = obj.get("position_ego_m") or {}
            entry = {
                "object_id": str(obj.get("object_id")), "class": obj.get("class"),
                "annotation_type": obj.get("annotation_type"), "lane_id": assignment.get("lane_id"),
                "logical_lane_id": logical_lane_ids.get(assignment.get("lane_id")),
                "lane_confidence": assignment.get("confidence"), "lane_method": assignment.get("method"),
                "inside_exact_lane_polygon": bool(assignment.get("inside_polygon")),
                "longitudinal_m": relative.get("longitudinal"), "lateral_m": relative.get("lateral"),
                "position_lcs_m": object_position[:2] if len(object_position) >= 2 else None,
            }
            object_assignments.append(entry)
            longitudinal = relative.get("longitudinal")
            if (
                ego_lane_id
                and entry["logical_lane_id"] == logical_lane_ids.get(ego_lane_id)
                and obj.get("class") in LEAD_CLASSES
                and obj.get("annotation_type") in settings["lead_annotation_types"]
                and _finite(longitudinal) and 0.0 < longitudinal <= settings["maximum_lead_distance_m"]
            ):
                lead_candidates.append(entry)
        lead_candidates.sort(key=lambda item: item["longitudinal_m"])
        lead = lead_candidates[0] if lead_candidates else None
        speed = ego.get("speed_mps")
        if not _finite(speed):
            state, reason = "unknown", "invalid_or_missing_speed"
        elif speed < settings["minimum_moving_speed_mps"]:
            state, reason = "not_applicable", "ego_below_moving_speed"
        elif ego_lane_id is None:
            state, reason = "unknown", "ego_lane_unknown"
        elif lead:
            state, reason = "following_lane_with_lead", "nearest_dynamic_vehicle_ahead_in_ego_lane"
        else:
            state, reason = "following_lane_without_lead", "no_dynamic_vehicle_ahead_in_ego_lane"
        observations.append(
            {
                "frame_index": frame["frame_index"], "timestamp_unix_s": frame["timestamp_unix_s"],
                "time_since_start_s": frame["time_since_start_s"], "speed_mps": speed,
                "state": state, "reason": reason, "ego_lane": ego_assignment,
                "left_lane": adjacency["left"], "right_lane": adjacency["right"],
                "lead": lead, "lead_candidate_count": len(lead_candidates),
                "objects": object_assignments,
            }
        )
    logical_lane_ids = refine_groups_from_observed_ego_path(
        lanes,
        topologies,
        logical_lane_ids,
        [(item["frame_index"], item["ego_lane"].get("lane_id")) for item in observations],
        maximum_upstream_topology_gap_m=settings[
            "maximum_observed_route_upstream_gap_m"
        ],
    )
    probable_bridges = build_probable_route_bridges(
        lanes,
        logical_lane_ids,
        maximum_gap_m=float(settings["probable_lane_max_bounded_extension_m"]),
    )
    source_frames = {frame["frame_index"]: frame for frame in recording.get("frames", [])}

    def neighboring_known_groups(role: str) -> tuple[list[tuple[int, str] | None], list[tuple[int, str] | None]]:
        previous_values = []
        previous = None
        for item in observations:
            lane_id = item[role].get("lane_id")
            if lane_id and logical_lane_ids.get(lane_id):
                previous = (item["frame_index"], logical_lane_ids[lane_id])
            previous_values.append(previous)
        next_values = [None] * len(observations)
        following = None
        for index in range(len(observations) - 1, -1, -1):
            item = observations[index]
            lane_id = item[role].get("lane_id")
            if lane_id and logical_lane_ids.get(lane_id):
                following = (item["frame_index"], logical_lane_ids[lane_id])
            next_values[index] = following
        return previous_values, next_values

    def probable_target(index: int, previous, following) -> tuple[str | None, float, str]:
        frame_index = observations[index]["frame_index"]
        maximum_gap = int(settings["probable_lane_max_frame_gap"])
        if (
            previous and following and previous[1] == following[1]
            and frame_index - previous[0] <= maximum_gap
            and following[0] - frame_index <= maximum_gap
        ):
            return previous[1], float(settings["probable_lane_max_bounded_extension_m"]), "bounded_by_same_route"
        if previous and frame_index - previous[0] <= 20:
            return previous[1], float(settings["probable_lane_max_unbounded_extension_m"]), "continued_from_previous_route"
        if following and following[0] - frame_index <= 20:
            return following[1], float(settings["probable_lane_max_unbounded_extension_m"]), "continued_to_next_route"
        return None, 0.0, "no_route_constraint"

    ego_previous, ego_following = neighboring_known_groups("ego_lane")
    for index, item in enumerate(observations):
        if item["ego_lane"].get("lane_id") is not None:
            continue
        source = source_frames[item["frame_index"]]
        position = (source.get("ego") or {}).get("position_lcs_m") or []
        heading = (source.get("ego") or {}).get("heading_lcs_rad")
        continuity = ego_previous[index] or ego_following[index]
        if len(position) >= 2 and _finite(heading):
            bridge_assignment = assign_point_to_probable_bridge(
                (float(position[0]), float(position[1])),
                float(heading),
                probable_bridges,
                lanes,
                preferred_logical_lane_id=continuity[1] if continuity else None,
            )
            if bridge_assignment:
                item["ego_lane"] = bridge_assignment
                continue
        route_id, extension_m, constraint = probable_target(index, ego_previous[index], ego_following[index])
        if route_id and len(position) >= 2 and _finite(heading):
            probable = assign_point_to_probable_route(
                (float(position[0]), float(position[1])), float(heading), route_id, lanes, logical_lane_ids,
                maximum_extension_m=extension_m,
                lateral_padding_m=float(settings["probable_lane_lateral_padding_m"]),
            )
            if probable:
                probable["route_constraint"] = constraint
                probable["intersection_connector"] = lanes[probable["lane_id"]].intersection_connector
                item["ego_lane"] = probable

    # Preserve left/right corridors through the same bounded map gaps. Querying
    # an offset point retains the side relationship instead of copying ego.
    for role, lateral_sign in (("left_lane", 1.0), ("right_lane", -1.0)):
        role_previous, role_following = neighboring_known_groups(role)
        for index, item in enumerate(observations):
            if item[role].get("lane_id") is not None:
                continue
            route_id, extension_m, constraint = probable_target(index, role_previous[index], role_following[index])
            source = source_frames[item["frame_index"]]
            ego = source.get("ego") or {}
            position, heading = ego.get("position_lcs_m") or [], ego.get("heading_lcs_rad")
            if not route_id or len(position) < 2 or not _finite(heading):
                continue
            query = (
                float(position[0]) - math.sin(float(heading)) * 3.5 * lateral_sign,
                float(position[1]) + math.cos(float(heading)) * 3.5 * lateral_sign,
            )
            probable = assign_point_to_probable_route(
                query, float(heading), route_id, lanes, logical_lane_ids,
                maximum_extension_m=extension_m,
                lateral_padding_m=float(settings["probable_lane_lateral_padding_m"]),
            )
            if probable:
                probable["route_constraint"] = constraint
                probable["intersection_connector"] = lanes[probable["lane_id"]].intersection_connector
                item[role] = probable

    for item in observations:
        ego_lane_id = item["ego_lane"].get("lane_id")
        item["ego_lane"]["logical_lane_id"] = logical_lane_ids.get(ego_lane_id)
        for side in ("left_lane", "right_lane"):
            item[side]["logical_lane_id"] = logical_lane_ids.get(item[side].get("lane_id"))
        source = source_frames[item["frame_index"]]
        ego = source.get("ego") or {}
        position = ego.get("position_lcs_m") or []
        if ego_lane_id and len(position) >= 2:
            split_roles = split_adjacent_roles(
                ego_lane_id,
                (float(position[0]), float(position[1])),
                lanes,
                topologies,
                logical_lane_ids,
            )
            for side, candidate in split_roles.items():
                role = f"{side}_lane"
                if item[role].get("lane_id") != candidate["lane_id"]:
                    item[role]["replaced_by_split_lane_id"] = candidate["lane_id"]
                    item[role] = candidate
        if ego_lane_id and len(position) >= 2:
            ego_lane_heading = nearest_heading(
                (float(position[0]), float(position[1])),
                lanes[ego_lane_id].centerline,
            )
            for side in ("left_lane", "right_lane"):
                adjacent_id = item[side].get("lane_id")
                if not adjacent_id or adjacent_id not in lanes:
                    continue
                adjacent_heading = nearest_heading(
                    (float(position[0]), float(position[1])),
                    lanes[adjacent_id].centerline,
                )
                if ego_lane_heading is None or adjacent_heading is None:
                    continue
                difference = abs(
                    math.degrees(wrap_angle(adjacent_heading - ego_lane_heading))
                )
                threshold = float(
                    settings["maximum_adjacent_lane_heading_difference_deg"]
                )
                relation = (
                    "same_direction"
                    if difference <= threshold
                    else "opposite_direction"
                    if difference >= 180.0 - threshold
                    else "crossing_or_diverging"
                )
                item[side].update(
                    {
                        "same_direction_as_ego": relation == "same_direction",
                        "direction_relation": relation,
                        "heading_difference_deg": round(difference, 2),
                        "maximum_same_direction_heading_difference_deg": threshold,
                    }
                )
                if relation != "same_direction":
                    item[side].update(
                        {
                            "rejected_lane_id": adjacent_id,
                            "rejected_logical_lane_id": item[side].get(
                                "logical_lane_id"
                            ),
                            "direction_source_method": item[side].get("method"),
                            "lane_id": None,
                            "logical_lane_id": None,
                            "method": "direction_mismatch_rejected",
                            "confidence": "rejected",
                        }
                    )
        for side in ("left_lane", "right_lane"):
            if (
                item["ego_lane"].get("logical_lane_id")
                and item[side].get("logical_lane_id") == item["ego_lane"]["logical_lane_id"]
            ):
                item[side]["rejected_lane_id"] = item[side].get("lane_id")
                item[side]["lane_id"] = None
                item[side]["logical_lane_id"] = None
                item[side]["method"] = "same_route_lane_as_ego_rejected"
                item[side]["confidence"] = "unknown"
        if (
            item["left_lane"].get("logical_lane_id")
            and item["left_lane"].get("logical_lane_id") == item["right_lane"].get("logical_lane_id")
        ):
            item["right_lane"]["rejected_lane_id"] = item["right_lane"].get("lane_id")
            item["right_lane"]["lane_id"] = None
            item["right_lane"]["logical_lane_id"] = None
            item["right_lane"]["method"] = "duplicate_adjacent_route_lane_rejected"
            item["right_lane"]["confidence"] = "unknown"
        for obj in item["objects"]:
            obj["logical_lane_id"] = logical_lane_ids.get(obj.get("lane_id"))
            ego_route_id = item["ego_lane"].get("logical_lane_id")
            exact_ego_lane = bool(
                ego_route_id
                and obj.get("logical_lane_id") == ego_route_id
                and obj.get("inside_exact_lane_polygon")
            )
            matching_bridge = None
            if ego_route_id and obj.get("position_lcs_m"):
                point = tuple(obj["position_lcs_m"])
                matching_bridge = next(
                    (
                        bridge
                        for bridge in probable_bridges
                        if bridge["logical_lane_id"] == ego_route_id
                        and point_in_polygon(point, bridge["polygon_lcs_m"])
                    ),
                    None,
                )
            obj["inside_ego_lane_area"] = exact_ego_lane or matching_bridge is not None
            obj["ego_lane_area_source"] = (
                "exact_lane_polygon"
                if exact_ego_lane
                else "probable_lane_bridge"
                if matching_bridge is not None
                else None
            )
            if matching_bridge is not None and not exact_ego_lane:
                obj["logical_lane_id"] = ego_route_id
                obj["lane_confidence"] = "probable"
                obj["lane_method"] = "inside_directed_lane_boundary_bridge"
                obj["probable_area"] = True
                obj["probable_bridge_source_lane_id"] = matching_bridge["source_lane_id"]
                obj["probable_bridge_destination_lane_id"] = matching_bridge["destination_lane_id"]
        lead_candidates = [
            obj
            for obj in item["objects"]
            if ego_lane_id
            and obj["logical_lane_id"] == logical_lane_ids.get(ego_lane_id)
            and obj.get("inside_ego_lane_area") is True
            and obj.get("class") in LEAD_CLASSES
            and obj.get("annotation_type") in settings["lead_annotation_types"]
            and _finite(obj.get("longitudinal_m"))
            and 0.0 < obj["longitudinal_m"] <= settings["maximum_lead_distance_m"]
        ]
        lead_candidates.sort(key=lambda obj: obj["longitudinal_m"])
        item["lead"] = lead_candidates[0] if lead_candidates else None
        item["lead_candidate_count"] = len(lead_candidates)
        item["_lead_candidates"] = lead_candidates
        speed = item.get("speed_mps")
        if not _finite(speed):
            item["state"], item["reason"] = "unknown", "invalid_or_missing_speed"
        elif speed < settings["minimum_moving_speed_mps"]:
            item["state"], item["reason"] = "not_applicable", "ego_below_moving_speed"
        elif ego_lane_id is None:
            item["state"], item["reason"] = "unknown", "ego_lane_unknown"
        elif item["lead"]:
            item["state"], item["reason"] = "following_lane_with_lead", "nearest_dynamic_vehicle_ahead_in_ego_route_lane"
        else:
            item["state"], item["reason"] = "following_lane_without_lead", "no_dynamic_vehicle_ahead_in_ego_route_lane"

    tracked_id = None
    tracked_lead = None
    missing_frames = 0
    pending_id = None
    pending_frames = 0
    for item in observations:
        candidates = item.pop("_lead_candidates")
        by_id = {candidate["object_id"]: candidate for candidate in candidates}
        nearest = candidates[0] if candidates else None
        current = by_id.get(tracked_id) if tracked_id else None
        if tracked_id is None:
            selected = nearest
            tracked_id = selected["object_id"] if selected else None
            tracked_lead = selected
            missing_frames = 0
        elif current is not None:
            selected = current
            missing_frames = 0
            if (
                nearest is not None
                and nearest["object_id"] != tracked_id
                and nearest["longitudinal_m"] + settings["lead_switch_margin_m"] < current["longitudinal_m"]
            ):
                if pending_id == nearest["object_id"]:
                    pending_frames += 1
                else:
                    pending_id, pending_frames = nearest["object_id"], 1
                if pending_frames >= int(settings["lead_switch_confirmation_frames"]):
                    selected = nearest
                    tracked_id = nearest["object_id"]
                    pending_id, pending_frames = None, 0
            else:
                pending_id, pending_frames = None, 0
            tracked_lead = selected
        else:
            missing_frames += 1
            if (
                tracked_lead is not None
                and tracked_lead.get("logical_lane_id") == item["ego_lane"].get("logical_lane_id")
                and tracked_lead.get("inside_ego_lane_area") is True
                and missing_frames <= int(settings["lead_missing_grace_frames"])
            ):
                selected = {
                    **tracked_lead,
                    "tracking_status": "held_through_missing_observation",
                    "tracking_age_frames": missing_frames,
                }
            else:
                selected = nearest
                tracked_id = selected["object_id"] if selected else None
                tracked_lead = selected
                missing_frames = 0
                pending_id, pending_frames = None, 0
        if selected is not None and "tracking_status" not in selected:
            selected = {**selected, "tracking_status": "observed_stable_track", "tracking_age_frames": 0}
        item["lead"] = selected
        if item["state"] not in {"unknown", "not_applicable"}:
            if selected:
                item["state"] = "following_lane_with_lead"
                item["reason"] = "temporally_stable_lead_in_ego_route_lane"
            else:
                item["state"] = "following_lane_without_lead"
                item["reason"] = "no_stable_lead_in_ego_route_lane"

    return {
        "schema_version": "following-lane-frame-tags-v1",
        "recording_id": recording.get("recording_id"),
        "config": settings,
        "interval_boundary_convention": "inclusive_observed_frames",
        "lane_geometry": [
            {**lane.as_dict(), "logical_lane_id": logical_lane_ids[lane.lane_id]}
            for lane in lanes.values()
        ],
        "probable_lane_bridges": probable_bridges,
        "frames": observations,
        "intervals": segment_states(observations),
    }
