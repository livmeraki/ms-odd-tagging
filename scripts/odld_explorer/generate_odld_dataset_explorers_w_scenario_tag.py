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
import time
from collections import Counter
from pathlib import Path

import generate_dataset_explorers as base
from ms_odd_tagging.common.progress import ProgressReporter
from ms_odd_tagging.features.road_feature_relations import (
    build_road_feature_relations,
)
from ms_odd_tagging.features.object_relations import build_object_relations
from ms_odd_tagging.features.object_path_crossing_relations import (
    build_object_path_crossing_relations,
)
from ms_odd_tagging.ld_topology.config import load_config as load_ld_topology_config
from ms_odd_tagging.ld_topology.pipeline import classify_recording
from ms_odd_tagging.tagger.rule_based.registry import (
    PHASE4_SCENARIOS,
    detect_recording_events,
    load_config,
)
from ms_odd_tagging.scenarios.following_lane.detector import run_following_lane
from ms_odd_tagging.scenarios.following_lane.explorer_visualization import (
    render_original_explorer_with_lane_tracker,
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
DEFAULT_LD_TOPOLOGY_CONFIG = Path("configs/ld_topology.json")
EXPLORER_DATA_MARKER = re.compile(r"const DATA = (\{.*?\});\s*const ", re.DOTALL)
HIDDEN_VISUALIZATION_SCENARIOS = {"high_magnitude_jerk"}
MANIFEST_SCHEMA_VERSION = "odld-animated-explorer-manifest-v1"
INDEX_ROW_KEYS = (
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
    "tagScenarioList",
    "topClasses",
    "thumbnail",
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


def following_lane_event_payload(interval: dict) -> dict:
    return {
        "scenario": interval["scenario"],
        "startFrame": interval["start_frame_index"],
        "endFrame": interval["end_frame_index"],
        "startTime": interval["start_time_since_start_s"],
        "endTime": interval["end_time_since_start_s"],
        "durationSec": (
            interval["end_time_since_start_s"]
            - interval["start_time_since_start_s"]
        ),
        "confidence": None,
        "detectorVersion": "following_lane_tracker",
        "evidence": compact_tag_evidence(
            {
                "frame_count": interval.get("frame_count"),
                "boundary_convention": interval.get("boundary_convention"),
            }
        ),
        "source": "generated_lane_tracker",
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

    events = [
        event
        for event in events
        if event["scenario"] not in HIDDEN_VISUALIZATION_SCENARIOS
    ]
    scenarios = sorted({event["scenario"] for event in events})
    return {
        "available": bool(events),
        "source": source_path.name if source_path is not None else None,
        "sourceKind": source_kind,
        "configVersion": config_version,
        "scenarios": scenarios,
        "events": events,
    }


TOPOLOGY_FRAME_FIELDS = (
    "topology_class",
    "topology_confidence",
    "topology_component_id",
    "intersection_geometry_source",
    "ego_inside_topology_polygon",
    "distance_to_topology_polygon_m",
    "arm_count",
    "arm_angles_deg",
    "opposite_pairs",
    "circularity_score",
    "internal_ambiguous_state",
    "decision_reason",
    "is_intersection_component",
    "topology_subtype",
    "subtype_confidence",
    "component_geometry_confidence",
    "intersection_evidence_score",
    "active_topology_component",
    "active_is_intersection",
    "active_topology_subtype",
    "lane_geometry_roundabout",
)


def build_ld_topology_result(canonical: dict) -> dict:
    config = load_ld_topology_config(
        DEFAULT_LD_TOPOLOGY_CONFIG if DEFAULT_LD_TOPOLOGY_CONFIG.is_file() else None
    )
    return classify_recording(canonical, config)


def canonical_with_ld_topology(canonical: dict, topology: dict) -> dict:
    frame_topology = {
        item.get("frame_index"): item
        for item in topology.get("frames", [])
        if item.get("frame_index") is not None
    }
    frames = []
    for frame in canonical.get("frames", []):
        merged = dict(frame)
        context = frame_topology.get(frame.get("frame_index")) or {}
        for key in TOPOLOGY_FRAME_FIELDS:
            if key in context:
                merged[key] = context[key]
        frames.append(merged)
    return {**canonical, "frames": frames}


def build_ld_topology_payload(topology: dict) -> dict:
    frames = topology.get("frames", [])
    classes = [frame.get("topology_class", "normal") for frame in frames]
    active_classes = {
        name
        for name in classes
        if name in {"intersection_unknown", "x-intersection", "t-intersection", "y-intersection", "roundabout"}
    }
    def component_payload(component: dict) -> dict:
        classification = component.get("classification") or {}
        arm_diagnostics = classification.get("arm_diagnostics") or {}
        external_corridors = arm_diagnostics.get("external_corridor_components") or []
        return {
            "id": component.get("component_id"),
            "class": classification.get("topology_class", "normal"),
            "isIntersectionComponent": bool(
                classification.get("is_intersection_component", False)
            ),
            "topologySubtype": classification.get("topology_subtype", "normal"),
            "confidence": classification.get("topology_confidence", 0.0),
            "geometryConfidence": classification.get(
                "component_geometry_confidence", 0.0
            ),
            "subtypeConfidence": classification.get("subtype_confidence", 0.0),
            "intersectionEvidenceScore": classification.get(
                "intersection_evidence_score", 0.0
            ),
            "externalCorridorCandidateCount": len(external_corridors),
            "physicalArmCandidateCount": classification.get("arm_count", 0),
            "armSource": arm_diagnostics.get("arm_source"),
            "center": component.get("center_lcs_m"),
            "polygon": component.get("core_polygon_lcs_m", []),
            "decisionReason": classification.get("decision_reason"),
        }

    return {
        "schemaVersion": "ld-topology-context-v1",
        "summary": {
            "components": len(topology.get("components", [])),
            "frames": len(frames),
            "activeFrames": len(active_classes)
            and sum(name in active_classes for name in classes),
            "classes": sorted(set(classes)),
            "minimumConfidenceSource": "configs/ld_topology.json",
        },
        "components": [
            component_payload(component)
            for component in topology.get("components", [])
        ],
        "frames": [
            {
                "frameIndex": frame.get("frame_index"),
                "topologyClass": frame.get("topology_class", "normal"),
                "topologySubtype": frame.get("topology_subtype", "normal"),
                "topologyConfidence": frame.get("topology_confidence", 0.0),
                "geometryConfidence": frame.get("component_geometry_confidence", 0.0),
                "subtypeConfidence": frame.get("subtype_confidence", 0.0),
                "intersectionEvidenceScore": frame.get("intersection_evidence_score", 0.0),
                "activeIsIntersection": bool(frame.get("active_is_intersection", False)),
                "activeTopologySubtype": frame.get("active_topology_subtype", "normal"),
                "componentId": frame.get("topology_component_id"),
                "egoInsideTopologyPolygon": frame.get(
                    "ego_inside_topology_polygon", False
                ),
                "distanceToTopologyPolygonM": frame.get(
                    "distance_to_topology_polygon_m"
                ),
                "decisionReason": frame.get("decision_reason"),
                "intersectionGeometrySource": frame.get("intersection_geometry_source"),
                "laneGeometryRoundabout": frame.get("lane_geometry_roundabout"),
            }
            for frame in frames
        ],
    }


def add_following_lane_tags(tags: dict, following: dict) -> dict:
    events = list(tags.get("events") or [])
    events.extend(
        following_lane_event_payload(interval)
        for interval in following.get("intervals", [])
        if interval.get("scenario")
    )
    events.sort(
        key=lambda event: (
            event.get("startFrame", -1),
            event.get("scenario", ""),
        )
    )
    tags = dict(tags)
    tags["available"] = bool(events)
    tags["scenarios"] = sorted({event["scenario"] for event in events})
    tags["events"] = events
    tags["sourceKind"] = f"{tags.get('sourceKind') or 'scenario_tags'}+generated_lane_tracker"
    return tags


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
        "topologyClass": [],
        "topologySubtype": [],
        "topologyConfidence": [],
        "topologyGeometryConfidence": [],
        "activeIsIntersection": [],
        "activeTopologySubtype": [],
        "egoInsideTopologyPolygon": [],
        "distanceToTopologyPolygonM": [],
        "topologyComponentId": [],
        "intersectionGeometrySource": [],
        "laneGeometryRoundabout": [],
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
        frame_context["topologyClass"].append(frame.get("topology_class", "normal"))
        frame_context["topologySubtype"].append(
            frame.get("topology_subtype", "normal")
        )
        frame_context["topologyConfidence"].append(
            frame.get("topology_confidence", 0.0)
        )
        frame_context["topologyGeometryConfidence"].append(
            frame.get("component_geometry_confidence", 0.0)
        )
        frame_context["activeIsIntersection"].append(
            bool(frame.get("active_is_intersection", False))
        )
        frame_context["activeTopologySubtype"].append(
            frame.get("active_topology_subtype", "normal")
        )
        frame_context["egoInsideTopologyPolygon"].append(
            bool(frame.get("ego_inside_topology_polygon"))
        )
        frame_context["distanceToTopologyPolygonM"].append(
            frame.get("distance_to_topology_polygon_m")
        )
        frame_context["topologyComponentId"].append(
            frame.get("topology_component_id")
        )
        frame_context["intersectionGeometrySource"].append(
            frame.get("intersection_geometry_source")
        )
        frame_context["laneGeometryRoundabout"].append(
            frame.get("lane_geometry_roundabout")
        )

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
      <label><input id="showDetectedTopologyAreas" type="checkbox" checked /> Detected topology areas</label>
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
      <div class="note">Scenario tags use inclusive frame/time sample bounds and include generated following-lane intervals.</div>
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
  high_magnitude_speed: '#7c3aed', high_lateral_acceleration: '#f59e0b',
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
const ldTopology = DATA.ldTopology || {summary: {}, frames: [], components: []};
const ldFrames = ld.frameContext;
const ldLineById = Object.fromEntries(ld.laneLines.map(feature => [String(feature.id), feature]));
const ldBoundaryById = Object.fromEntries(ld.boundaries.map(feature => [String(feature.id), feature]));
const ldRoadmarkById = Object.fromEntries(ld.roadmarks.map(feature => [String(feature.id), feature]));
const VEHICLE_CLASSES = new Set(['car', 'truck', 'truck_head', 'bus', 'trailer', 'motorcycle', 'bicycle']);
const DEBUG_BASE = `debug/${encodeURIComponent(DATA.summary.recording)}`;
document.getElementById('statLdPoints').textContent = ld.summary.points;
document.getElementById('statLdLanes').textContent = `${ld.summary.laneLines} / ${ld.summary.lanes}`;
document.getElementById('statLdBoundaries').textContent = `${ld.summary.roadBoundaries} / ${ld.summary.roadmarks} · ${ldTopology.summary.components || 0} topology`;
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

function topologyClassColor(name) {
  return {
    'x-intersection': '#dc2626',
    't-intersection': '#ea580c',
    'y-intersection': '#d946ef',
    roundabout: '#7c3aed',
    intersection_unknown: '#0891b2',
    normal: '#64748b'
  }[name] || '#64748b';
}

function topologyClassFillColor(name) {
  return {
    'x-intersection': 'rgba(220, 38, 38, 0.24)',
    't-intersection': 'rgba(234, 88, 12, 0.24)',
    'y-intersection': 'rgba(217, 70, 239, 0.24)',
    roundabout: 'rgba(124, 58, 237, 0.24)',
    intersection_unknown: 'rgba(8, 145, 178, 0.24)',
    normal: 'rgba(100, 116, 139, 0.24)'
  }[name] || 'rgba(100, 116, 139, 0.24)';
}

function detectedTopologyAreaTraces() {
  const traces = [];
  if (!document.getElementById('showDetectedTopologyAreas').checked) return traces;
  const centerX = [], centerY = [], centerCustom = [], centerColors = [];
  for (const component of ldTopology.components || []) {
    const polygon = component.polygon || [];
    if (polygon.length < 3) continue;
    const x = polygon.map(point => point[0]);
    const y = polygon.map(point => point[1]);
    x.push(polygon[0][0]);
    y.push(polygon[0][1]);
    const color = topologyClassColor(component.class || 'normal');
    traces.push({
      type: 'scatter', mode: 'lines', fill: 'toself',
      name: `detected topology: ${component.class || 'normal'}`,
      x, y,
      line: {color, width: 5, dash: component.class === 'normal' ? 'dash' : 'solid'},
      fillcolor: topologyClassFillColor(component.class || 'normal'),
      opacity: 0.95,
      customdata: x.map(() => [
        component.id,
        component.class || 'normal',
        component.confidence || 0,
        component.externalCorridorCandidateCount || 0,
        component.physicalArmCandidateCount || 0,
        component.decisionReason || ''
      ]),
      hovertemplate: 'detected topology %{customdata[0]}<br>class=%{customdata[1]}<br>confidence=%{customdata[2]:.2f}<br>external corridors=%{customdata[3]} · physical arms=%{customdata[4]}<br>%{customdata[5]}<extra></extra>'
    });
    if (component.center) {
      centerX.push(component.center[0]);
      centerY.push(component.center[1]);
      centerColors.push(color);
      centerCustom.push([
        component.id,
        component.class || 'normal',
        component.confidence || 0,
        component.externalCorridorCandidateCount || 0,
        component.physicalArmCandidateCount || 0,
        component.decisionReason || ''
      ]);
    }
  }
  if (centerX.length) {
    traces.push({
      type: 'scattergl', mode: 'markers',
      name: 'detected topology centers',
      x: centerX, y: centerY,
      marker: {size: 13, symbol: 'diamond-open', color: centerColors, line: {width: 3}},
      customdata: centerCustom,
      hovertemplate: 'detected topology center %{customdata[0]}<br>class=%{customdata[1]}<br>confidence=%{customdata[2]:.2f}<br>external corridors=%{customdata[3]} · physical arms=%{customdata[4]}<br>%{customdata[5]}<extra></extra>'
    });
  }
  const currentComponentId = ldFrames.topologyComponentId[currentIndex];
  if (currentComponentId) {
    const currentComponent = (ldTopology.components || []).find(
      component => component.id === currentComponentId
    );
    if (currentComponent && currentComponent.center) {
      traces.push({
        type: 'scattergl', mode: 'markers',
        name: 'current topology component',
        x: [currentComponent.center[0]], y: [currentComponent.center[1]],
        marker: {
          size: 15,
          symbol: 'x',
          color: topologyClassColor(currentComponent.class || 'normal'),
          line: {width: 3, color: '#111827'}
        },
        customdata: [[
          currentComponent.id,
          currentComponent.class || 'normal',
          currentComponent.confidence || 0,
          currentComponent.externalCorridorCandidateCount || 0,
          currentComponent.physicalArmCandidateCount || 0,
          ldFrames.egoInsideTopologyPolygon[currentIndex] ? 'ego inside polygon' : 'ego outside polygon'
        ]],
        hovertemplate: 'current topology %{customdata[0]}<br>class=%{customdata[1]}<br>confidence=%{customdata[2]:.2f}<br>external corridors=%{customdata[3]} · physical arms=%{customdata[4]}<br>%{customdata[5]}<extra></extra>'
      });
    }
  }
  return traces;
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
  traces.push(...detectedTopologyAreaTraces());
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

function formatRoundaboutMetric(metric) {
  if (!metric) return 'roundabout evidence: none';
  const source = metric.source || 'unknown source';
  const radius = metric.radius_m == null ? 'n/a' : `${Number(metric.radius_m).toFixed(1)} m radius`;
  const coverage = metric.angular_coverage_deg == null ? 'n/a' : `${Number(metric.angular_coverage_deg).toFixed(0)} deg coverage`;
  const tangent = metric.tangent_radial_score == null ? 'n/a' : `tangent ${Number(metric.tangent_radial_score).toFixed(2)}`;
  const count = metric.line_count ?? metric.lane_count ?? 'n/a';
  return `roundabout evidence: ${source} · ${count} lines/lanes · ${radius} · ${coverage} · ${tangent}`;
}

function updateLdContext() {
  const i = currentIndex;
  const invalid = ld.summary.invalidLaneEndpointOrders;
  const topologyClass = ldFrames.topologyClass[i] || 'normal';
  const topologySubtype = ldFrames.activeTopologySubtype[i] || ldFrames.topologySubtype[i] || topologyClass;
  const topologyConfidence = Number(ldFrames.topologyConfidence[i] || 0).toFixed(2);
  const topologyGeometryConfidence = Number(ldFrames.topologyGeometryConfidence[i] || 0).toFixed(2);
  const activeIntersection = ldFrames.activeIsIntersection[i] ? 'intersection component' : 'not intersection-active';
  const topologyInside = ldFrames.egoInsideTopologyPolygon[i] ? 'inside' : 'outside';
  const topologyDistance = formatDistance(ldFrames.distanceToTopologyPolygonM[i]);
  const topologyComponentId = ldFrames.topologyComponentId[i];
  const topologyComponent = topologyComponentId
    ? (ldTopology.components || []).find(component => component.id === topologyComponentId)
    : null;
  const externalCorridors = topologyComponent ? topologyComponent.externalCorridorCandidateCount || 0 : 0;
  const physicalArms = topologyComponent ? topologyComponent.physicalArmCandidateCount || 0 : 0;
  const roundaboutMetric = ldFrames.laneGeometryRoundabout ? ldFrames.laneGeometryRoundabout[i] : null;
  document.getElementById('ldContext').innerHTML =
    `<b>Frame ${i} LD context</b><br>` +
    `nearby: ${ldFrames.lineCount[i]} lines · ${ldFrames.laneCount[i]} lanes · ${ldFrames.boundaryCount[i]} boundaries · ${ldFrames.topologyCount[i]} topologies · ${ldFrames.roadmarkCount[i]} roadmarks<br>` +
    `intersection context: ${ldFrames.intersectionLineCount[i]} nearby lines with intersection=true<br>` +
    `detected topology: ${topologyClass} · subtype ${topologySubtype} · ${activeIntersection}<br>` +
    `external corridors considered: ${externalCorridors} · physical arm candidates: ${physicalArms}<br>` +
    `topology confidence: subtype ${topologyConfidence} · geometry ${topologyGeometryConfidence} · ${topologyInside} polygon · distance ${topologyDistance}<br>` +
    `${formatRoundaboutMetric(roundaboutMetric)}<br>` +
    `nearest: line ${formatDistance(ldFrames.nearestLineM[i])} · boundary ${formatDistance(ldFrames.nearestBoundaryM[i])} · roadmark ${formatDistance(ldFrames.nearestRoadmarkM[i])}<br>` +
    `OD: lead ${ldFrames.leadObjectId[i] ?? 'none'} · motional within 30m ${ldFrames.nearbyMotionalCount[i]}<br>` +
    `source quality: ${invalid} invalid lane endpoint-order reference${invalid === 1 ? '' : 's'}`;
}

function renderLdTimeline() {
  const topologyActive = ldFrames.topologyClass.map((name, index) =>
    (ldFrames.egoInsideTopologyPolygon[index] &&
     ['intersection_unknown', 'x-intersection', 't-intersection', 'y-intersection', 'roundabout'].includes(name)) ? 1 : 0
  );
  const traces = [
    {type: 'scattergl', mode: 'lines', x: traj.rel_t, y: ldFrames.nearestLineM, name: 'nearest lane line m', line: {color: '#0284c7'}},
    {type: 'scattergl', mode: 'lines', x: traj.rel_t, y: ldFrames.nearestBoundaryM, name: 'nearest boundary m', line: {color: '#b45309'}},
    {type: 'scattergl', mode: 'lines', x: traj.rel_t, y: ldFrames.nearestRoadmarkM, name: 'nearest roadmark m', line: {color: '#e11d48'}},
    {type: 'scattergl', mode: 'lines', x: traj.rel_t, y: ldFrames.nearbyMotionalCount, name: 'OD motional within 30m', yaxis: 'y2', line: {color: '#16a34a'}},
    {type: 'scattergl', mode: 'lines', x: traj.rel_t, y: ldFrames.lineCount, name: 'LD lines within 100m', yaxis: 'y2', line: {color: '#7c3aed', dash: 'dot'}},
    {type: 'scattergl', mode: 'lines', x: traj.rel_t, y: topologyActive, name: 'topology active', yaxis: 'y2', line: {color: '#dc2626', width: 3}}
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
        '    <label for="classFilter">Object classes</label>',
        LD_CONTROLS_HTML
        + TAG_CONTROLS_HTML
        + '\n    <label for="classFilter">Object classes</label>',
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
        "for (const id of ['showFootprints','showObjects','showEgoMarkers','showObjectHeadings','persistStatic','showLaneLines','showIntersectionLines','showBoundaries','showRoadmarks','showTopology','showDetectedTopologyAreas','topologyFilter','showLaneAnchors','showNearbyLd','showTags','showRoadFeatureRelations','showObjectRelations','showDynamicObjectVelocities','showPathCrossingRelations','showConfirmedCrossingsOnly']) document.getElementById(id).addEventListener('change', render);\n"
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


def index_cards_html(rows: list[dict]) -> str:
    return "\n".join(
        f"""<a class="card" href="{html.escape(row['file'])}" data-recording="{html.escape(row['recording'])}">
  <div class="route">{row['thumbnail']}</div>
  <h2>{html.escape(row['recording'])}</h2>
  <div class="metrics"><span>{row['frames']} frames</span><span>{row['duration']:.1f}s</span><span>{row['objects']} objects</span></div>
  <div class="metrics"><span>{row['lines']} lane lines</span><span>{row['boundaries']} boundaries</span><span>{row['roadmarks']} roadmarks</span></div>
  <div class="metrics"><span>{row['tagScenarios']} tagged scenarios</span><span>{row['tagEvents']} tag intervals</span></div>
  <p>{html.escape(row['topClasses'])}</p>
</a>"""
        for row in rows
    )


def index_html(rows: list[dict]) -> str:
    cards = index_cards_html(rows)
    scenario_options = sorted(
        {
            scenario
            for row in rows
            for scenario in row.get("tagScenarioList", [])
        }
        | set(PHASE4_SCENARIOS)
    )
    scenario_items = "".join(
        f'<label class="scenarioChoice"><input type="checkbox" value="{html.escape(scenario)}"><span>{html.escape(scenario)}</span></label>'
        for scenario in scenario_options
    )
    row_json = json.dumps(rows, ensure_ascii=True, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OD + LD + Ego Trajectory Explorers</title>
<style>
body{{margin:0;font-family:Arial,sans-serif;background:#eef2f6;color:#17202a}}header{{padding:20px 28px 18px;background:#17324d;color:white}}header h1{{margin:0 0 5px;font-size:22px;font-weight:700}}header p{{margin:0;opacity:.84;font-size:13px}}.toolbar{{position:sticky;top:0;z-index:5;background:#f8fafc;border-bottom:1px solid #cbd5e1;padding:14px 22px 12px;box-shadow:0 6px 18px rgba(15,23,42,.06)}}.controlRow{{display:grid;grid-template-columns:minmax(260px,2fr) minmax(110px,.7fr) minmax(130px,.8fr) minmax(150px,1fr) minmax(130px,.8fr) auto auto;gap:10px;align-items:end}}label{{display:grid;gap:5px;font-size:11px;font-weight:700;color:#475569;text-transform:uppercase}}input,select{{height:34px;border:1px solid #cbd5e1;border-radius:6px;background:white;color:#17202a;padding:0 9px;font-size:13px}}button{{height:34px;border:1px solid #94a3b8;border-radius:6px;background:#ffffff;color:#334155;padding:0 12px;font-size:13px;cursor:pointer}}button:hover{{border-color:#2563eb;color:#1d4ed8}}.count{{font-size:13px;color:#334155;white-space:nowrap;padding-bottom:9px}}.scenarioPanel{{margin-top:11px;border:1px solid #d7dee8;border-radius:8px;background:white}}.scenarioHeader{{display:flex;justify-content:space-between;gap:12px;padding:8px 10px;border-bottom:1px solid #e2e8f0;color:#475569;font-size:12px}}.scenarioHeader strong{{color:#334155}}.scenarioChoices{{max-height:82px;overflow:auto;padding:8px;display:flex;gap:6px;flex-wrap:wrap;align-content:flex-start}}.scenarioChoice{{display:flex;align-items:center;gap:5px;border:1px solid #cbd5e1;border-radius:999px;padding:4px 8px;font-size:12px;font-weight:400;color:#17202a;text-transform:none;white-space:nowrap;background:#f8fafc}}.scenarioChoice:has(input:checked){{background:#dbeafe;border-color:#60a5fa;color:#1e3a8a}}.scenarioChoice input{{width:13px;height:13px;padding:0;margin:0}}main{{padding:18px 22px 24px;display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px}}.card{{display:block;background:white;border:1px solid #d7dee8;border-radius:8px;padding:12px;text-decoration:none;color:inherit;box-shadow:0 1px 4px rgba(15,23,42,.05)}}.card:hover{{border-color:#2563eb;box-shadow:0 5px 16px rgba(37,99,235,.12)}}h2{{font-size:15px;margin:9px 0 8px;overflow-wrap:anywhere;line-height:1.25}}.route{{height:96px;background:#f8fafc;border-radius:6px;overflow:hidden;border:1px solid #eef2f7}}.route svg{{width:100%;height:100%}}.metrics{{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}}.metrics span{{background:#edf2f7;border-radius:999px;padding:3px 7px;font-size:11px;color:#334155}}p{{font-size:12px;color:#64748b;line-height:1.4;margin:8px 0 0}}.empty{{padding:28px;color:#64748b}}@media (max-width:1060px){{.controlRow{{grid-template-columns:1fr 1fr 1fr}}.count{{padding-bottom:0}}}}@media (max-width:680px){{header{{padding:16px}}.toolbar{{padding:12px}}.controlRow{{grid-template-columns:1fr}}main{{grid-template-columns:1fr;padding:12px}}}}
</style></head><body><header><h1>OD + LD + Ego Trajectory Explorers</h1><p>Synchronized scene viewers with OD tracks, complete LD map layers, scenario-tag intervals, frame-local context, playback, timelines, and notes.</p></header>
<section class="toolbar">
  <div class="controlRow">
    <label>Search<input id="recordingSearch" type="search" autocomplete="off"></label>
    <label>Min objects<input id="minObjectsFilter" type="number" min="0" step="1"></label>
    <label>Min tag events<input id="minTagEventsFilter" type="number" min="0" step="1"></label>
    <label>Sort<select id="sortField"><option value="recording">Recording</option><option value="frames">Frames</option><option value="duration">Duration</option><option value="objects">Objects</option><option value="tagEvents">Tag intervals</option><option value="tagScenarios">Tagged scenarios</option></select></label>
    <label>Order<select id="sortDirection"><option value="asc">Ascending</option><option value="desc">Descending</option></select></label>
    <button id="clearFilters" type="button">Clear</button>
    <div id="resultCount" class="count"></div>
  </div>
  <div class="scenarioPanel">
    <div class="scenarioHeader"><strong>Scenario tags</strong><span>matches all selected</span></div>
    <div id="scenarioFilter" class="scenarioChoices">{scenario_items}</div>
  </div>
</section>
<main id="recordingGrid">{cards}</main>
<script>
const INDEX_ROWS = {row_json};
const grid = document.getElementById('recordingGrid');
const count = document.getElementById('resultCount');
const controls = ['recordingSearch','scenarioFilter','minObjectsFilter','minTagEventsFilter','sortField','sortDirection'].map(id => document.getElementById(id));
function escapeHtml(value) {{
  return String(value ?? '').replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
}}
function numericValue(id) {{
  const value = Number(document.getElementById(id).value);
  return Number.isFinite(value) ? value : 0;
}}
function cardHtml(row) {{
  return `<a class="card" href="${{escapeHtml(row.file)}}" data-recording="${{escapeHtml(row.recording)}}">
  <div class="route">${{row.thumbnail || ''}}</div>
  <h2>${{escapeHtml(row.recording)}}</h2>
  <div class="metrics"><span>${{row.frames}} frames</span><span>${{Number(row.duration).toFixed(1)}}s</span><span>${{row.objects}} objects</span></div>
  <div class="metrics"><span>${{row.lines}} lane lines</span><span>${{row.boundaries}} boundaries</span><span>${{row.roadmarks}} roadmarks</span></div>
  <div class="metrics"><span>${{row.tagScenarios}} tagged scenarios</span><span>${{row.tagEvents}} tag intervals</span></div>
  <p>${{escapeHtml(row.topClasses)}}</p>
</a>`;
}}
function applyIndexFilters() {{
  const query = document.getElementById('recordingSearch').value.trim().toLowerCase();
  const selectedScenarios = [...document.querySelectorAll('#scenarioFilter input:checked')].map(input => input.value);
  const minObjects = numericValue('minObjectsFilter');
  const minTagEvents = numericValue('minTagEventsFilter');
  const sortField = document.getElementById('sortField').value;
  const direction = document.getElementById('sortDirection').value === 'desc' ? -1 : 1;
  const filtered = INDEX_ROWS.filter(row => {{
    if (query && !String(row.recording).toLowerCase().includes(query)) return false;
    if (selectedScenarios.length && !selectedScenarios.every(scenario => (row.tagScenarioList || []).includes(scenario))) return false;
    if (Number(row.objects) < minObjects) return false;
    if (Number(row.tagEvents) < minTagEvents) return false;
    return true;
  }}).sort((a, b) => {{
    const av = a[sortField];
    const bv = b[sortField];
    if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * direction;
    return String(av).localeCompare(String(bv), undefined, {{numeric: true}}) * direction;
  }});
  grid.innerHTML = filtered.length ? filtered.map(cardHtml).join('') : '<div class="empty">No matching recordings</div>';
  count.textContent = `${{filtered.length}} / ${{INDEX_ROWS.length}} recordings`;
}}
for (const control of controls) control.addEventListener('input', applyIndexFilters);
for (const control of controls) control.addEventListener('change', applyIndexFilters);
document.getElementById('clearFilters').addEventListener('click', () => {{
  document.getElementById('recordingSearch').value = '';
  document.getElementById('minObjectsFilter').value = '';
  document.getElementById('minTagEventsFilter').value = '';
  document.getElementById('sortField').value = 'recording';
  document.getElementById('sortDirection').value = 'asc';
  for (const input of document.querySelectorAll('#scenarioFilter input')) input.checked = false;
  applyIndexFilters();
}});
applyIndexFilters();
</script></body></html>"""


def inject_lane_tracker(output_path: Path, following_lane_result: dict) -> None:
    render_original_explorer_with_lane_tracker(
        output_path, following_lane_result, output_path
    )


def write_explorer_atomically(
    output_path: Path, data: dict, following_lane_result: dict
) -> None:
    temp_path = output_path.with_name(f".{output_path.name}.tmp")
    temp_path.write_text(scene_html(data), encoding="utf-8")
    inject_lane_tracker(temp_path, following_lane_result)
    temp_path.replace(output_path)


def row_from_explorer(output_path: Path) -> dict:
    match = EXPLORER_DATA_MARKER.search(output_path.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"Unable to read explorer payload: {output_path}")
    data = json.loads(match.group(1))
    try:
        return {
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
            "tagScenarioList": data["tags"]["scenarios"],
            "topClasses": ", ".join(
                f"{key}:{value}"
                for key, value in list(data["summary"]["classCounts"].items())[:6]
            ),
            "thumbnail": base.thumbnail_svg(data),
        }
    finally:
        del data


def explorer_output_name(recording: str) -> str:
    return f"{recording}_animated_odld_explorer.html"


def format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remaining_seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m {remaining_seconds:.1f}s"
    hours, remaining_minutes = divmod(minutes, 60)
    return f"{int(hours)}h {int(remaining_minutes)}m {remaining_seconds:.1f}s"


def recording_from_canonical_path(canonical_path: Path) -> str:
    return canonical_path.name.removesuffix("_canonical_odld_frames.json")


def row_has_valid_manifest_metadata(row: object) -> bool:
    return isinstance(row, dict) and all(key in row for key in INDEX_ROW_KEYS)


def read_manifest_rows(output_dir: Path) -> dict[str, dict]:
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.is_file():
        return {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        return {}
    rows = {}
    for row in manifest.get("recordings", []):
        if not row_has_valid_manifest_metadata(row):
            continue
        recording = row["recording"]
        output_path = output_dir / row["file"]
        if output_path.is_file():
            rows[recording] = row
    return rows


def existing_rows_by_recording(output_dir: Path) -> dict[str, dict]:
    rows = {}
    output_paths = sorted(output_dir.glob("*_animated_odld_explorer.html"))
    progress = ProgressReporter("explorer-index", len(output_paths), "recording")
    progress.start()
    for output_path in output_paths:
        row = row_from_explorer(output_path)
        rows[row["recording"]] = row
        progress.advance(row["recording"])
        gc.collect()
    return rows


def resolve_index_path(index_path: Path, output_dir: Path) -> Path:
    if str(index_path) in ("", "."):
        return output_dir.parent / DEFAULT_INDEX_PATH.name
    if index_path.exists() and index_path.is_dir():
        return index_path / "index.html"
    return index_path


def write_index_and_manifest(index_path: Path, output_dir: Path, rows: list[dict]) -> None:
    index_path = resolve_index_path(index_path, output_dir)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(index_html(rows), encoding="utf-8")
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "index": index_path.name,
        "recordings": [{key: row[key] for key in INDEX_ROW_KEYS} for row in rows],
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8"
    )
    print(f"Wrote index: {index_path}")
    print(f"Wrote manifest: {manifest_path}")


def rebuild_rows_from_outputs(output_dir: Path, rows_by_recording: dict[str, dict]) -> list[dict]:
    rows = dict(rows_by_recording)
    output_paths = sorted(output_dir.glob("*_animated_odld_explorer.html"))
    progress = ProgressReporter("explorer-index", len(output_paths), "recording")
    progress.start()
    for output_path in output_paths:
        recording = output_path.name.removesuffix("_animated_odld_explorer.html")
        if row_has_valid_manifest_metadata(rows.get(recording)):
            progress.advance(f"{recording}: manifest")
            continue
        row = row_from_explorer(output_path)
        rows[row["recording"]] = row
        progress.advance(f"{row['recording']}: parsed")
        gc.collect()
    return sorted(rows.values(), key=lambda row: row["recording"])


def row_from_generated_data(recording: str, output_name: str, data: dict) -> dict:
    return {
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
        "tagScenarioList": data["tags"]["scenarios"],
        "topClasses": ", ".join(
            f"{key}:{value}"
            for key, value in list(data["summary"]["classCounts"].items())[:6]
        ),
        "thumbnail": base.thumbnail_svg(data),
    }


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
    parser.add_argument(
        "--regenerate-existing",
        action="store_true",
        help="Regenerate explorer HTML even when the output file already exists.",
    )
    parser.add_argument("recordings", nargs="*")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.index_from_existing:
        rows = sorted(
            existing_rows_by_recording(args.output_dir).values(),
            key=lambda row: row["recording"],
        )
        write_index_and_manifest(args.index_path, args.output_dir, rows)
        return

    canonical_paths = sorted(args.canonical_dir.glob("*_canonical_odld_frames.json"))
    if args.recordings:
        requested = set(args.recordings)
        canonical_paths = [
            path
            for path in canonical_paths
            if recording_from_canonical_path(path) in requested
        ]
    rows_by_recording = read_manifest_rows(args.output_dir)
    generation_progress = ProgressReporter(
        "odld-explorers", len(canonical_paths), "recording"
    )
    generation_progress.start()
    total_started_at = time.perf_counter()
    for index, canonical_path in enumerate(canonical_paths, 1):
        recording_started_at = time.perf_counter()
        recording = recording_from_canonical_path(canonical_path)
        output_name = explorer_output_name(recording)
        output_path = args.output_dir / output_name
        if output_path.is_file() and not args.regenerate_existing:
            elapsed = format_elapsed(time.perf_counter() - recording_started_at)
            print(
                f"[{index}/{len(canonical_paths)}] {recording}: "
                f"skipped existing explorer in {elapsed}"
            )
            generation_progress.advance(f"{recording}: skipped")
            continue
        with canonical_path.open(encoding="utf-8") as handle:
            canonical = json.load(handle)
        recording = canonical["recording_id"]
        ld_topology_result = build_ld_topology_result(canonical)
        canonical = canonical_with_ld_topology(canonical, ld_topology_result)
        scene_dir = args.source_root / recording
        data = build_base_data(scene_dir)
        data["ld"] = build_ld_payload(canonical)
        data["ldTopology"] = build_ld_topology_payload(ld_topology_result)
        data["roadFeatureRelations"] = build_road_feature_payload(canonical)
        data["objectRelations"] = build_object_relation_payload(canonical)
        data["pathCrossingRelations"] = build_object_path_crossing_payload(
            canonical
        )
        following_lane_result = run_following_lane(canonical)
        data["tags"] = build_tag_payload(
            recording, args.window_dir, canonical
        )
        data["tags"] = add_following_lane_tags(data["tags"], following_lane_result)
        debug_counts = write_debug_payloads(scene_dir, canonical, args.output_dir)
        write_explorer_atomically(output_path, data, following_lane_result)
        rows_by_recording[recording] = row_from_generated_data(
            recording, output_name, data
        )
        elapsed = format_elapsed(time.perf_counter() - recording_started_at)
        print(
            f"[{index}/{len(canonical_paths)}] {recording}: "
            f"{data['summary']['objects']} objects, "
            f"{data['ld']['summary']['laneLines']} lane lines, "
            f"{data['ld']['summary']['roadBoundaries']} boundaries, "
            f"{len(data['tags']['scenarios'])} tagged scenarios / "
            f"{len(data['tags']['events'])} intervals, "
            f"{debug_counts['od']} OD + {debug_counts['ld']} LD debug records, "
            f"generated in {elapsed}"
        )
        generation_progress.advance(f"{recording}: generated")
        # Each recording can embed tens of MB of OD/LD payload. Release it
        # before loading the next scene so all-recording regeneration remains
        # reliable on Windows.
        del canonical, data
        gc.collect()
    rows = rebuild_rows_from_outputs(args.output_dir, rows_by_recording)
    write_index_and_manifest(args.index_path, args.output_dir, rows)
    print(
        f"Finished {len(canonical_paths)} recording(s) in "
        f"{format_elapsed(time.perf_counter() - total_started_at)}"
    )


if __name__ == "__main__":
    main()
