"""Run duplicated production lane-change detector from lane-debug v2 evidence."""
from __future__ import annotations

from typing import Any

from ms_odd_tagging.features.ego_motion import extract_ego_motion_features

from .lane_changes_baseline import LaneChangeDetector


def _apply_lane_id_hysteresis(
    contexts: dict[int, dict[str, Any]],
    frame_indexes: list[int],
    rule: dict[str, Any],
) -> list[dict[str, Any]]:
    """Stabilize ego logical-lane identity before lane-change detection.

    A newly observed non-null lane must persist for ``confirmation_frames``
    consecutive frames before replacing the stable lane. Short null gaps are
    held on the previous stable lane for ``missing_hold_frames``. Raw lane IDs
    remain available in debug fields so suppressed spikes are auditable.
    """
    confirmation_frames = max(1, int(rule.get("lane_id_hysteresis_confirmation_frames", 3)))
    missing_hold_frames = max(0, int(rule.get("lane_id_hysteresis_missing_hold_frames", 2)))

    stable_lane: str | None = None
    pending_lane: str | None = None
    pending_count = 0
    missing_count = 0
    debug: list[dict[str, Any]] = []

    for frame_index in frame_indexes:
        context = contexts.get(frame_index, {})
        raw_lane = context.get("logical_lane_id")
        raw_lane = None if raw_lane is None else str(raw_lane)
        action = "stable"

        if stable_lane is None:
            if raw_lane is None:
                filtered_lane = None
                action = "no_stable_lane"
            else:
                stable_lane = raw_lane
                pending_lane = None
                pending_count = 0
                missing_count = 0
                filtered_lane = stable_lane
                action = "initialize_stable_lane"
        elif raw_lane == stable_lane:
            pending_lane = None
            pending_count = 0
            missing_count = 0
            filtered_lane = stable_lane
            action = "stable"
        elif raw_lane is None:
            pending_lane = None
            pending_count = 0
            missing_count += 1
            if missing_count <= missing_hold_frames:
                filtered_lane = stable_lane
                action = "hold_stable_through_missing"
            else:
                filtered_lane = None
                action = "missing_hold_expired"
        else:
            missing_count = 0
            if raw_lane == pending_lane:
                pending_count += 1
            else:
                pending_lane = raw_lane
                pending_count = 1

            if pending_count >= confirmation_frames:
                previous_stable = stable_lane
                stable_lane = pending_lane
                pending_lane = None
                pending_count = 0
                filtered_lane = stable_lane
                action = f"confirm_switch_from_{previous_stable}"
            else:
                filtered_lane = stable_lane
                action = "hold_stable_pending_switch"

        context["raw_logical_lane_id"] = raw_lane
        context["logical_lane_id"] = filtered_lane
        context["lane_id_hysteresis_action"] = action
        context["lane_id_hysteresis_pending_lane_id"] = pending_lane
        context["lane_id_hysteresis_pending_count"] = pending_count
        context["lane_id_hysteresis_confirmation_frames"] = confirmation_frames
        context["lane_id_hysteresis_missing_hold_frames"] = missing_hold_frames
        debug.append({
            "frame_index": frame_index,
            "raw_logical_lane_id": raw_lane,
            "filtered_logical_lane_id": filtered_lane,
            "stable_logical_lane_id": stable_lane,
            "pending_logical_lane_id": pending_lane,
            "pending_count": pending_count,
            "missing_count": missing_count,
            "action": action,
        })

    return debug


def run_lane_change_debug(
    recording: dict[str, Any],
    following_result: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    frames = recording.get("frames", [])
    features = extract_ego_motion_features(frames)
    source_by_index = {f.get("frame_index"): f for f in frames}
    context: dict[int, dict[str, Any]] = {}
    for item in following_result.get("frames", []):
        fi = item["frame_index"]
        source = source_by_index.get(fi, {})
        topology = {
            k: v
            for k, v in source.items()
            if k.startswith("topology_")
            or k
            in {
                "active_topology_subtype",
                "active_topology_component_id",
                "active_is_intersection",
                "is_intersection_component",
                "ego_inside_topology_polygon",
                "distance_to_topology_polygon_m",
                "component_geometry_confidence",
            }
        }
        context[fi] = {
            **topology,
            "logical_lane_id": (item.get("ego_lane") or {}).get("logical_lane_id"),
            "physical_lane_id": (item.get("ego_lane") or {}).get("lane_id"),
            "left_logical_lane_id": (item.get("left_lane") or {}).get("logical_lane_id"),
            "right_logical_lane_id": (item.get("right_lane") or {}).get("logical_lane_id"),
            "lane_assignment_method": (item.get("ego_lane") or {}).get("method"),
            "lane_assignment_confidence": (item.get("ego_lane") or {}).get("confidence"),
        }

    lane_change_rule = config.get("lane_change_detection", {})
    hysteresis_debug = _apply_lane_id_hysteresis(
        context,
        list(features.frame_index),
        lane_change_rule,
    )

    detector = LaneChangeDetector()
    events = detector.detect(frames, features, config, frame_context=context)
    return {
        "schema_version": "lane-debug-v2-lane-change-tags-v2-hysteresis",
        "recording_id": recording.get("recording_id"),
        "events": [event.to_dict() for event in events],
        "frame_evaluations": getattr(detector, "debug_evaluations", []),
        "lane_id_hysteresis_debug": hysteresis_debug,
        "lane_id_hysteresis_policy": {
            "method": "consecutive_candidate_confirmation_with_missing_hold",
            "confirmation_frames": int(
                lane_change_rule.get("lane_id_hysteresis_confirmation_frames", 3)
            ),
            "missing_hold_frames": int(
                lane_change_rule.get("lane_id_hysteresis_missing_hold_frames", 2)
            ),
            "raw_lane_id_preserved": True,
            "scope": "lane_change_detection_only",
        },
    }
