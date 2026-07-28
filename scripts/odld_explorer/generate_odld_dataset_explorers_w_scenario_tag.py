#!/usr/bin/env python3
"""Generate tagged interactive OD + LD + ego-trajectory explorers.

The established OD explorer supplies the interaction shell.  This generator
adds the complete recording-level LD map once, compact per-frame nearby-ID
highlights, LD context readouts, scenario-tag overlays, and synchronized
LD/scenario timelines.
"""

from __future__ import annotations

import argparse
import gc
import html
import json
import math
import re
from collections import Counter
from pathlib import Path

import generate_dataset_explorers as base
from ms_odd_tagging.features.road_feature_relations import (
    build_road_feature_relations,
)
from ms_odd_tagging.features.object_relations import build_object_relations
from ms_odd_tagging.features.object_path_crossing_relations import (
    build_object_path_crossing_relations,
)
from ms_odd_tagging.tagger.rule_based.registry import (
    detect_recording_events,
    load_config,
)


DEFAULT_SOURCE_ROOT = Path(
    "2600_MV2_ODLD_traj_annotations/2600_MV2_ODLD_traj_annotations"
)
DEFAULT_CANONICAL_DIR = Path(
    "quick_exploration_outputs/scenario_tagging_pipeline_odld/01_canonical_frames"
)
DEFAULT_WINDOW_DIR = Path(
    "quick_exploration_outputs/scenario_tagging_pipeline_odld/02_motional_windows"
)
DEFAULT_OUTPUT_DIR = Path(
    "quick_exploration_outputs/dataset_scene_explorers_odld_w_scenario_tag"
)
DEFAULT_INDEX_PATH = Path(
    "quick_exploration_outputs/dataset_odld_explorer_w_scenario_tag_index.html"
)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f"Unable to inject {label}: expected one marker, found {text.count(old)}")
    return text.replace(old, new, 1)


def quaternion_available(bbox: dict) -> bool:
    values = [bbox.get(key) for key in ("qx", "qy", "qz", "qw")]
    return all(
        isinstance(value, (int, float)) and math.isfinite(value) for value in values
    ) and sum(float(value) ** 2 for value in values) > 1e-12


def object_payload(obj: dict) -> dict:
    """Extend the established explorer payload with explicit yaw validity."""
    payload = base.object_payload(obj)
    payload["yawAvailable"] = quaternion_available(obj.get("bbox3d") or {})
    if payload.get("frames"):
        validity_by_frame = {}
        for key, frame in (obj.get("frames") or {}).items():
            bbox = frame.get("bbox3d")
            if bbox:
                validity_by_frame[int(frame.get("frameIndex", key))] = (
                    quaternion_available(bbox)
                )
        payload["yawValids"] = [
            validity_by_frame.get(frame_index, False)
            for frame_index in payload["frames"]
        ]
    return payload


def build_base_data(scene_dir: Path) -> dict:
    with (scene_dir / "annotations_OD.json").open(encoding="utf-8") as handle:
        annotations = json.load(handle)
    trajectory = base.load_traj(scene_dir / "traj_lcs.txt")
    objects = [object_payload(obj) for obj in annotations.get("objects", [])]
    class_counts = Counter(obj["className"] for obj in objects)
    return {
        "summary": {
            "recording": annotations.get("scene", {}).get("name", scene_dir.name),
            "scene": annotations.get("scene", {}),
            "frames": len(trajectory["rel_t"]),
            "durationSec": trajectory["rel_t"][-1] if trajectory["rel_t"] else 0,
            "objects": len(objects),
            "movingTracks": sum(1 for obj in objects if "frames" in obj),
            "classCounts": dict(class_counts.most_common()),
            "speedMinMeanMax": [
                min(trajectory["speed"]),
                sum(trajectory["speed"]) / len(trajectory["speed"]),
                max(trajectory["speed"]),
            ],
        },
        "trajectory": trajectory,
        "objects": objects,
    }


def compact_tag_evidence(value: object) -> object:
    """Keep tag hover text useful without embedding raw per-frame evidence."""
    if isinstance(value, dict):
        preferred = (
            "median_speed_mps",
            "median_ego_speed_mps",
            "peak_abs_lateral_acceleration_mps2",
            "peak_jerk_mps3",
            "signed_heading_delta_rad",
            "peak_signed_yaw_rate_rad_s",
            "median_early_turn_speed_mps",
            "physical_turn_event_id",
            "same_logical_lane",
            "logical_lane_ids",
            "threshold_mode",
            "minimum_accumulated_heading_change_rad",
            "physical_lane_change_event_id",
            "source_logical_lane_id",
            "target_logical_lane_id",
            "direction",
            "transition_frame",
            "source_stable_start_frame",
            "target_stable_end_frame",
            "road_feature_event_id",
            "crosswalk_id",
            "stopline_id",
            "source_feature_ids",
            "entry_frame",
            "exit_confirmation_frame",
            "crossing_progress_m",
            "stationary_relation",
            "distance_m",
            "initial_distance_m",
            "final_distance_m",
            "initial_speed_mps",
            "final_speed_mps",
            "peak_deceleration_mps2",
            "peak_acceleration_mps2",
            "final_relation",
            "acceleration_began_relation",
            "association_distance_m",
            "association_orientation_difference_deg",
            "association_confidence",
            "association_valid",
            "object_interaction_event_id",
            "object_track_ids",
            "source_object_ids",
            "object_classes",
            "object_class",
            "bbox_dimensions_m",
            "classification_reason",
            "normalized_category",
            "minimum_required_count",
            "peak_simultaneous_count",
            "minimum_footprint_distance_m",
            "representative_frame",
            "peak_object_speed_mps",
            "representative_object_speed_mps",
            "speed_definition",
            "velocity_sources",
            "pedestrian_crosswalk_event_id",
            "crosswalk_ids",
            "pedestrian_track_ids",
            "pedestrian_ids",
            "peak_pedestrian_count",
            "minimum_distance_m",
            "maximum_crosswalk_overlap_ratio",
            "ego_crosswalk_relation",
            "pedestrian_crosswalk_relation",
            "same_crosswalk_required",
            "object_path_crossing_event_id",
            "object_track_id",
            "original_class",
            "crossing_direction",
            "initial_side",
            "final_side",
            "arc_entry_frame",
            "arc_exit_frame",
            "source_side_confirmation_frame",
            "approach_start_frame",
            "target_side_confirmation_frame",
            "minimum_path_distance_m",
            "lateral_displacement_m",
            "ground_displacement_m",
            "representative_speed_mps",
            "representative_path_normal_speed_mps",
            "arc_dwell_duration_s",
            "directional_motion_fraction",
            "projected_intersection_confirmations",
            "projected_intersection_lcs_m",
            "intersection_path_progress_m",
            "crossing_angle_deg",
            "object_heading_lcs_rad",
            "heading_motion_difference_deg",
            "ego_time_to_intersection_s",
            "object_time_to_intersection_s",
            "time_to_intersection_difference_s",
            "forward_arc",
        )
        return {key: value[key] for key in preferred if key in value}
    if isinstance(value, list):
        return [compact_tag_evidence(item) for item in value[:3]]
    return value


def tag_event_payload(event: dict) -> dict:
    return {
        "scenario": event["scenario"],
        "startFrame": event["start_frame"],
        "endFrame": event["end_frame"],
        "startTime": event["start_timestamp_s"],
        "endTime": event["end_timestamp_s"],
        "durationSec": event.get("duration_s"),
        "confidence": event.get("confidence"),
        "detectorVersion": event.get("detector_version"),
        "evidence": compact_tag_evidence(event.get("evidence") or {}),
        "source": event.get("source", "rule_based"),
    }


def build_tag_payload(recording: str, window_dir: Path, canonical: dict) -> dict:
    """Load or regenerate dynamic recording-level rule-based events.

    Event bounds use inclusive first/last samples. Legacy overlapping five-second
    candidate windows are never used for visualization tags.
    """
    candidates = [
        window_dir / f"{recording}_motional_windows_odld.json",
        window_dir / f"{recording}_motional_windows.json",
    ]
    source_path = next((path for path in candidates if path.is_file()), None)
    windows = {}
    if source_path is not None:
        with source_path.open(encoding="utf-8") as handle:
            windows = json.load(handle)

    config = load_config()
    rule_events = windows.get("rule_based_events") or []
    saved_config_version = windows.get("rule_config_version")
    if rule_events and saved_config_version == config["config_version"]:
        events = [tag_event_payload(event) for event in rule_events]
        source_kind = "recording_rule_based_events"
        config_version = saved_config_version
    else:
        detected, _ = detect_recording_events(canonical, config)
        events = [tag_event_payload(event.to_dict()) for event in detected]
        source_kind = (
            "canonical_per_frame_rule_events_stale_window_replaced"
            if rule_events
            else "canonical_per_frame_rule_events"
        )
        config_version = config["config_version"]

    scenarios = sorted({event["scenario"] for event in events})
    return {
        "available": bool(events),
        "source": source_path.name if source_path is not None else None,
        "sourceKind": source_kind,
        "configVersion": config_version,
        "scenarios": scenarios,
        "events": events,
    }


def build_road_feature_payload(canonical: dict) -> dict:
    """Compact the reusable relation layer for synchronized map debugging."""
    config = load_config()
    payload = build_road_feature_relations(
        canonical, config["road_feature_relations"]
    )
    tracks = [
        {
            "trackId": track["track_id"],
            "featureType": track["feature_type"],
            "sourceFeatureIds": track.get("source_feature_ids", []),
            "x": [point[0] for point in track.get("polygon_lcs_m", [])],
            "y": [point[1] for point in track.get("polygon_lcs_m", [])],
            "center": track.get("center_lcs_m"),
            "confidence": track.get("confidence"),
        }
        for track in payload.get("tracks", [])
    ]

    def compact_relation(relation: dict) -> dict:
        return {
            "trackId": relation.get("track_id"),
            "state": relation.get("state"),
            "signedDistanceM": relation.get("signed_longitudinal_distance_m"),
            "lateralOffsetM": relation.get("lateral_offset_m"),
            "nearestDistanceM": relation.get("nearest_geometry_distance_m"),
            "overlap": relation.get("ego_footprint_overlap") is True,
            "pathCompatible": relation.get("path_compatible") is True,
            "valid": relation.get("relation_valid") is True,
            "observed": relation.get("observed_this_frame") is True,
        }

    frames = [
        {
            "frameIndex": frame["frame_index"],
            "time": frame.get("time_since_start_s"),
            "crosswalks": [
                compact_relation(relation)
                for relation in frame.get("crosswalk_relations", [])
            ],
            "stoplines": [
                compact_relation(relation)
                for relation in frame.get("stopline_relations", [])
            ],
        }
        for frame in payload.get("frames", [])
    ]
    associations = [
        {
            "stoplineTrackId": item.get("stopline_track_id"),
            "crosswalkTrackId": item.get("crosswalk_track_id"),
            "valid": item.get("valid") is True,
            "status": item.get("status"),
            "confidence": item.get("confidence"),
            "geometryDistanceM": item.get("geometry_distance_m"),
            "orientationDifferenceDeg": item.get(
                "orientation_difference_deg"
            ),
        }
        for item in payload.get("stopline_crosswalk_associations", [])
    ]
    return {
        "schemaVersion": payload.get("schema_version"),
        "configVersion": config["config_version"],
        "egoFootprint": payload.get("ego_footprint"),
        "tracks": tracks,
        "frames": frames,
        "associations": associations,
    }


def build_object_relation_payload(canonical: dict) -> dict:
    """Compact normalized object relations for synchronized map debugging."""
    config = load_config()
    payload = build_object_relations(canonical, config["object_relations"])
    canonical_frames = {
        frame["frame_index"]: frame for frame in canonical.get("frames", [])
    }

    def compact_frame(frame: dict) -> dict:
        raw_frame = canonical_frames.get(frame["frame_index"], {})
        raw_by_id = {
            str(item.get("object_id")): item
            for item in raw_frame.get("objects", [])
            if item.get("object_id") not in (None, "")
        }
        objects = []
        for item in frame["objects"]:
            raw = raw_by_id.get(str(item.get("source_object_id")), {})
            velocity = raw.get("velocity_lcs_mps")
            valid_velocity = (
                isinstance(velocity, (list, tuple))
                and len(velocity) >= 2
                and all(
                    isinstance(value, (int, float)) and math.isfinite(value)
                    for value in velocity[:2]
                )
            )
            objects.append(
                {
                    "trackId": item["track_id"],
                    "sourceObjectId": item["source_object_id"],
                    "className": item["class_name"],
                    "category": item["normalized_category"],
                    "annotationType": item.get("annotation_type"),
                    "x": item["center_lcs_m"][0],
                    "y": item["center_lcs_m"][1],
                    "distanceM": item["nearest_footprint_distance_m"],
                    "longitudinalM": item["signed_longitudinal_m"],
                    "lateralM": item["signed_lateral_m"],
                    "inside": item["inside_proximity_region"],
                    "speedMps": item["object_speed_mps"],
                    "velocityX": (
                        base.compact_float(float(velocity[0]))
                        if valid_velocity
                        else None
                    ),
                    "velocityY": (
                        base.compact_float(float(velocity[1]))
                        if valid_velocity
                        else None
                    ),
                    "velocitySource": item["velocity_source"],
                    "longVehicle": item["long_vehicle"],
                    "longVehicleReason": item["long_vehicle_reason"],
                    "trackAgeS": item["track_age_s"],
                }
            )
        return {
            "frameIndex": frame["frame_index"],
            "time": frame["time_since_start_s"],
            "objects": objects,
        }

    return {
        "schemaVersion": payload["schema_version"],
        "configVersion": config["config_version"],
        "proximityRegion": payload["proximity_region"],
        "tracks": [
            {
                "trackId": track["track_id"],
                "sourceObjectIds": track.get("source_object_ids", []),
                "category": track["normalized_category"],
                "classes": track.get("class_names", []),
                "idSwitchCount": track.get("id_switch_count", 0),
                "duplicateAliasIds": track.get("duplicate_alias_ids", []),
            }
            for track in payload["tracks"]
        ],
        "frames": [compact_frame(frame) for frame in payload["frames"]],
    }


def build_object_path_crossing_payload(canonical: dict) -> dict:
    """Compact forward future-path crossing relations for map debugging."""
    config = load_config()
    objects = build_object_relations(canonical, config["object_relations"])
    settings = {
        **config["object_path_crossing_interactions"],
        "maximum_plausible_object_speed_mps": config["object_relations"][
            "maximum_physically_plausible_object_speed_mps"
        ],
    }
    payload = build_object_path_crossing_relations(
        canonical, objects, settings
    )
    trajectories: dict[str, dict] = {}
    compact_frames = []
    for frame in payload.get("frames", []):
        compact_objects = []
        for item in frame.get("objects", []):
            compact = {
                "trackId": item.get("track_id"),
                "className": item.get("class_name"),
                "category": item.get("normalized_category"),
                "x": (item.get("center_lcs_m") or [None, None])[0],
                "y": (item.get("center_lcs_m") or [None, None])[1],
                "nearestX": (
                    (item.get("nearest_point_lcs_m") or [None, None])[0]
                ),
                "nearestY": (
                    (item.get("nearest_point_lcs_m") or [None, None])[1]
                ),
                "signedLateralM": item.get("signed_lateral_distance_m"),
                "pathDistanceM": item.get("nearest_path_distance_m"),
                "pathProgressM": item.get("longitudinal_progress_m"),
                "inside": item.get("inside_forward_arc") is True,
                "arcBearingDeg": item.get("arc_bearing_deg"),
                "arcRangeM": item.get("arc_range_m"),
                "side": item.get("side"),
                "state": item.get("state"),
                "valid": item.get("relation_valid") is True,
                "pathNormalSpeedMps": item.get("path_normal_speed_mps"),
                "speedMps": item.get("object_speed_mps"),
                "velocitySource": item.get("velocity_source"),
                "projectedIntersectionValid": item.get(
                    "projected_intersection_valid"
                )
                is True,
                "projectionRejectionReason": item.get(
                    "projection_rejection_reason"
                ),
                "intersectionX": (
                    (item.get("projected_intersection_lcs_m") or [None, None])[0]
                ),
                "intersectionY": (
                    (item.get("projected_intersection_lcs_m") or [None, None])[1]
                ),
                "crossingAngleDeg": item.get("crossing_angle_deg"),
                "egoTtiS": item.get("ego_time_to_intersection_s"),
                "objectTtiS": item.get("object_time_to_intersection_s"),
                "ttiDifferenceS": item.get(
                    "time_to_intersection_difference_s"
                ),
            }
            compact_objects.append(compact)
            trajectory = trajectories.setdefault(
                str(item.get("track_id")),
                {
                    "className": item.get("class_name"),
                    "category": item.get("normalized_category"),
                    "x": [],
                    "y": [],
                    "frameIndex": [],
                },
            )
            if compact["x"] is not None and compact["y"] is not None:
                trajectory["x"].append(compact["x"])
                trajectory["y"].append(compact["y"])
                trajectory["frameIndex"].append(frame["frame_index"])
        compact_frames.append(
            {
                "frameIndex": frame["frame_index"],
                "time": frame.get("time_since_start_s"),
                "pathStartFrame": frame.get("path_start_frame"),
                "pathEndFrame": frame.get("path_end_frame"),
                "objects": compact_objects,
            }
        )
    return {
        "schemaVersion": payload.get("schema_version"),
        "configVersion": config["config_version"],
        "sideSignConvention": payload.get("side_sign_convention"),
        "arc": payload.get("arc"),
        "egoPath": [
            {
                "frameIndex": item["frame_index"],
                "time": item["timestamp_s"],
                "x": item["x"],
                "y": item["y"],
            }
            for item in payload.get("ego_path", [])
        ],
        "trajectories": trajectories,
        "frames": compact_frames,
    }


def feature_xy(feature: dict, point_by_id: dict[str, dict]) -> tuple[list, list]:
    x_values, y_values = [], []
    for point_id in feature.get("point_ids", []):
        point = point_by_id.get(str(point_id))
        if point is None:
            continue
        x_values.append(point["position_lcs_m"][0])
        y_values.append(point["position_lcs_m"][1])
    return x_values, y_values


def average_xy(points: list[list[float]]) -> list[float]:
    return [
        base.compact_float(sum(point[0] for point in points) / len(points)),
        base.compact_float(sum(point[1] for point in points) / len(points)),
    ]


def lane_anchors(store: dict, point_by_id: dict[str, dict]) -> dict[str, dict]:
    """Recover lane centroid, entry, and exit from ordered boundary ranges.

    Topology has no source geometry of its own.  The lane boundary reference
    order is therefore the available directional contract: the first boundary
    cross-section is lane entry and the last is lane exit.  Invalid ranges are
    not used for topology placement.
    """
    edge_by_id = {
        feature["line_id"]: feature for feature in store["lane_lines"]
    } | {
        feature["road_boundary_id"]: feature for feature in store["road_boundaries"]
    }
    result = {}
    for lane in store["lanes"]:
        sides = []
        for side in ("left", "right"):
            reference = lane["boundaries"].get(side)
            if not reference or not reference.get("endpoint_order_valid"):
                continue
            edge = edge_by_id.get(reference["edge_id"])
            if edge is None:
                continue
            elements = edge.get("elements", [])
            order_to_index = {
                element["order"]: index for index, element in enumerate(elements)
            }
            start = order_to_index[reference["start_order"]]
            end = order_to_index[reference["end_order"]]
            step = 1 if end >= start else -1
            elements = [
                elements[index] for index in range(start, end + step, step)
            ]
            points = []
            for element in elements:
                point = point_by_id.get(element["point_id"])
                if point:
                    points.append(point["position_lcs_m"])
            if points:
                sides.append(points)
        if sides:
            all_points = [point for points in sides for point in points]
            result[lane["lane_id"]] = {
                "centroid": average_xy(all_points),
                "entry": average_xy([points[0] for points in sides]),
                "exit": average_xy([points[-1] for points in sides]),
                "valid_boundary_side_count": len(sides),
            }
    return result


def build_ld_payload(canonical: dict) -> dict:
    store = canonical["ld_feature_store"]
    point_by_id = {point["point_id"]: point for point in store["points"]}
    lane_lines = []
    for feature in store["lane_lines"]:
        x_values, y_values = feature_xy(feature, point_by_id)
        lane_lines.append(
            {
                "id": feature["line_id"],
                "pattern": feature["attributes"].get("pattern", "unknown"),
                "color": feature["attributes"].get("color"),
                "drivable": feature["attributes"].get("drivable"),
                "intersection": feature["attributes"].get("intersection"),
                "x": x_values,
                "y": y_values,
            }
        )

    boundaries = []
    for feature in store["road_boundaries"]:
        x_values, y_values = feature_xy(feature, point_by_id)
        boundaries.append(
            {
                "id": feature["road_boundary_id"],
                "subclass": feature.get("subclass"),
                "attribute": feature.get("boundary_attribute"),
                "x": x_values,
                "y": y_values,
            }
        )

    roadmarks = []
    for feature in store["roadmarks"]:
        x_values = [point["position_lcs_m"][0] for point in feature["points"]]
        y_values = [point["position_lcs_m"][1] for point in feature["points"]]
        if x_values:
            x_values.append(x_values[0])
            y_values.append(y_values[0])
        roadmarks.append(
            {
                "id": feature["roadmark_id"],
                "class": feature.get("class"),
                "subclass": feature.get("subclass"),
                "ignored": feature.get("ignored") is True,
                "x": x_values,
                "y": y_values,
            }
        )

    anchors = lane_anchors(store, point_by_id)
    lanes = [
        {
            "id": feature["lane_id"],
            "subclass": feature.get("subclass"),
            "x": anchors[feature["lane_id"]]["centroid"][0],
            "y": anchors[feature["lane_id"]]["centroid"][1],
            "entry": anchors[feature["lane_id"]]["entry"],
            "exit": anchors[feature["lane_id"]]["exit"],
        }
        for feature in store["lanes"]
        if feature["lane_id"] in anchors
    ]
    topologies = []
    for feature in store["topologies"]:
        source = anchors.get(feature["source_lane_id"])
        destination = anchors.get(feature["destination_lane_id"])
        if source and destination:
            source_exit = source["exit"]
            destination_entry = destination["entry"]
            topologies.append(
                {
                    "id": feature["topology_id"],
                    "subclass": feature.get("subclass"),
                    "sourceLaneId": feature["source_lane_id"],
                    "destinationLaneId": feature["destination_lane_id"],
                    "placementMethod": "source_lane_exit_to_destination_lane_entry",
                    "sourceExit": source_exit,
                    "destinationEntry": destination_entry,
                    "connectionDistanceM": base.compact_float(
                        ((source_exit[0] - destination_entry[0]) ** 2
                         + (source_exit[1] - destination_entry[1]) ** 2) ** 0.5
                    ),
                    "x": [source_exit[0], destination_entry[0]],
                    "y": [source_exit[1], destination_entry[1]],
                }
            )

    frame_context = {
        "nearbyLineIds": [],
        "nearbyLaneIds": [],
        "nearbyBoundaryIds": [],
        "nearbyTopologyIds": [],
        "nearbyRoadmarkIds": [],
        "nearbyIgnoredRoadmarkIds": [],
        "lineCount": [],
        "intersectionLineCount": [],
        "laneCount": [],
        "boundaryCount": [],
        "topologyCount": [],
        "roadmarkCount": [],
        "nearestLineM": [],
        "nearestLaneM": [],
        "nearestBoundaryM": [],
        "nearestRoadmarkM": [],
        "leadObjectId": [],
        "nearbyPedestrianCount": [],
        "nearbyMotorcycleCount": [],
        "nearbyMotionalCount": [],
    }
    for frame in canonical["frames"]:
        identifiers = frame["ld"]["nearby_feature_ids"]
        summary = frame["ld"]["summary"]
        signals = frame["scenario_signals"]
        lead = signals.get("lead_candidate")
        nearby = signals["nearby_30m_counts"]
        frame_context["nearbyLineIds"].append(identifiers["lane_lines"])
        frame_context["nearbyLaneIds"].append(identifiers["lanes"])
        frame_context["nearbyBoundaryIds"].append(identifiers["road_boundaries"])
        frame_context["nearbyTopologyIds"].append(identifiers["topologies"])
        frame_context["nearbyRoadmarkIds"].append(identifiers["roadmarks"])
        frame_context["nearbyIgnoredRoadmarkIds"].append(identifiers["ignored_roadmarks"])
        frame_context["lineCount"].append(summary["nearby_lane_line_count"])
        nearby_line_ids = {str(value) for value in identifiers["lane_lines"]}
        frame_context["intersectionLineCount"].append(
            sum(
                1
                for feature in lane_lines
                if str(feature["id"]) in nearby_line_ids
                and feature.get("intersection") is True
            )
        )
        frame_context["laneCount"].append(summary["nearby_lane_count"])
        frame_context["boundaryCount"].append(summary["nearby_road_boundary_count"])
        frame_context["topologyCount"].append(summary["nearby_topology_count"])
        frame_context["roadmarkCount"].append(summary["nearby_roadmark_count"])
        frame_context["nearestLineM"].append(summary["nearest_lane_line_distance_m"])
        frame_context["nearestLaneM"].append(summary["nearest_lane_distance_m"])
        frame_context["nearestBoundaryM"].append(summary["nearest_road_boundary_distance_m"])
        frame_context["nearestRoadmarkM"].append(summary["nearest_roadmark_distance_m"])
        frame_context["leadObjectId"].append(lead["object_id"] if lead else None)
        frame_context["nearbyPedestrianCount"].append(nearby["pedestrian"])
        frame_context["nearbyMotorcycleCount"].append(nearby["motorcycle"])
        frame_context["nearbyMotionalCount"].append(nearby["all_motional"])

    return {
        "summary": {
            "points": len(store["points"]),
            "laneLines": len(lane_lines),
            "intersectionLaneLines": sum(
                feature.get("intersection") is True for feature in lane_lines
            ),
            "lanes": len(store["lanes"]),
            "roadBoundaries": len(boundaries),
            "topologies": len(store["topologies"]),
            "renderableTopologies": len(topologies),
            "roadmarks": len(roadmarks),
            "ignoredRoadmarks": store["quality"]["ignored_roadmark_count"],
            "invalidLaneEndpointOrders": store["quality"][
                "invalid_lane_boundary_endpoint_order_count"
            ],
            "queryRadiusM": canonical["ld_configuration"]["nearby_query_radius_m"],
            "coordinateSystem": store["coordinate_system"]["name"],
            "confidenceAvailable": False,
            "freespaceAvailable": False,
        },
        "laneLines": lane_lines,
        "lanes": lanes,
        "boundaries": boundaries,
        "roadmarks": roadmarks,
        "topologies": topologies,
        "frameContext": frame_context,
    }


def safe_feature_id(value: object) -> str:
    """Return a filename-safe representation without changing the JSON ID."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value))


def referenced_points(feature: dict, point_by_id: dict[str, dict]) -> list[dict]:
    return [
        point_by_id[str(point_id)]
        for point_id in feature.get("point_ids", [])
        if str(point_id) in point_by_id
    ]


def write_debug_payloads(
    scene_dir: Path, canonical: dict, output_dir: Path
) -> dict[str, int]:
    """Write inspectable OD and LD records addressed by explorer plot clicks."""
    recording = canonical["recording_id"]
    debug_root = output_dir / "debug" / recording
    od_dir = debug_root / "od"
    ld_dir = debug_root / "ld"
    od_dir.mkdir(parents=True, exist_ok=True)
    ld_dir.mkdir(parents=True, exist_ok=True)

    with (scene_dir / "annotations_OD.json").open(encoding="utf-8") as handle:
        od_source = json.load(handle)
    od_ids: set[str] = set()
    for obj in od_source.get("objects", []):
        object_id = obj.get("objectId")
        if object_id is None:
            continue
        payload = {
            "schema_version": "od-debug-feature-v1",
            "recording_id": recording,
            "feature_type": "od_object",
            "feature_id": object_id,
            "scene": od_source.get("scene", {}),
            "object": obj,
        }
        path = od_dir / f"object_{safe_feature_id(object_id)}.json"
        path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        od_ids.add(str(object_id))

    store = canonical["ld_feature_store"]
    point_by_id = {str(point["point_id"]): point for point in store["points"]}
    line_by_id = {str(item["line_id"]): item for item in store["lane_lines"]}
    boundary_by_id = {
        str(item["road_boundary_id"]): item for item in store["road_boundaries"]
    }
    lane_by_id = {str(item["lane_id"]): item for item in store["lanes"]}
    anchor_by_lane_id = lane_anchors(store, point_by_id)
    common = {
        "schema_version": "odld-ld-debug-feature-v1",
        "recording_id": recording,
        "source": {
            "kind": store.get("source_kind"),
            "format_version": store.get("source_format_version"),
            "exported_at": store.get("source_exported_at"),
            "policy": store.get("source_policy"),
        },
        "coordinate_system": store.get("coordinate_system"),
        "filtering_metadata": store.get("filtering_metadata"),
        "store_quality": store.get("quality"),
    }
    feature_specs = [
        ("lane_line", "line_id", store["lane_lines"]),
        ("lane", "lane_id", store["lanes"]),
        ("road_boundary", "road_boundary_id", store["road_boundaries"]),
        ("topology", "topology_id", store["topologies"]),
        ("roadmark", "roadmark_id", store["roadmarks"]),
    ]
    ld_count = 0
    for feature_type, id_key, features in feature_specs:
        for feature in features:
            feature_id = feature[id_key]
            references: dict[str, object] = {}
            if feature_type in {"lane_line", "road_boundary"}:
                references["points"] = referenced_points(feature, point_by_id)
            elif feature_type == "lane":
                edges = []
                for side, reference in feature.get("boundaries", {}).items():
                    if not reference:
                        continue
                    edge_id = str(reference.get("edge_id"))
                    edge = line_by_id.get(edge_id) or boundary_by_id.get(edge_id)
                    edges.append({"side": side, "reference": reference, "feature": edge})
                references["boundary_edges"] = edges
            elif feature_type == "topology":
                references["source_lane"] = lane_by_id.get(
                    str(feature.get("source_lane_id"))
                )
                references["destination_lane"] = lane_by_id.get(
                    str(feature.get("destination_lane_id"))
                )
                source_anchor = anchor_by_lane_id.get(
                    str(feature.get("source_lane_id"))
                )
                destination_anchor = anchor_by_lane_id.get(
                    str(feature.get("destination_lane_id"))
                )
                connector = {
                    "placement_method": (
                        "source_lane_exit_to_destination_lane_entry"
                    ),
                    "renderable": bool(source_anchor and destination_anchor),
                    "source_lane_exit_lcs_m": (
                        source_anchor["exit"] if source_anchor else None
                    ),
                    "destination_lane_entry_lcs_m": (
                        destination_anchor["entry"] if destination_anchor else None
                    ),
                }
                if source_anchor and destination_anchor:
                    start = source_anchor["exit"]
                    end = destination_anchor["entry"]
                    connector["connection_distance_m"] = base.compact_float(
                        ((start[0] - end[0]) ** 2 + (start[1] - end[1]) ** 2)
                        ** 0.5
                    )
                else:
                    connector["connection_distance_m"] = None
                references["visualization_connector"] = connector
            payload = {
                **common,
                "feature_type": feature_type,
                "feature_id": feature_id,
                "feature": feature,
                "referenced_geometry": references,
            }
            path = ld_dir / f"{feature_type}_{safe_feature_id(feature_id)}.json"
            path.write_text(
                json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8"
            )
            ld_count += 1
    return {"od": len(od_ids), "ld": ld_count}


LD_STYLE = """
  .ldSection { margin-top: 14px; padding-top: 10px; border-top: 1px solid #edf1f5; }
  .ldSection h3 { margin: 0 0 6px; font-size: 15px; }
  .ldReadout { margin-top: 8px; padding: 8px; border-radius: 6px; background: #eff6ff; color: #1e3a5f; font-size: 12px; line-height: 1.45; }
  #ldTimeline { height: 350px; }
  .debugReadout { background: #f5f3ff; color: #4c1d95; }
"""


LD_STATS_HTML = """
    <div class="stat"><span>LD points</span><b id="statLdPoints"></b></div>
    <div class="stat"><span>Lane lines / lanes</span><b id="statLdLanes"></b></div>
    <div class="stat"><span>Boundaries / roadmarks</span><b id="statLdBoundaries"></b></div>
"""


LD_CONTROLS_HTML = """
    <div class="ldSection">
      <h3>LD Map Layers</h3>
      <label><input id="showLaneLines" type="checkbox" checked /> Lane lines</label>
      <label><input id="showIntersectionLines" type="checkbox" checked /> Highlight lines with intersection=true</label>
      <label><input id="showBoundaries" type="checkbox" checked /> Road boundaries</label>
      <label><input id="showRoadmarks" type="checkbox" checked /> Roadmarks</label>
      <label><input id="showTopology" type="checkbox" /> Lane topology links</label>
      <label>Topology filter
        <select id="topologyFilter">
          <option value="intersections" selected>intersection_in + intersection_out</option>
          <option value="intersection_in">intersection_in only</option>
          <option value="intersection_out">intersection_out only</option>
          <option value="all">all topology types</option>
        </select>
      </label>
      <label><input id="showLaneAnchors" type="checkbox" /> Lane anchors (debug)</label>
      <label><input id="showNearbyLd" type="checkbox" /> Highlight current nearby LD</label>
      <div id="ldContext" class="ldReadout"></div>
      <div id="debugContext" class="ldReadout debugReadout"><b>Feature debugging</b><br>Click an OD marker or LD feature to open its JSON.</div>
      <div class="note">Topology is rendered from the source-lane exit (open circle) to the destination-lane entry (diamond); topology records contain relationships, not standalone geometry. LD is a recording-level 3D map in inferred shared LCS. Frame highlights use the canonical 100 m spatial query; confidence and freespace are unavailable.</div>
    </div>
"""


TAG_STYLE = """
  .tagReadout { margin-top: 8px; padding: 8px; border-radius: 6px; background: #ecfdf5; color: #14532d; font-size: 12px; line-height: 1.45; }
  .tagPill { display: inline-block; margin: 2px 4px 2px 0; padding: 3px 7px; border-radius: 999px; background: #d1fae5; color: #14532d; font-weight: 700; }
  .roadFeatureReadout { background: #fff7ed; color: #7c2d12; }
  .objectRelationReadout { background: #f0fdfa; color: #134e4a; }
  .pathCrossingReadout { background: #f5f3ff; color: #4c1d95; }
  #tagTimeline { height: 420px; }
"""


TAG_STATS_HTML = """
    <div class="stat"><span>Tagged scenarios</span><b id="statTagScenarios"></b></div>
    <div class="stat"><span>Tag intervals</span><b id="statTagEvents"></b></div>
"""


TAG_CONTROLS_HTML = """
    <div class="ldSection">
      <h3>Scenario Tags</h3>
      <label><input id="showTags" type="checkbox" checked /> Show active tag on map</label>
      <label><input id="showRoadFeatureRelations" type="checkbox" checked /> Crosswalk / stopline relation overlay</label>
      <label><input id="showObjectRelations" type="checkbox" checked /> Nearby object relation overlay</label>
      <label><input id="showDynamicObjectVelocities" type="checkbox" checked /> Dynamic-object velocities and vectors</label>
      <label><input id="showPathCrossingRelations" type="checkbox" checked /> Ego forward arc and crossing states</label>
      <label><input id="showConfirmedCrossingsOnly" type="checkbox" checked /> Confirmed crossing objects only</label>
      <label>Crossing object
        <select id="pathCrossingObjectFilter">
          <option value="all" selected>active confirmed crossings</option>
        </select>
      </label>
      <label>Timeline filter
        <select id="tagScenarioFilter"><option value="all" selected>all tagged scenarios</option></select>
      </label>
      <div id="tagContext" class="tagReadout"></div>
      <div id="roadFeatureContext" class="tagReadout roadFeatureReadout"></div>
      <div id="objectRelationContext" class="tagReadout objectRelationReadout"></div>
      <div id="pathCrossingContext" class="tagReadout pathCrossingReadout"></div>
      <div class="note">All tags are dynamic recording-level rule events with inclusive frame/time sample bounds.</div>
    </div>
"""


TAG_SCRIPT_SETUP = r"""
const tags = DATA.tags;
const roadFeatureRelations = DATA.roadFeatureRelations;
const objectRelations = DATA.objectRelations;
const pathCrossingRelations = DATA.pathCrossingRelations;
const SHARED_TIME_RANGE = [0, traj.rel_t[traj.rel_t.length - 1]];
const SHARED_TIMELINE_MARGIN = {l: 190, r: 85, t: 30, b: 65};
const SHARED_TIME_PLOT_IDS = ['tagTimeline', 'timeline', 'ldTimeline'];
let syncingTimeAxes = false;
const tagFilter = document.getElementById('tagScenarioFilter');
for (const scenario of tags.scenarios) {
  const option = document.createElement('option');
  option.value = scenario;
  option.textContent = scenario.replaceAll('_', ' ');
  tagFilter.appendChild(option);
}
document.getElementById('statTagScenarios').textContent = tags.scenarios.length;
document.getElementById('statTagEvents').textContent = tags.events.length;
const CROSSING_SCENARIOS = new Set([
  'crossed_by_bike', 'crossed_by_motorcycle', 'crossed_by_vehicle'
]);
const crossingEvents = tags.events.filter(event =>
  CROSSING_SCENARIOS.has(event.scenario)
);
const crossingObjectFilter = document.getElementById('pathCrossingObjectFilter');
for (const [index, event] of crossingEvents.entries()) {
  const option = document.createElement('option');
  option.value = String(index);
  const objectClass = event.evidence.original_class || event.evidence.normalized_category || 'object';
  const direction = (event.evidence.crossing_direction || 'unknown direction').replaceAll('_', ' ');
  option.textContent =
    `${objectClass} · ${direction} · frames ${event.startFrame}-${event.endFrame}`;
  crossingObjectFilter.appendChild(option);
}
if (!crossingEvents.length) {
  crossingObjectFilter.options[0].textContent = 'no confirmed crossings';
  crossingObjectFilter.disabled = true;
}
"""


TAG_SCRIPT_FUNCTIONS = r"""
const TAG_COLORS = {
  stationary: '#475569', low_magnitude_speed: '#0ea5e9', medium_magnitude_speed: '#2563eb',
  high_magnitude_speed: '#7c3aed', high_lateral_acceleration: '#f59e0b', high_magnitude_jerk: '#dc2626',
  starting_left_turn: '#16a34a', starting_right_turn: '#db2777',
  starting_low_speed_turn: '#0d9488', starting_high_speed_turn: '#9333ea',
  changing_lane: '#0891b2', changing_lane_to_left: '#15803d',
  changing_lane_to_right: '#be185d',
  traversing_crosswalk: '#ea580c', on_stopline_crosswalk: '#b45309',
  stationary_at_crosswalk: '#78716c', stopping_at_crosswalk: '#c2410c',
  accelerating_at_crosswalk: '#65a30d',
  near_high_speed_vehicle: '#dc2626', near_long_vehicle: '#92400e',
  near_multiple_bikes: '#0d9488', near_multiple_motorcycle: '#7c3aed',
  near_multiple_pedestrians: '#db2777', near_multiple_vehicles: '#2563eb',
  near_pedestrian_on_crosswalk: '#e11d48',
  near_pedestrian_on_crosswalk_with_ego: '#9f1239',
  crossed_by_bike: '#0f766e', crossed_by_motorcycle: '#6d28d9',
  crossed_by_vehicle: '#1d4ed8'
};

function tagColor(scenario) { return TAG_COLORS[scenario] || '#64748b'; }

function sharedTimelineXAxis(extra = {}) {
  return {title: 'time since start (s)', range: [...SHARED_TIME_RANGE], domain: [0, 1], ...extra};
}

function attachSharedTimeAxis(plotId) {
  const plot = document.getElementById(plotId);
  if (plot._sharedTimeAxisAttached) return;
  plot._sharedTimeAxisAttached = true;
  plot.on('plotly_relayout', update => {
    if (syncingTimeAxes) return;
    let range = null;
    if (update['xaxis.range[0]'] != null && update['xaxis.range[1]'] != null) {
      range = [update['xaxis.range[0]'], update['xaxis.range[1]']];
    } else if (update['xaxis.autorange']) {
      range = [...SHARED_TIME_RANGE];
    }
    if (!range) return;
    syncingTimeAxes = true;
    const updates = SHARED_TIME_PLOT_IDS
      .filter(id => id !== plotId && document.getElementById(id).data)
      .map(id => Plotly.relayout(id, {'xaxis.range': range, 'xaxis.autorange': false}));
    Promise.all(updates).finally(() => { syncingTimeAxes = false; });
  });
}

function activeTagEvents() {
  if (!document.getElementById('showTags').checked) return [];
  return tags.events.filter(event => event.startFrame <= currentIndex && currentIndex <= event.endFrame);
}

const roadFeatureTrackById = Object.fromEntries(
  roadFeatureRelations.tracks.map(track => [track.trackId, track])
);
const roadFeatureAssociationByStopline = Object.fromEntries(
  roadFeatureRelations.associations.map(item => [item.stoplineTrackId, item])
);

function currentRoadFeatureFrame() {
  return roadFeatureRelations.frames[currentIndex] || null;
}

function relevantRoadRelations() {
  const frame = currentRoadFeatureFrame();
  if (!frame) return [];
  const all = [...frame.crosswalks, ...frame.stoplines];
  const activeFeatureIds = new Set();
  for (const event of activeTagEvents()) {
    if (event.evidence.crosswalk_id) activeFeatureIds.add(event.evidence.crosswalk_id);
    for (const id of event.evidence.crosswalk_ids || []) activeFeatureIds.add(id);
    if (event.evidence.stopline_id) activeFeatureIds.add(event.evidence.stopline_id);
  }
  const relevant = all.filter(relation =>
    relation.valid &&
    (activeFeatureIds.has(relation.trackId) ||
     !['far', 'unknown'].includes(relation.state))
  );
  if (relevant.length) return relevant;
  return all.filter(relation => relation.valid && relation.pathCompatible)
    .sort((a, b) => (a.nearestDistanceM ?? Infinity) - (b.nearestDistanceM ?? Infinity))
    .slice(0, 1);
}

function roadFeaturePolygonTrace(relation) {
  const track = roadFeatureTrackById[relation.trackId];
  if (!track || !track.x.length) return null;
  const isCrosswalk = track.featureType === 'crosswalk';
  const x = [...track.x, track.x[0]];
  const y = [...track.y, track.y[0]];
  return {
    type: 'scatter', mode: 'lines', name: `${track.featureType} relation`,
    x, y, fill: isCrosswalk ? 'toself' : 'none',
    fillcolor: isCrosswalk ? 'rgba(234,88,12,0.16)' : 'rgba(0,0,0,0)',
    line: {
      color: isCrosswalk ? '#ea580c' : '#b45309',
      width: relation.overlap ? 6 : 4,
      dash: relation.valid ? 'solid' : 'dot'
    },
    customdata: x.map(() => [
      relation.trackId, relation.state, relation.signedDistanceM,
      relation.nearestDistanceM, relation.pathCompatible
    ]),
    hovertemplate:
      '%{customdata[0]}<br>state=%{customdata[1]}' +
      '<br>signed distance=%{customdata[2]:.2f} m' +
      '<br>geometry distance=%{customdata[3]:.2f} m' +
      '<br>path compatible=%{customdata[4]}<extra></extra>'
  };
}

function egoRoadFeatureFootprintTrace() {
  const dimensions = roadFeatureRelations.egoFootprint || {};
  const length = Number(dimensions.length_m || 4.8);
  const width = Number(dimensions.width_m || 2.0);
  const heading = Number(traj.yaw_deg[currentIndex] || 0) * Math.PI / 180;
  const cosine = Math.cos(heading), sine = Math.sin(heading);
  const points = [
    [length / 2, width / 2], [length / 2, -width / 2],
    [-length / 2, -width / 2], [-length / 2, width / 2],
    [length / 2, width / 2]
  ].map(([longitudinal, lateral]) => [
    traj.x[currentIndex] + cosine * longitudinal - sine * lateral,
    traj.y[currentIndex] + sine * longitudinal + cosine * lateral
  ]);
  return {
    type: 'scatter', mode: 'lines', name: 'ego relation footprint',
    x: points.map(point => point[0]), y: points.map(point => point[1]),
    fill: 'toself', fillcolor: 'rgba(30,64,175,0.12)',
    line: {color: '#1e40af', width: 3},
    hovertemplate: `ego footprint ${length.toFixed(1)} x ${width.toFixed(1)} m<extra></extra>`
  };
}

function roadFeatureAssociationTrace(relations) {
  const stopline = relations.find(relation =>
    roadFeatureTrackById[relation.trackId]?.featureType === 'stopline'
  );
  if (!stopline) return null;
  const association = roadFeatureAssociationByStopline[stopline.trackId];
  if (!association || !association.valid) return null;
  const stoplineTrack = roadFeatureTrackById[association.stoplineTrackId];
  const crosswalkTrack = roadFeatureTrackById[association.crosswalkTrackId];
  if (!stoplineTrack?.center || !crosswalkTrack?.center) return null;
  return {
    type: 'scatter', mode: 'lines+markers', name: 'stopline-crosswalk association',
    x: [stoplineTrack.center[0], crosswalkTrack.center[0]],
    y: [stoplineTrack.center[1], crosswalkTrack.center[1]],
    line: {color: '#7c3aed', width: 2, dash: 'dot'},
    marker: {color: '#7c3aed', size: 7},
    customdata: [[association.confidence, association.geometryDistanceM,
      association.orientationDifferenceDeg], [association.confidence,
      association.geometryDistanceM, association.orientationDifferenceDeg]],
    hovertemplate:
      'valid stopline-crosswalk association' +
      '<br>confidence=%{customdata[0]}' +
      '<br>distance=%{customdata[1]:.2f} m' +
      '<br>orientation difference=%{customdata[2]:.1f} deg<extra></extra>'
  };
}

function roadFeatureRelationTraces() {
  if (!document.getElementById('showRoadFeatureRelations').checked) return [];
  const relations = relevantRoadRelations();
  if (!relations.length) return [];
  const traces = [egoRoadFeatureFootprintTrace()];
  for (const relation of relations) {
    const trace = roadFeaturePolygonTrace(relation);
    if (trace) traces.push(trace);
  }
  const association = roadFeatureAssociationTrace(relations);
  if (association) traces.push(association);
  return traces;
}

function updateRoadFeatureContext() {
  const target = document.getElementById('roadFeatureContext');
  if (!document.getElementById('showRoadFeatureRelations').checked) {
    target.textContent = 'Road-feature relation overlay hidden.';
    return;
  }
  const relations = relevantRoadRelations();
  if (!relations.length) {
    target.innerHTML = '<b>Road-feature relation</b><br>No valid path-related crosswalk or stopline.';
    return;
  }
  const lines = relations.map(relation => {
    const track = roadFeatureTrackById[relation.trackId] || {};
    const distance = relation.signedDistanceM == null
      ? 'n/a' : `${Number(relation.signedDistanceM).toFixed(2)} m`;
    let association = '';
    const linked = roadFeatureAssociationByStopline[relation.trackId];
    if (linked) {
      association = linked.valid
        ? ` · associated ${linked.crosswalkTrackId} (${linked.confidence})`
        : ` · association ${linked.status}`;
    }
    return `${track.featureType || 'feature'} ${relation.trackId}: ` +
      `${relation.state.replaceAll('_', ' ')} · signed ${distance}` +
      ` · overlap ${relation.overlap ? 'yes' : 'no'}${association}`;
  });
  target.innerHTML = `<b>Frame ${currentIndex} road-feature relation</b><br>${lines.join('<br>')}`;
}

const OBJECT_CATEGORY_COLORS = {
  vehicle: '#2563eb', pedestrian: '#db2777',
  bicycle: '#0d9488', motorcycle: '#7c3aed'
};

function currentObjectRelationFrame() {
  return objectRelations.frames[currentIndex] || {objects: []};
}

function activeObjectTrackIds() {
  const ids = new Set();
  for (const event of activeTagEvents()) {
    for (const id of event.evidence.object_track_ids || []) ids.add(id);
    for (const id of event.evidence.pedestrian_track_ids || []) ids.add(id);
  }
  return ids;
}

function objectRelationTraces() {
  if (!document.getElementById('showObjectRelations').checked) return [];
  const nearby = currentObjectRelationFrame().objects.filter(item => item.inside);
  const activeIds = activeObjectTrackIds();
  const radius = Number(
    objectRelations.proximityRegion.nearest_footprint_radius_m || 30
  );
  const circleX = [], circleY = [];
  for (let index = 0; index <= 72; index++) {
    const angle = index * Math.PI * 2 / 72;
    circleX.push(traj.x[currentIndex] + radius * Math.cos(angle));
    circleY.push(traj.y[currentIndex] + radius * Math.sin(angle));
  }
  const traces = [{
    type: 'scattergl', mode: 'lines', name: 'object proximity radius',
    x: circleX, y: circleY,
    line: {color: '#64748b', width: 1, dash: 'dot'},
    hovertemplate: `configured footprint proximity radius ${radius.toFixed(1)} m<extra></extra>`
  }];
  for (const category of ['vehicle', 'pedestrian', 'bicycle', 'motorcycle']) {
    const objects = nearby.filter(item => item.category === category);
    if (!objects.length) continue;
    traces.push({
      type: 'scattergl', mode: 'markers', name: `near ${category}`,
      x: objects.map(item => item.x), y: objects.map(item => item.y),
      marker: {
        color: OBJECT_CATEGORY_COLORS[category],
        size: objects.map(item => activeIds.has(item.trackId) ? 18 : 11),
        symbol: objects.map(item => activeIds.has(item.trackId) ? 'diamond' : 'circle'),
        line: {color: '#ffffff', width: 1}
      },
      customdata: objects.map(item => [
        item.className, item.distanceM, item.longitudinalM,
        item.lateralM, item.speedMps, item.velocitySource,
        item.longVehicle, activeIds.has(item.trackId)
      ]),
      hovertemplate:
        '%{customdata[0]}' +
        '<br>footprint distance=%{customdata[1]:.2f} m' +
        '<br>longitudinal=%{customdata[2]:.2f} m; lateral=%{customdata[3]:.2f} m' +
        '<br>speed=%{customdata[4]:.2f} m/s; %{customdata[5]}' +
        '<br>long vehicle=%{customdata[6]}; qualifying=%{customdata[7]}<extra></extra>'
    });
  }
  return traces;
}

function dynamicObjectVelocityTraces() {
  if (!document.getElementById('showDynamicObjectVelocities').checked) return [];
  const objects = currentObjectRelationFrame().objects.filter(
    item => item.annotationType === 'dynamic'
  );
  const valid = objects.filter(
    item => Number.isFinite(item.velocityX) && Number.isFinite(item.velocityY)
  );
  const horizonS = 0.5;
  const traces = [];
  const egoSpeed = Number(traj.speed[currentIndex]);
  if (Number.isFinite(egoSpeed)) {
    traces.push({
      type: 'scattergl', mode: 'markers+text', name: 'ego speed',
      x: [traj.x[currentIndex]], y: [traj.y[currentIndex]],
      text: [`${egoSpeed.toFixed(1)} m/s`],
      textposition: 'top center',
      marker: {
        color: '#16a34a', size: 12, symbol: 'diamond-open',
        line: {width: 3}
      },
      hovertemplate: `ego<br>calculated speed=${egoSpeed.toFixed(2)} m/s<extra></extra>`
    });
  }
  if (!objects.length) return traces;
  if (valid.length) {
    const vectorX = [], vectorY = [];
    for (const item of valid) {
      vectorX.push(item.x, item.x + item.velocityX * horizonS, null);
      vectorY.push(item.y, item.y + item.velocityY * horizonS, null);
    }
    traces.push({
      type: 'scattergl', mode: 'lines', name: 'dynamic velocity (0.5 s vector)',
      x: vectorX, y: vectorY,
      line: {color: '#0f172a', width: 2},
      hoverinfo: 'skip'
    });
  }
  traces.push({
    type: 'scattergl', mode: 'markers+text', name: 'all dynamic-object speeds',
    x: objects.map(item => item.x), y: objects.map(item => item.y),
    text: objects.map(item =>
      item.speedMps == null
        ? ''
        : `${Number(item.speedMps).toFixed(1)} m/s`
    ),
    textposition: 'top center',
    marker: {
      color: objects.map(
        item => OBJECT_CATEGORY_COLORS[item.category] || '#475569'
      ),
      size: 8,
      symbol: 'circle-open',
      line: {width: 2}
    },
    customdata: objects.map(item => [
      item.className, item.speedMps, item.velocityX, item.velocityY,
      item.velocitySource
    ]),
    hovertemplate:
      '%{customdata[0]}' +
      '<br>calculated speed=%{customdata[1]:.2f} m/s' +
      '<br>velocity LCS=(%{customdata[2]:.2f}, %{customdata[3]:.2f}) m/s' +
      '<br>source=%{customdata[4]}' +
      '<extra></extra>'
  });
  return traces;
}

function updateObjectRelationContext() {
  const target = document.getElementById('objectRelationContext');
  const showRelations = document.getElementById('showObjectRelations').checked;
  const showVelocities = document.getElementById(
    'showDynamicObjectVelocities'
  ).checked;
  if (!showRelations && !showVelocities) {
    target.textContent = 'Object relation and velocity overlays hidden.';
    return;
  }
  const objects = currentObjectRelationFrame().objects.filter(item => item.inside);
  const dynamic = currentObjectRelationFrame().objects.filter(
    item => item.annotationType === 'dynamic'
  );
  const dynamicWithVelocity = dynamic.filter(item => item.speedMps != null);
  const counts = {vehicle: 0, pedestrian: 0, bicycle: 0, motorcycle: 0};
  for (const item of objects) counts[item.category] = (counts[item.category] || 0) + 1;
  const activeIds = activeObjectTrackIds();
  const qualifying = objects.filter(item => activeIds.has(item.trackId));
  target.innerHTML =
    `<b>Frame ${currentIndex} dynamic velocities</b><br>` +
    `${dynamicWithVelocity.length}/${dynamic.length} dynamic objects have valid velocity` +
    (showRelations
      ? `<br>nearby: vehicle ${counts.vehicle} - pedestrian ${counts.pedestrian} - ` +
        `bicycle ${counts.bicycle} - motorcycle ${counts.motorcycle}<br>` +
        `qualifying tracks: ${qualifying.length
      ? qualifying.map(item => item.trackId).join(', ')
      : 'none'}`
      : '<br>Nearby-object relation overlay hidden.');
}

function currentPathCrossingFrame() {
  return pathCrossingRelations.frames[currentIndex] || {objects: []};
}

function selectedCrossingEvent() {
  const value = document.getElementById('pathCrossingObjectFilter').value;
  if (value === 'all') return null;
  return crossingEvents[Number(value)] || null;
}

function visibleConfirmedCrossingEvents() {
  const selected = selectedCrossingEvent();
  if (selected) return [selected];
  return crossingEvents.filter(
    event => event.startFrame <= currentIndex && currentIndex <= event.endFrame
  );
}

function visibleCrossingTrackIds() {
  return new Set(
    visibleConfirmedCrossingEvents()
      .map(event => event.evidence.object_track_id)
      .filter(value => value != null)
  );
}

function crossingRelationObjects() {
  const frame = currentPathCrossingFrame();
  const confirmedOnly = document.getElementById(
    'showConfirmedCrossingsOnly'
  ).checked;
  const trackIds = visibleCrossingTrackIds();
  if (confirmedOnly || selectedCrossingEvent()) {
    return frame.objects.filter(
      item => item.valid && trackIds.has(item.trackId)
    );
  }
  return frame.objects.filter(item =>
    item.valid && (
      item.inside ||
      ['APPROACHING_ARC', 'LEAVING_ARC'].includes(item.state)
    )
  );
}

function localCrossingPath() {
  const frame = currentPathCrossingFrame();
  if (frame.pathStartFrame == null || frame.pathEndFrame == null) return [];
  return pathCrossingRelations.egoPath.filter(
    point => frame.pathStartFrame <= point.frameIndex &&
      point.frameIndex <= frame.pathEndFrame
  );
}

function crossingArcPolygon() {
  const arc = pathCrossingRelations.arc;
  if (!arc) return {x: [], y: []};
  const centerX = traj.x[currentIndex], centerY = traj.y[currentIndex];
  const heading = Number(traj.yaw_deg[currentIndex] || 0) * Math.PI / 180;
  const halfAngle = Number(arc.half_angle_deg) * Math.PI / 180;
  const inner = Number(arc.inner_radius_m), outer = Number(arc.outer_radius_m);
  const points = [], samples = 32;
  for (let i = 0; i <= samples; i++) {
    const angle = heading + halfAngle - (2 * halfAngle * i / samples);
    points.push([centerX + outer * Math.cos(angle), centerY + outer * Math.sin(angle)]);
  }
  for (let i = samples; i >= 0; i--) {
    const angle = heading + halfAngle - (2 * halfAngle * i / samples);
    points.push([centerX + inner * Math.cos(angle), centerY + inner * Math.sin(angle)]);
  }
  points.push(points[0]);
  return {x: points.map(point => point[0]), y: points.map(point => point[1])};
}

function crossingTrajectoryPoints(item) {
  const trajectory = pathCrossingRelations.trajectories[item.trackId];
  if (!trajectory) return {x: [], y: []};
  const selected = selectedCrossingEvent();
  const confirmedOnly = document.getElementById(
    'showConfirmedCrossingsOnly'
  ).checked;
  let intervals = [];
  if (selected) {
    intervals = [[selected.startFrame, selected.endFrame]];
  } else if (confirmedOnly) {
    intervals = visibleConfirmedCrossingEvents()
      .filter(event => event.evidence.object_track_id === item.trackId)
      .map(event => [event.startFrame, event.endFrame]);
  } else {
    const frameRadius = 50;
    intervals = [[currentIndex - frameRadius, currentIndex + frameRadius]];
  }
  const x = [], y = [];
  for (let index = 0; index < trajectory.frameIndex.length; index++) {
    const frameIndex = trajectory.frameIndex[index];
    if (intervals.some(([start, end]) => start <= frameIndex && frameIndex <= end)) {
      x.push(trajectory.x[index]);
      y.push(trajectory.y[index]);
    }
  }
  return {x, y};
}

function pathCrossingArcTraces() {
  if (!document.getElementById('showPathCrossingRelations').checked) return [];
  const arc = pathCrossingRelations.arc;
  if (!arc) return [];
  const polygon = crossingArcPolygon();
  const traces = [{
    type: 'scattergl', mode: 'lines', name: 'ego forward crossing arc',
    x: polygon.x, y: polygon.y, fill: 'toself',
    fillcolor: 'rgba(124,58,237,0.10)',
    line: {color: '#7c3aed', width: 1, dash: 'dot'},
    hovertemplate:
      `forward arc ${Number(arc.inner_radius_m).toFixed(1)}–` +
      `${Number(arc.outer_radius_m).toFixed(1)} m; ±` +
      `${Number(arc.half_angle_deg).toFixed(0)}°<extra></extra>`
  }];
  const relevant = crossingRelationObjects();
  const confirmedIds = visibleCrossingTrackIds();
  for (const item of relevant) {
    const trajectory = crossingTrajectoryPoints(item);
    if (trajectory.x.length) traces.push({
      type: 'scattergl', mode: 'lines',
      name: `${item.className} crossing trajectory`,
      x: trajectory.x, y: trajectory.y,
      line: {
        color: OBJECT_CATEGORY_COLORS[item.category] || '#475569',
        width: confirmedIds.has(item.trackId) ? 4 : 2
      },
      hovertemplate: `${item.className} trajectory<extra></extra>`
    });
    const relationX = [item.x], relationY = [item.y];
    if (item.intersectionX != null && item.intersectionY != null) {
      relationX.push(item.intersectionX);
      relationY.push(item.intersectionY);
    }
    traces.push({
      type: 'scattergl', mode: 'lines+markers',
      name: `${item.className} arc relation`,
      x: relationX, y: relationY,
      line: {
        color: OBJECT_CATEGORY_COLORS[item.category] || '#475569',
        width: 2
      },
      marker: {size: [13, 6], symbol: ['diamond', 'circle-open']},
      customdata: relationX.map(() => [
        item.className, item.state, item.side, item.arcBearingDeg,
        item.arcRangeM, item.pathNormalSpeedMps, item.speedMps,
        item.projectionRejectionReason || 'synchronized intersection'
      ]),
      hovertemplate:
        '%{customdata[0]}' +
        '<br>crossing state=%{customdata[1]}; side=%{customdata[2]}' +
        '<br>arc bearing=%{customdata[3]:.1f}°; range=%{customdata[4]:.2f} m' +
        '<br>ego-lateral speed=%{customdata[5]:.2f} m/s' +
        '<br>object speed=%{customdata[6]:.2f} m/s' +
        '<br>projection=%{customdata[7]}<extra></extra>'
    });
  }
  return traces;
}

function updatePathCrossingContext() {
  const target = document.getElementById('pathCrossingContext');
  if (!document.getElementById('showPathCrossingRelations').checked) {
    target.textContent = 'Path-crossing relation overlay hidden.';
    return;
  }
  const relevant = crossingRelationObjects();
  const selected = selectedCrossingEvent();
  const confirmedOnly = document.getElementById(
    'showConfirmedCrossingsOnly'
  ).checked;
  if (!relevant.length) {
    target.innerHTML = `<b>Frame ${currentIndex} path crossing</b><br>` +
      (selected
        ? 'The selected crossing object is not observed at this frame.'
        : confirmedOnly
          ? 'No confirmed crossing is active. Select a crossing object to jump to its entry frame.'
          : 'No object is approaching, inside, or leaving the forward arc.');
    return;
  }
  const lines = relevant.map(item =>
    `${item.className}: ${item.state.replaceAll('_', ' ').toLowerCase()} · ` +
    `${item.side.toLowerCase()} · bearing ${Number(item.arcBearingDeg).toFixed(1)}° · ` +
    `range ${Number(item.arcRangeM).toFixed(1)} m · lateral speed ` +
    `${item.pathNormalSpeedMps == null ? 'n/a' : Number(item.pathNormalSpeedMps).toFixed(2) + ' m/s'}`
  );
  const mode = selected
    ? 'isolated confirmed crossing'
    : confirmedOnly
      ? 'active confirmed crossings only'
      : 'current crossing candidates';
  target.innerHTML =
    `<b>Frame ${currentIndex} path crossing · ${mode}</b><br>${lines.join('<br>')}`;
}

function currentTagTrace() {
  const active = activeTagEvents();
  if (!active.length) return null;
  return {
    type: 'scattergl', mode: 'markers', name: `active tag: ${active[0].scenario}`,
    x: [traj.x[currentIndex]], y: [traj.y[currentIndex]],
    marker: {size: 24, symbol: 'circle-open', color: tagColor(active[0].scenario), line: {width: 5}},
    customdata: [[active.map(event => event.scenario.replaceAll('_', ' ')).join(', ')]],
    hovertemplate: 'active tags<br>%{customdata[0]}<extra></extra>'
  };
}

function tagEvidence(event) {
  const evidence = event.evidence || {};
  const parts = [];
  for (const [key, value] of Object.entries(evidence)) {
    if (value == null || typeof value === 'object') continue;
    parts.push(`${key.replaceAll('_', ' ')}=${typeof value === 'number' ? Number(value).toFixed(3) : value}`);
  }
  return parts.slice(0, 3).join(' | ') || 'interval evidence';
}

function updateTagContext() {
  const context = document.getElementById('tagContext');
  if (!tags.available) {
    context.innerHTML = '<b>No tag source found</b><br>Generate motional windows or pass --window-dir.';
    return;
  }
  const active = activeTagEvents();
  const pills = active.length
    ? active.map(event => `<span class="tagPill">${escapeHtml(event.scenario.replaceAll('_', ' '))}</span>`).join('')
    : '<span>No active scenario tag</span>';
  const evidence = active.map(event => `${escapeHtml(event.scenario)}: ${escapeHtml(tagEvidence(event))}`).join('<br>');
  context.innerHTML = `<b>Frame ${currentIndex} scenario tags</b><br>${pills}${evidence ? '<br>' + evidence : ''}<br>` +
    `source: ${escapeHtml(tags.sourceKind)}${tags.configVersion ? ' | config ' + escapeHtml(tags.configVersion) : ''}`;
}

function renderTagTimeline() {
  const selected = tagFilter.value;
  const events = tags.events.filter(event => selected === 'all' || event.scenario === selected);
  const traces = events.map(event => ({
    type: 'bar', orientation: 'h', showlegend: false, name: event.scenario,
    y: [event.scenario.replaceAll('_', ' ')], x: [Math.max(0.01, event.endTime - event.startTime)], base: [event.startTime],
    marker: {color: tagColor(event.scenario), opacity: 0.82}, width: 0.58,
    customdata: [[event.startFrame, event.endFrame, event.startTime, event.endTime, tagEvidence(event), event.source]],
    hovertemplate: `${event.scenario}<br>frames %{customdata[0]}-%{customdata[1]}<br>time %{customdata[2]:.2f}-%{customdata[3]:.2f}s<br>%{customdata[4]}<br>source=%{customdata[5]}<extra></extra>`
  }));
  Plotly.newPlot('tagTimeline', traces, {
    margin: {...SHARED_TIMELINE_MARGIN}, barmode: 'overlay',
    xaxis: sharedTimelineXAxis(),
    yaxis: {title: '', automargin: false}, hovermode: 'closest',
    shapes: [{type: 'line', x0: traj.rel_t[currentIndex], x1: traj.rel_t[currentIndex], y0: 0, y1: 1, yref: 'paper', line: {color: '#111827', width: 2, dash: 'dot'}}]
  }, {responsive: true});
  attachSharedTimeAxis('tagTimeline');
  const timeline = document.getElementById('tagTimeline');
  if (!timeline._tagClickAttached) {
    timeline._tagClickAttached = true;
    timeline.on('plotly_click', eventData => {
      const point = eventData.points && eventData.points[0];
      if (point && point.customdata) setFrame(point.customdata[0]);
    });
  }
}

function updateTagTimelineCursor() {
  Plotly.relayout('tagTimeline', {shapes: [{type: 'line', x0: traj.rel_t[currentIndex], x1: traj.rel_t[currentIndex], y0: 0, y1: 1, yref: 'paper', line: {color: '#111827', width: 2, dash: 'dot'}}]});
}
"""


LD_SCRIPT_SETUP = r"""
const ld = DATA.ld;
const ldFrames = ld.frameContext;
const ldLineById = Object.fromEntries(ld.laneLines.map(feature => [String(feature.id), feature]));
const ldBoundaryById = Object.fromEntries(ld.boundaries.map(feature => [String(feature.id), feature]));
const ldRoadmarkById = Object.fromEntries(ld.roadmarks.map(feature => [String(feature.id), feature]));
const VEHICLE_CLASSES = new Set(['car', 'truck', 'truck_head', 'bus', 'trailer', 'motorcycle', 'bicycle']);
const DEBUG_BASE = `debug/${encodeURIComponent(DATA.summary.recording)}`;
document.getElementById('statLdPoints').textContent = ld.summary.points;
document.getElementById('statLdLanes').textContent = `${ld.summary.laneLines} / ${ld.summary.lanes}`;
document.getElementById('statLdBoundaries').textContent = `${ld.summary.roadBoundaries} / ${ld.summary.roadmarks}`;
"""


LD_SCRIPT_FUNCTIONS = r"""
function combineLdFeatures(features) {
  const x = [], y = [], customdata = [];
  for (const feature of features) {
    for (let i = 0; i < feature.x.length; i++) {
      x.push(feature.x[i]); y.push(feature.y[i]); customdata.push([String(feature.id), feature.subclass || '']);
    }
    x.push(null); y.push(null); customdata.push([String(feature.id), feature.subclass || '']);
  }
  return {x, y, customdata};
}

function ldLineTrace(features, debugType, name, color, dash, width=1.5, opacity=0.8) {
  const combined = combineLdFeatures(features);
  return {type: 'scattergl', mode: 'lines', name, x: combined.x, y: combined.y,
    customdata: combined.customdata, meta: {debugType}, line: {color, width, dash}, opacity,
    hovertemplate: `${debugType.replaceAll('_', ' ')} #${'%{customdata[0]}'}<br>subtype=%{customdata[1]}<br>x=%{x:.2f}, y=%{y:.2f}<br><b>click for JSON</b><extra></extra>`};
}

function topologyAnchorTrace(features, name, color) {
  const x = [], y = [], customdata = [], symbols = [];
  for (const feature of features) {
    x.push(feature.x[0], feature.x[1]);
    y.push(feature.y[0], feature.y[1]);
    customdata.push(
      [String(feature.id), feature.subclass || '', 'source lane exit', feature.connectionDistanceM],
      [String(feature.id), feature.subclass || '', 'destination lane entry', feature.connectionDistanceM]
    );
    symbols.push('circle-open', 'diamond');
  }
  return {type: 'scattergl', mode: 'markers', name: `${name} endpoints`, showlegend: false,
    x, y, customdata, meta: {debugType: 'topology'},
    marker: {size: 9, color, symbol: symbols, line: {width: 1.5, color}},
    hovertemplate: 'topology #%{customdata[0]}<br>subtype=%{customdata[1]}<br>%{customdata[2]}<br>connector=%{customdata[3]:.2f} m<br><b>click for JSON</b><extra></extra>'};
}

function vehicleHeadingTrace(selectedClasses) {
  const x = [], y = [];
  for (const object of objects) {
    if (!VEHICLE_CLASSES.has(object.className) ||
        !selectedClasses.has(object.className) || !isActiveObject(object)) continue;
    const state = objectState(object, currentIndex);
    if (!state.yawAvailable || state.x == null || state.y == null || state.yaw == null) continue;
    const shaftLength = Math.max(0.8, (state.length || 2.5) / 2);
    const headLength = Math.min(0.8, Math.max(0.35, shaftLength * 0.35));
    const frontX = state.x + shaftLength * Math.cos(state.yaw);
    const frontY = state.y + shaftLength * Math.sin(state.yaw);
    const leftX = frontX - headLength * Math.cos(state.yaw - 0.58);
    const leftY = frontY - headLength * Math.sin(state.yaw - 0.58);
    const rightX = frontX - headLength * Math.cos(state.yaw + 0.58);
    const rightY = frontY - headLength * Math.sin(state.yaw + 0.58);
    x.push(state.x, frontX, null, leftX, frontX, rightX, null);
    y.push(state.y, frontY, null, leftY, frontY, rightY, null);
  }
  return {type: 'scattergl', mode: 'lines', name: 'vehicle heading from OD yaw',
    x, y, line: {color: '#111827', width: 2.2}, hoverinfo: 'skip'};
}

function ldTraces() {
  const traces = [];
  if (document.getElementById('showLaneLines').checked) {
    const styles = {
      solid: ['#0ea5e9', 'solid'], dashed: ['#2563eb', 'dash'],
      virtual: ['#94a3b8', 'dot'], zigzag: ['#7c3aed', 'dashdot'],
      unknown: ['#64748b', 'dot']
    };
    for (const pattern of [...new Set(ld.laneLines.map(feature => feature.pattern || 'unknown'))]) {
      const style = styles[pattern] || styles.unknown;
      traces.push(ldLineTrace(ld.laneLines.filter(feature => (feature.pattern || 'unknown') === pattern), 'lane_line', `LD line: ${pattern}`, style[0], style[1], 1.5, 0.78));
    }
  }
  if (document.getElementById('showIntersectionLines').checked) {
    const intersectionLines = ld.laneLines.filter(feature => feature.intersection === true);
    if (intersectionLines.length) {
      traces.push(ldLineTrace(
        intersectionLines, 'lane_line',
        'LD line: intersection=true', '#d946ef', 'solid', 2.0, 0.82
      ));
    }
  }
  if (document.getElementById('showBoundaries').checked) {
    traces.push(ldLineTrace(ld.boundaries.filter(feature => feature.attribute === 'drivable'), 'road_boundary', 'LD boundary: drivable', '#f59e0b', 'solid', 2, 0.8));
    traces.push(ldLineTrace(ld.boundaries.filter(feature => feature.attribute !== 'drivable'), 'road_boundary', 'LD boundary: non-drivable', '#b45309', 'solid', 2.2, 0.8));
  }
  if (document.getElementById('showRoadmarks').checked) {
    for (const className of [...new Set(ld.roadmarks.map(feature => feature.class || 'unknown'))]) {
      const features = ld.roadmarks.filter(feature => (feature.class || 'unknown') === className && !feature.ignored);
      if (features.length) traces.push(ldLineTrace(features, 'roadmark', `roadmark: ${className}`, className.includes('crosswalk') ? '#e11d48' : '#f97316', 'solid', 3, 0.9));
    }
    const ignored = ld.roadmarks.filter(feature => feature.ignored);
    if (ignored.length) traces.push(ldLineTrace(ignored, 'roadmark', 'roadmark: ignored', '#9ca3af', 'dot', 2, 0.65));
  }
  if (document.getElementById('showTopology').checked && ld.topologies.length) {
    const topologyFilter = document.getElementById('topologyFilter').value;
    const selectedTopologies = ld.topologies.filter(feature =>
      topologyFilter === 'all' ||
      feature.subclass === topologyFilter ||
      (topologyFilter === 'intersections' && ['intersection_in', 'intersection_out'].includes(feature.subclass))
    );
    const topologyStyles = {
      intersection_in: ['#16a34a', 'solid', 3.2, 0.92],
      intersection_out: ['#dc2626', 'dash', 3.2, 0.92]
    };
    for (const subtype of [...new Set(selectedTopologies.map(feature => feature.subclass || 'unknown'))]) {
      const style = topologyStyles[subtype] || ['#8b5cf6', 'dot', 1.4, 0.65];
      const subtypeFeatures = selectedTopologies.filter(
        feature => (feature.subclass || 'unknown') === subtype
      );
      traces.push(ldLineTrace(
        subtypeFeatures, 'topology', `topology: ${subtype}`,
        style[0], style[1], style[2], style[3]
      ));
      traces.push(topologyAnchorTrace(subtypeFeatures, `topology: ${subtype}`, style[0]));
    }
  }
  if (document.getElementById('showLaneAnchors').checked && ld.lanes.length) {
    traces.push({type: 'scattergl', mode: 'markers', name: 'LD lane anchors',
      x: ld.lanes.map(feature => feature.x), y: ld.lanes.map(feature => feature.y),
      customdata: ld.lanes.map(feature => [String(feature.id), feature.subclass || '']),
      meta: {debugType: 'lane'}, marker: {size: 7, color: '#6d28d9', symbol: 'diamond'},
      hovertemplate: 'lane #%{customdata[0]}<br>subclass=%{customdata[1]}<br><b>click for JSON</b><extra></extra>'});
  }
  if (document.getElementById('showNearbyLd').checked) {
    const lines = ldFrames.nearbyLineIds[currentIndex].map(id => ldLineById[String(id)]).filter(Boolean);
    const boundaries = ldFrames.nearbyBoundaryIds[currentIndex].map(id => ldBoundaryById[String(id)]).filter(Boolean);
    const roadmarks = ldFrames.nearbyRoadmarkIds[currentIndex].map(id => ldRoadmarkById[String(id)]).filter(Boolean);
    if (lines.length) traces.push(ldLineTrace(lines, 'lane_line', 'nearby lane lines (100m)', '#22d3ee', 'solid', 4, 0.42));
    if (boundaries.length) traces.push(ldLineTrace(boundaries, 'road_boundary', 'nearby boundaries (100m)', '#fbbf24', 'solid', 4, 0.38));
    if (roadmarks.length) traces.push(ldLineTrace(roadmarks, 'roadmark', 'nearby roadmarks (100m)', '#fb7185', 'solid', 5, 0.55));
  }
  return traces;
}

function debugFeatureUrl(debugType, featureId) {
  if (debugType === 'od_object') return `${DEBUG_BASE}/od/object_${encodeURIComponent(featureId)}.json`;
  return `${DEBUG_BASE}/ld/${debugType}_${encodeURIComponent(featureId)}.json`;
}

function attachFeatureDebugHandler() {
  const map = document.getElementById('map');
  if (map._featureDebugAttached) return;
  map._featureDebugAttached = true;
  map.on('plotly_click', eventData => {
    const point = eventData.points && eventData.points[0];
    const debugType = point && point.data && point.data.meta && point.data.meta.debugType;
    if (!debugType || !point.data.customdata) return;
    const row = point.data.customdata[point.pointIndex];
    if (!Array.isArray(row) || row[0] == null) return;
    const url = debugFeatureUrl(debugType, row[0]);
    document.getElementById('debugContext').innerHTML =
      `<b>Selected ${debugType.replaceAll('_', ' ')} #${row[0]}</b><br><a href="${url}" target="_blank">Open debug JSON</a>`;
    const opened = window.open(url, '_blank');
    if (!opened) document.getElementById('debugContext').innerHTML += '<br>Popup blocked; use the link above.';
  });
}

function formatDistance(value) { return value == null ? 'n/a' : `${Number(value).toFixed(2)} m`; }

function updateLdContext() {
  const i = currentIndex;
  const invalid = ld.summary.invalidLaneEndpointOrders;
  document.getElementById('ldContext').innerHTML =
    `<b>Frame ${i} LD context</b><br>` +
    `nearby: ${ldFrames.lineCount[i]} lines · ${ldFrames.laneCount[i]} lanes · ${ldFrames.boundaryCount[i]} boundaries · ${ldFrames.topologyCount[i]} topologies · ${ldFrames.roadmarkCount[i]} roadmarks<br>` +
    `intersection context: ${ldFrames.intersectionLineCount[i]} nearby lines with intersection=true<br>` +
    `nearest: line ${formatDistance(ldFrames.nearestLineM[i])} · boundary ${formatDistance(ldFrames.nearestBoundaryM[i])} · roadmark ${formatDistance(ldFrames.nearestRoadmarkM[i])}<br>` +
    `OD: lead ${ldFrames.leadObjectId[i] ?? 'none'} · motional within 30m ${ldFrames.nearbyMotionalCount[i]}<br>` +
    `source quality: ${invalid} invalid lane endpoint-order reference${invalid === 1 ? '' : 's'}`;
}

function renderLdTimeline() {
  const traces = [
    {type: 'scattergl', mode: 'lines', x: traj.rel_t, y: ldFrames.nearestLineM, name: 'nearest lane line m', line: {color: '#0284c7'}},
    {type: 'scattergl', mode: 'lines', x: traj.rel_t, y: ldFrames.nearestBoundaryM, name: 'nearest boundary m', line: {color: '#b45309'}},
    {type: 'scattergl', mode: 'lines', x: traj.rel_t, y: ldFrames.nearestRoadmarkM, name: 'nearest roadmark m', line: {color: '#e11d48'}},
    {type: 'scattergl', mode: 'lines', x: traj.rel_t, y: ldFrames.nearbyMotionalCount, name: 'OD motional within 30m', yaxis: 'y2', line: {color: '#16a34a'}},
    {type: 'scattergl', mode: 'lines', x: traj.rel_t, y: ldFrames.lineCount, name: 'LD lines within 100m', yaxis: 'y2', line: {color: '#7c3aed', dash: 'dot'}}
  ];
  Plotly.newPlot('ldTimeline', traces, {
    margin: {...SHARED_TIMELINE_MARGIN},
    xaxis: sharedTimelineXAxis(),
    yaxis: {title: 'nearest distance (m)', rangemode: 'tozero'},
    yaxis2: {title: 'feature/object count', overlaying: 'y', side: 'right', rangemode: 'tozero'},
    legend: {orientation: 'h', x: 0.5, xanchor: 'center', y: -0.24, yanchor: 'top', font: {size: 10}},
    hovermode: 'x unified'
  }, {responsive: true});
  attachSharedTimeAxis('ldTimeline');
}

function updateLdTimelineCursor() {
  const t = traj.rel_t[currentIndex];
  Plotly.relayout('ldTimeline', {shapes: [{type: 'line', x0: t, x1: t, y0: 0, y1: 1, xref: 'x', yref: 'paper', line: {color: '#111827', width: 2, dash: 'dot'}}]});
}
"""


def scene_html(data: dict) -> str:
    page = base.scene_html(data)
    title = data["summary"]["recording"]
    page = page.replace(
        f"<title>{title} Animated Trajectory/Object Explorer</title>",
        f"<title>{title} Animated OD+LD Explorer</title>",
    )
    page = page.replace(
        "Animated ego trajectory with ALT object tracks. Uses per-frame bbox3d where available; static objects use object-level bbox3d.",
        "Animated ego trajectory, OD object tracks, and recording-level LD map geometry with synchronized frame context.",
    )
    page = page.replace(
        '<a class="backLink" href="../dataset_trajectory_object_explorer_index.html">Back to list</a>',
        '<a class="backLink" href="../dataset_odld_explorer_w_scenario_tag_index.html">Back to OD+LD list</a>',
    )
    page = replace_once(
        page, "</style>", LD_STYLE + TAG_STYLE + "\n</style>", "LD and tag styles"
    )
    page = replace_once(
        page,
        '    <div class="stat"><span>Per-frame tracks</span><b id="statTracks"></b></div>\n',
        '    <div class="stat"><span>Per-frame tracks</span><b id="statTracks"></b></div>\n'
        + LD_STATS_HTML
        + TAG_STATS_HTML,
        "LD and tag statistics",
    )
    page = replace_once(
        page,
        '    <div id="animControls">',
        LD_CONTROLS_HTML + TAG_CONTROLS_HTML + '\n    <div id="animControls">',
        "LD and tag controls",
    )
    page = replace_once(
        page,
        '    <label><input id="showEgoMarkers" type="checkbox" checked /> Show ego heading samples</label>',
        '    <label><input id="showEgoMarkers" type="checkbox" checked /> Show ego heading samples</label>\n'
        '    <label><input id="showObjectHeadings" type="checkbox" checked /> Show vehicle heading arrows from OD yaw</label>',
        "vehicle heading control",
    )
    page = replace_once(
        page,
        '    <div class="panel"><div id="timeline"></div></div>',
        '    <div class="panel"><div id="tagTimeline"></div></div>\n'
        '    <div class="panel"><div id="timeline"></div></div>\n'
        '    <div class="panel"><div id="ldTimeline"></div></div>',
        "LD and tag timeline panels",
    )
    page = replace_once(
        page,
        "const objects = DATA.objects;\n",
        "const objects = DATA.objects;\n" + LD_SCRIPT_SETUP + TAG_SCRIPT_SETUP,
        "LD and tag script setup",
    )
    page = replace_once(
        page,
        "function render() {\n",
        LD_SCRIPT_FUNCTIONS + TAG_SCRIPT_FUNCTIONS + "\nfunction render() {\n",
        "LD and tag render helpers",
    )
    page = replace_once(
        page,
        "    margin: {l: 72, r: 78, t: 26, b: 86},\n"
        "    xaxis: {title: 'time since start (s)', domain: [0, 1], anchor: 'y4'},",
        "    margin: {...SHARED_TIMELINE_MARGIN},\n"
        "    xaxis: sharedTimelineXAxis({anchor: 'y4'}),",
        "shared motion timeline x-axis",
    )
    page = replace_once(
        page,
        "    legend: {orientation: 'h', x: 0.5, xanchor: 'center', y: -0.18, yanchor: 'top', font: {size: 11}}\n"
        "  }, {responsive: true});\n"
        "}\n\n"
        "function updateTimelineCursor() {",
        "    legend: {orientation: 'h', x: 0.5, xanchor: 'center', y: -0.18, yanchor: 'top', font: {size: 11}}\n"
        "  }, {responsive: true});\n"
        "  attachSharedTimeAxis('timeline');\n"
        "}\n\n"
        "function updateTimelineCursor() {",
        "shared motion timeline synchronization",
    )
    page = replace_once(
        page,
        "        customdata: active.map((o, i) => [o.objectId, o.type, o.subclassName || '', states[i].length, states[i].width, o.visibleMin, o.visibleMax, states[i].source]),",
        "        customdata: active.map((o, i) => [o.objectId, o.type, o.subclassName || '', states[i].length, states[i].width, o.visibleMin, o.visibleMax, states[i].source, states[i].yawAvailable ? `${(states[i].yaw * 180 / Math.PI).toFixed(1)} deg` : 'n/a']),\n"
        "        meta: {debugType: 'od_object'},",
        "OD debug identity",
    )
    page = replace_once(
        page,
        "        hovertemplate: `${c} #%{customdata[0]}<br>x=%{x:.2f}, y=%{y:.2f}<br>type=%{customdata[1]} %{customdata[2]}<br>LxW=%{customdata[3]:.1f} x %{customdata[4]:.1f}<br>visible=%{customdata[5]}-%{customdata[6]}<br>source=%{customdata[7]}<extra></extra>`",
        "        hovertemplate: `${c} #%{customdata[0]}<br>x=%{x:.2f}, y=%{y:.2f}<br>type=%{customdata[1]} %{customdata[2]}<br>LxW=%{customdata[3]:.1f} x %{customdata[4]:.1f}<br>yaw LCS=%{customdata[8]}<br>visible=%{customdata[5]}-%{customdata[6]}<br>source=%{customdata[7]}<extra></extra>`",
        "OD yaw hover",
    )
    page = replace_once(
        page,
        "      yaw: o.yaws[idx] ?? o.yaw,",
        "      yaw: o.yaws[idx] ?? o.yaw,\n"
        "      yawAvailable: o.yawValids ? o.yawValids[idx] === true : o.yawAvailable === true,",
        "per-frame OD yaw validity",
    )
    page = replace_once(
        page,
        "  return {x: o.x, y: o.y, yaw: o.yaw, length: o.length, width: o.width, height: o.height, source: 'object-level bbox3d'};",
        "  return {x: o.x, y: o.y, yaw: o.yaw, yawAvailable: o.yawAvailable === true, length: o.length, width: o.width, height: o.height, source: 'object-level bbox3d'};",
        "object-level OD yaw validity",
    )
    page = replace_once(
        page,
        "  if (document.getElementById('showEgoMarkers').checked) traces.push(headingTrace());",
        "  traces.unshift(...ldTraces());\n"
        "  traces.unshift(...roadFeatureRelationTraces());\n"
        "  traces.unshift(...objectRelationTraces());\n"
        "  traces.unshift(...dynamicObjectVelocityTraces());\n"
        "  traces.unshift(...pathCrossingArcTraces());\n"
        "  updateLdContext();\n"
        "  updateTagContext();\n"
        "  updateRoadFeatureContext();\n"
        "  updateObjectRelationContext();\n"
        "  updatePathCrossingContext();\n"
        "  if (document.getElementById('showEgoMarkers').checked) traces.push(headingTrace());\n"
        "  const tagTrace = currentTagTrace();\n"
        "  if (tagTrace) traces.push(tagTrace);",
        "LD map and tag traces",
    )
    page = replace_once(
        page,
        "  if (document.getElementById('showFootprints').checked) {",
        "  if (document.getElementById('showObjectHeadings').checked) traces.push(vehicleHeadingTrace(selected));\n"
        "  if (document.getElementById('showFootprints').checked) {",
        "vehicle heading traces",
    )
    page = replace_once(
        page,
        "  syncNoteEditor();\n  render();\n  applyFollowEgo();\n  updateTimelineCursor();\n}",
        "  syncNoteEditor();\n  render();\n  applyFollowEgo();\n"
        "  updateTimelineCursor();\n  updateLdTimelineCursor();\n  updateTagTimelineCursor();\n}",
        "LD and tag cursor update",
    )
    page = replace_once(
        page,
        "for (const id of ['showFootprints','showObjects','showEgoMarkers','persistStatic']) document.getElementById(id).addEventListener('change', render);",
        "for (const id of ['showFootprints','showObjects','showEgoMarkers','showObjectHeadings','persistStatic','showLaneLines','showIntersectionLines','showBoundaries','showRoadmarks','showTopology','topologyFilter','showLaneAnchors','showNearbyLd','showTags','showRoadFeatureRelations','showObjectRelations','showDynamicObjectVelocities','showPathCrossingRelations','showConfirmedCrossingsOnly']) document.getElementById(id).addEventListener('change', render);\n"
        "document.getElementById('pathCrossingObjectFilter').addEventListener('change', () => {\n"
        "  const event = selectedCrossingEvent();\n"
        "  if (event) setFrame(event.evidence.arc_entry_frame ?? event.startFrame);\n"
        "  else render();\n"
        "});\n"
        "document.getElementById('tagScenarioFilter').addEventListener('change', renderTagTimeline);",
        "LD and tag control listeners",
    )
    page = replace_once(
        page,
        "    attachMapRelayoutHandler();\n    applyFollowEgo();",
        "    attachMapRelayoutHandler();\n    attachFeatureDebugHandler();\n    applyFollowEgo();",
        "feature debug click handler",
    )
    page = replace_once(
        page,
        "renderTimeline();\n",
        "renderTimeline();\nrenderLdTimeline();\nrenderTagTimeline();\n",
        "LD and tag timeline initialization",
    )
    return page


def index_html(rows: list[dict]) -> str:
    cards = "\n".join(
        f"""<a class="card" href="dataset_scene_explorers_odld_w_scenario_tag/{html.escape(row['file'])}">
  <div class="route">{row['thumbnail']}</div>
  <h2>{html.escape(row['recording'])}</h2>
  <div class="metrics"><span>{row['frames']} frames</span><span>{row['duration']:.1f}s</span><span>{row['objects']} objects</span></div>
  <div class="metrics"><span>{row['lines']} lane lines</span><span>{row['boundaries']} boundaries</span><span>{row['roadmarks']} roadmarks</span></div>
  <div class="metrics"><span>{row['tagScenarios']} tagged scenarios</span><span>{row['tagEvents']} tag intervals</span></div>
  <p>{html.escape(row['topClasses'])}</p>
</a>"""
        for row in rows
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OD + LD + Ego Trajectory Explorers</title>
<style>
body{{margin:0;font-family:Arial,sans-serif;background:#f1f5f9;color:#17202a}}header{{padding:22px 28px;background:#17324d;color:white}}header h1{{margin:0 0 6px;font-size:24px}}header p{{margin:0;opacity:.88}}main{{padding:22px;display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:16px}}.card{{display:block;background:white;border:1px solid #cbd5e1;border-radius:10px;padding:15px;text-decoration:none;color:inherit;box-shadow:0 2px 8px rgba(15,23,42,.06)}}.card:hover{{border-color:#2563eb;box-shadow:0 5px 18px rgba(37,99,235,.14)}}h2{{font-size:16px;margin:10px 0}}.route{{height:120px;background:#f8fafc;border-radius:7px;overflow:hidden}}.route svg{{width:100%;height:100%}}.metrics{{display:flex;gap:8px;flex-wrap:wrap;margin:7px 0}}.metrics span{{background:#e2e8f0;border-radius:999px;padding:4px 8px;font-size:12px}}p{{font-size:12px;color:#475569;line-height:1.45}}
</style></head><body><header><h1>OD + LD + Ego Trajectory Explorers</h1><p>Synchronized scene viewers with OD tracks, complete LD map layers, scenario-tag intervals, frame-local context, playback, timelines, and notes.</p></header><main>{cards}</main></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--canonical-dir", type=Path, default=DEFAULT_CANONICAL_DIR)
    parser.add_argument("--window-dir", type=Path, default=DEFAULT_WINDOW_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--index-path", type=Path, default=DEFAULT_INDEX_PATH)
    parser.add_argument(
        "--index-from-existing",
        action="store_true",
        help="Rebuild the index/manifest from already generated explorer HTML.",
    )
    parser.add_argument("recordings", nargs="*")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.index_from_existing:
        rows = []
        marker = re.compile(r"const DATA = (\{.*?\});\s*const ", re.DOTALL)
        for output_path in sorted(
            args.output_dir.glob("*_animated_odld_explorer.html")
        ):
            match = marker.search(output_path.read_text(encoding="utf-8"))
            if match is None:
                raise ValueError(f"Unable to read explorer payload: {output_path}")
            data = json.loads(match.group(1))
            rows.append(
                {
                    "recording": data["summary"]["recording"],
                    "file": output_path.name,
                    "frames": data["summary"]["frames"],
                    "duration": data["summary"]["durationSec"],
                    "objects": data["summary"]["objects"],
                    "lines": data["ld"]["summary"]["laneLines"],
                    "boundaries": data["ld"]["summary"]["roadBoundaries"],
                    "roadmarks": data["ld"]["summary"]["roadmarks"],
                    "tagScenarios": len(data["tags"]["scenarios"]),
                    "tagEvents": len(data["tags"]["events"]),
                    "topClasses": ", ".join(
                        f"{key}:{value}"
                        for key, value in list(
                            data["summary"]["classCounts"].items()
                        )[:6]
                    ),
                    "thumbnail": base.thumbnail_svg(data),
                }
            )
            del data
            gc.collect()
        args.index_path.parent.mkdir(parents=True, exist_ok=True)
        args.index_path.write_text(index_html(rows), encoding="utf-8")
        manifest_path = args.output_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "odld-animated-explorer-manifest-v1",
                    "index": args.index_path.name,
                    "recordings": [
                        {
                            key: row[key]
                            for key in (
                                "recording",
                                "file",
                                "frames",
                                "duration",
                                "objects",
                                "lines",
                                "boundaries",
                                "roadmarks",
                                "tagScenarios",
                                "tagEvents",
                            )
                        }
                        for row in rows
                    ],
                },
                ensure_ascii=True,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Wrote index: {args.index_path}")
        print(f"Wrote manifest: {manifest_path}")
        return

    canonical_paths = sorted(args.canonical_dir.glob("*_canonical_odld_frames.json"))
    if args.recordings:
        requested = set(args.recordings)
        canonical_paths = [
            path
            for path in canonical_paths
            if path.name.removesuffix("_canonical_odld_frames.json") in requested
        ]
    rows = []
    for index, canonical_path in enumerate(canonical_paths, 1):
        with canonical_path.open(encoding="utf-8") as handle:
            canonical = json.load(handle)
        recording = canonical["recording_id"]
        scene_dir = args.source_root / recording
        data = build_base_data(scene_dir)
        data["ld"] = build_ld_payload(canonical)
        data["roadFeatureRelations"] = build_road_feature_payload(canonical)
        data["objectRelations"] = build_object_relation_payload(canonical)
        data["pathCrossingRelations"] = build_object_path_crossing_payload(
            canonical
        )
        data["tags"] = build_tag_payload(
            recording, args.window_dir, canonical
        )
        debug_counts = write_debug_payloads(scene_dir, canonical, args.output_dir)
        output_name = f"{recording}_animated_odld_explorer.html"
        output_path = args.output_dir / output_name
        output_path.write_text(scene_html(data), encoding="utf-8")
        top_classes = ", ".join(
            f"{key}:{value}"
            for key, value in list(data["summary"]["classCounts"].items())[:6]
        )
        rows.append(
            {
                "recording": recording,
                "file": output_name,
                "frames": data["summary"]["frames"],
                "duration": data["summary"]["durationSec"],
                "objects": data["summary"]["objects"],
                "lines": data["ld"]["summary"]["laneLines"],
                "boundaries": data["ld"]["summary"]["roadBoundaries"],
                "roadmarks": data["ld"]["summary"]["roadmarks"],
                "tagScenarios": len(data["tags"]["scenarios"]),
                "tagEvents": len(data["tags"]["events"]),
                "topClasses": top_classes,
                "thumbnail": base.thumbnail_svg(data),
            }
        )
        print(
            f"[{index}/{len(canonical_paths)}] {recording}: "
            f"{data['summary']['objects']} objects, "
            f"{data['ld']['summary']['laneLines']} lane lines, "
            f"{data['ld']['summary']['roadBoundaries']} boundaries, "
            f"{len(data['tags']['scenarios'])} tagged scenarios / "
            f"{len(data['tags']['events'])} intervals, "
            f"{debug_counts['od']} OD + {debug_counts['ld']} LD debug records"
        )
        # Each recording can embed tens of MB of OD/LD payload. Release it
        # before loading the next scene so all-recording regeneration remains
        # reliable on Windows.
        del canonical, data
        gc.collect()
    args.index_path.parent.mkdir(parents=True, exist_ok=True)
    args.index_path.write_text(index_html(rows), encoding="utf-8")
    manifest = {
        "schema_version": "odld-animated-explorer-manifest-v1",
        "index": args.index_path.name,
        "recordings": [
            {
                key: row[key]
                for key in (
                    "recording",
                    "file",
                    "frames",
                    "duration",
                    "objects",
                    "lines",
                    "boundaries",
                    "roadmarks",
                    "tagScenarios",
                    "tagEvents",
                )
            }
            for row in rows
        ],
    }
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8")
    print(f"Wrote index: {args.index_path}")
    print(f"Wrote manifest: {manifest_path}")


if __name__ == "__main__":
    main()
