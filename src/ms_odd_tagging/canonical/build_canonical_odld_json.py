#!/usr/bin/env python3
"""Build canonical OD + recording-level LD map + ego trajectory JSON.

This is an isolated experimental extension of build_canonical_od_json.py.  The
OD and ego fields intentionally retain the existing canonical semantics.  LD
geometry is stored once in ``ld_feature_store``; frames carry compact nearby
IDs and ego-relative distance summaries instead of duplicated polylines.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

import build_canonical_od_json as od


SCHEMA_VERSION = "odld-trajectory-canonical-frame-v1"
MANIFEST_SCHEMA_VERSION = "odld-trajectory-canonical-manifest-v1"
DEFAULT_SOURCE_ROOT = Path(
    "data"
)
DEFAULT_OUTPUT_ROOT = Path(
    "outputs/canonical_frames"
)


def portable_path(path: Path) -> str:
    """Return a portable path, relative to the working tree when possible."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def require_finite_xyz(value, context: str) -> tuple[float, float, float]:
    if not isinstance(value, dict):
        raise ValueError(f"{context}: expected an object")
    coordinates = tuple(value.get(axis) for axis in ("x", "y", "z"))
    if not all(od.finite_number(component) for component in coordinates):
        raise ValueError(f"{context}: x/y/z must be finite")
    return coordinates


def attributes_as_object(attributes) -> dict:
    if isinstance(attributes, dict):
        return dict(attributes)
    return od.attributes_as_object(attributes)


def ordered_elements(feature: dict) -> list[dict]:
    return [
        {"point_id": str(element["pointId"]), "order": element.get("order")}
        for element in sorted(
            feature.get("elements", []), key=lambda item: item.get("order", 0)
        )
    ]


def normalize_ld(ld: dict) -> tuple[dict, dict]:
    """Normalize LD map geometry and build private indexes for spatial queries."""
    lanes_root = ld.get("lanes")
    if not isinstance(lanes_root, dict):
        raise ValueError("LD annotations are missing the lanes object")

    raw_points = lanes_root.get("points", [])
    point_by_id: dict[str, dict] = {}
    points = []
    duplicate_point_ids = 0
    for index, point in enumerate(raw_points):
        point_id = str(point["pointId"])
        if point_id in point_by_id:
            duplicate_point_ids += 1
        x, y, z = require_finite_xyz(point, f"LD point {point_id} at index {index}")
        normalized = {
            "point_id": point_id,
            "type": point.get("type"),
            "position_lcs_m": [od.round_or_none(x), od.round_or_none(y), od.round_or_none(z)],
        }
        if "width" in point:
            width = point.get("width")
            if not od.finite_number(width):
                raise ValueError(f"LD point {point_id}: width must be finite when present")
            normalized["width_m"] = od.round_or_none(width)
        points.append(normalized)
        point_by_id[point_id] = normalized

    missing_feature_point_references = 0

    def normalize_edge(raw: dict, id_key: str, output_id_key: str) -> dict:
        nonlocal missing_feature_point_references
        elements = ordered_elements(raw)
        point_ids = [element["point_id"] for element in elements]
        missing = [point_id for point_id in point_ids if point_id not in point_by_id]
        missing_feature_point_references += len(missing)
        result = {
            output_id_key: str(raw[id_key]),
            "class": raw.get("className"),
            "elements": elements,
            "point_ids": point_ids,
            "attributes": attributes_as_object(raw.get("staticAttributes")),
            "validity": {
                "all_point_references_resolve": not missing,
                "missing_point_ids": missing,
            },
        }
        if "subClassName" in raw:
            result["subclass"] = raw.get("subClassName")
        if "attribute" in raw:
            result["boundary_attribute"] = raw.get("attribute")
        return result

    lane_lines = [
        normalize_edge(raw, "lineId", "line_id") for raw in lanes_root.get("lines", [])
    ]
    road_boundaries = [
        normalize_edge(raw, "roadBoundaryId", "road_boundary_id")
        for raw in lanes_root.get("roadBoundaries", [])
    ]
    edge_by_id = {
        feature["line_id"]: feature for feature in lane_lines
    } | {
        feature["road_boundary_id"]: feature for feature in road_boundaries
    }

    missing_lane_edge_references = 0
    invalid_lane_endpoint_orders = 0
    normalized_lanes = []
    lane_geometry_ids: dict[str, list[str]] = {}
    invalid_lane_ids: set[str] = set()

    for raw_lane in lanes_root.get("lanes", []):
        lane_id = str(raw_lane["laneId"])
        normalized_boundaries = {}
        geometry_ids = []
        lane_valid = True
        for side, source_key in (("left", "leftBoundary"), ("right", "rightBoundary")):
            reference = raw_lane.get(source_key)
            if not isinstance(reference, dict):
                normalized_boundaries[side] = None
                lane_valid = False
                continue
            edge_id = str(reference.get("edgeId"))
            edge = edge_by_id.get(edge_id)
            endpoint_orders = reference.get("pointIds") or {}
            start_order = endpoint_orders.get("start")
            end_order = endpoint_orders.get("end")
            edge_resolves = edge is not None
            if not edge_resolves:
                missing_lane_edge_references += 1
                order_valid = False
                selected_ids = []
            else:
                order_to_index = {
                    element["order"]: index
                    for index, element in enumerate(edge["elements"])
                }
                order_valid = (
                    start_order in order_to_index and end_order in order_to_index
                )
                if order_valid:
                    start_index = order_to_index[start_order]
                    end_index = order_to_index[end_order]
                    step = 1 if end_index >= start_index else -1
                    selected_ids = edge["point_ids"][start_index : end_index + step : step]
                else:
                    # Preserve usability without pretending the invalid range is sound.
                    selected_ids = list(edge["point_ids"])
                    invalid_lane_endpoint_orders += 1
            if not order_valid:
                lane_valid = False
            geometry_ids.extend(selected_ids)
            normalized_boundaries[side] = {
                "edge_id": edge_id,
                "start_order": start_order,
                "end_order": end_order,
                "edge_reference_valid": edge_resolves,
                "endpoint_order_valid": order_valid,
                "geometry_fallback": "full_edge" if edge_resolves and not order_valid else None,
            }
        geometry_ids = list(dict.fromkeys(geometry_ids))
        lane_geometry_ids[lane_id] = geometry_ids
        if not lane_valid:
            invalid_lane_ids.add(lane_id)
        normalized_lanes.append(
            {
                "lane_id": lane_id,
                "class": raw_lane.get("className"),
                "subclass": raw_lane.get("subClassName"),
                "boundaries": normalized_boundaries,
                "validity": {"boundary_ranges_valid": lane_valid},
            }
        )

    normalized_lane_id_list = [lane["lane_id"] for lane in normalized_lanes]
    lane_ids = set(normalized_lane_id_list)
    missing_topology_lane_references = 0
    topologies = []
    for raw in lanes_root.get("topologies", []):
        relations = raw.get("relationLaneIds") or {}
        source_lane_id = str(relations.get("source"))
        destination_lane_id = str(relations.get("destination"))
        missing = [
            lane_id
            for lane_id in (source_lane_id, destination_lane_id)
            if lane_id not in lane_ids
        ]
        missing_topology_lane_references += len(missing)
        topologies.append(
            {
                "topology_id": str(raw["topologyId"]),
                "class": raw.get("className"),
                "subclass": raw.get("subClassName"),
                "source_lane_id": source_lane_id,
                "destination_lane_id": destination_lane_id,
                "validity": {
                    "lane_references_resolve": not missing,
                    "missing_lane_ids": missing,
                },
            }
        )

    roadmarks = []
    ignored_roadmark_count = 0
    roadmark_geometry: dict[str, list[tuple[float, float, float]]] = {}
    for raw in ld.get("roadmarks", []):
        roadmark_id = str(raw["roadmarkId"])
        raw_attributes = attributes_as_object(raw.get("staticAttributes"))
        ignored = raw_attributes.get("ignored") is True
        ignored_roadmark_count += int(ignored)
        normalized_points = []
        geometry = []
        for index, point in enumerate(raw.get("points", [])):
            x, y, z = require_finite_xyz(
                point, f"LD roadmark {roadmark_id} point {index}"
            )
            geometry.append((x, y, z))
            normalized_point = {
                "position_lcs_m": [
                    od.round_or_none(x),
                    od.round_or_none(y),
                    od.round_or_none(z),
                ]
            }
            if "h" in point:
                normalized_point["height_m"] = od.round_or_none(point.get("h"))
            normalized_points.append(normalized_point)
        roadmark_geometry[roadmark_id] = geometry
        roadmarks.append(
            {
                "roadmark_id": roadmark_id,
                "class": raw.get("className"),
                "subclass": raw.get("subclassName"),
                "shape_type": raw.get("shapeType"),
                "points": normalized_points,
                "attributes": raw_attributes,
                "ignored": ignored,
            }
        )

    line_ids = [feature["line_id"] for feature in lane_lines]
    boundary_ids = [feature["road_boundary_id"] for feature in road_boundaries]
    duplicate_counts = {
        "point_ids": duplicate_point_ids,
        "line_ids": len(line_ids) - len(set(line_ids)),
        "lane_ids": len(normalized_lane_id_list) - len(lane_ids),
        "road_boundary_ids": len(boundary_ids) - len(set(boundary_ids)),
    }

    feature_store = {
        "source_kind": "recording_static_map",
        "source_format_version": ld.get("formatVersion"),
        "source_exported_at": ld.get("exportedAt"),
        "source_policy": ld.get("policy", []),
        "coordinate_system": {
            "name": "inferred_shared_lcs",
            "explicitly_declared_by_source": False,
            "dimensions": "3D_xyz_m",
            "notes": [
                "LD supplies recording-level x/y/z geometry and no coordinate-system label.",
                "Shared LCS is inferred from matching scene identity and spatial agreement with the ego trajectory.",
                "No 2D image-coordinate LD geometry is present.",
            ],
        },
        "points": points,
        "lane_lines": lane_lines,
        "lanes": normalized_lanes,
        "road_boundaries": road_boundaries,
        "topologies": topologies,
        "roadmarks": roadmarks,
        "freespace": {"source_present": False, "features": []},
        "filtering_metadata": {
            "confidence_available": False,
            "confidence_threshold": None,
            "confidence_filter_applied": False,
            "generic_validity_available": False,
            "ignored_roadmarks_retained_in_store": True,
            "ignored_roadmarks_excluded_from_default_frame_context": True,
        },
        "quality": {
            "duplicate_identifier_counts": duplicate_counts,
            "missing_feature_point_references": missing_feature_point_references,
            "missing_lane_edge_references": missing_lane_edge_references,
            "invalid_lane_boundary_endpoint_order_count": invalid_lane_endpoint_orders,
            "missing_topology_lane_references": missing_topology_lane_references,
            "ignored_roadmark_count": ignored_roadmark_count,
        },
    }

    def feature_geometry(features: list[dict], id_key: str) -> dict[str, list[tuple[float, float, float]]]:
        return {
            feature[id_key]: [
                tuple(point_by_id[point_id]["position_lcs_m"])
                for point_id in feature["point_ids"]
                if point_id in point_by_id
            ]
            for feature in features
        }

    private = {
        "line_geometry": feature_geometry(lane_lines, "line_id"),
        "boundary_geometry": feature_geometry(road_boundaries, "road_boundary_id"),
        "lane_geometry": {
            lane_id: [
                tuple(point_by_id[point_id]["position_lcs_m"])
                for point_id in point_ids
                if point_id in point_by_id
            ]
            for lane_id, point_ids in lane_geometry_ids.items()
        },
        "roadmark_geometry": roadmark_geometry,
        "line_by_id": {feature["line_id"]: feature for feature in lane_lines},
        "boundary_by_id": {
            feature["road_boundary_id"]: feature for feature in road_boundaries
        },
        "lane_by_id": {feature["lane_id"]: feature for feature in normalized_lanes},
        "roadmark_by_id": {
            feature["roadmark_id"]: feature for feature in roadmarks
        },
        "topologies": topologies,
        "invalid_lane_ids": invalid_lane_ids,
    }
    return feature_store, private


def minimum_ego_distance(
    geometry: list[tuple[float, float, float]], ego: dict
) -> tuple[float | None, tuple[float, float] | None]:
    best_distance = None
    best_relative = None
    for x, y, _ in geometry:
        longitudinal, lateral = od.ego_relative((x, y, 0.0), ego["position"], ego["yaw"])
        distance = math.hypot(longitudinal, lateral)
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_relative = (longitudinal, lateral)
    return best_distance, best_relative


def nearby_features(
    geometry_by_id: dict[str, list[tuple[float, float, float]]],
    ego: dict,
    radius_m: float,
) -> tuple[list[str], dict[str, dict]]:
    nearby_ids = []
    summaries = {}
    for feature_id, geometry in geometry_by_id.items():
        distance, relative = minimum_ego_distance(geometry, ego)
        if distance is None or distance > radius_m:
            continue
        nearby_ids.append(feature_id)
        summaries[feature_id] = {
            "minimum_distance_m": od.round_or_none(distance),
            "closest_longitudinal_m": od.round_or_none(relative[0]),
            "closest_lateral_m": od.round_or_none(relative[1]),
        }
    return nearby_ids, summaries


def compact_clipped_geometry(
    ids: list[str],
    geometry_by_id: dict[str, list[tuple[float, float, float]]],
    ego: dict,
    radius_m: float,
) -> list[dict]:
    """Optional visualization-only point excerpts; disabled by default."""
    clipped = []
    for feature_id in ids:
        geometry = geometry_by_id[feature_id]
        inside = []
        for index, point in enumerate(geometry):
            longitudinal, lateral = od.ego_relative(point, ego["position"], ego["yaw"])
            if math.hypot(longitudinal, lateral) <= radius_m:
                inside.append(index)
        if not inside:
            continue
        selected_indices = set(inside)
        selected_indices.add(max(0, min(inside) - 1))
        selected_indices.add(min(len(geometry) - 1, max(inside) + 1))
        points = []
        for index in sorted(selected_indices):
            x, y, z = geometry[index]
            longitudinal, lateral = od.ego_relative((x, y, z), ego["position"], ego["yaw"])
            points.append(
                {
                    "position_lcs_m": [
                        od.round_or_none(x),
                        od.round_or_none(y),
                        od.round_or_none(z),
                    ],
                    "position_ego_m": [
                        od.round_or_none(longitudinal),
                        od.round_or_none(lateral),
                        od.round_or_none(z - ego["position"][2]),
                    ],
                }
            )
        clipped.append({"feature_id": feature_id, "points": points})
    return clipped


def build_frame_ld_context(
    ego: dict,
    indexes: dict,
    radius_m: float,
    include_clipped_geometry: bool,
) -> dict:
    line_ids, line_distances = nearby_features(
        indexes["line_geometry"], ego, radius_m
    )
    boundary_ids, boundary_distances = nearby_features(
        indexes["boundary_geometry"], ego, radius_m
    )
    lane_ids, lane_distances = nearby_features(
        indexes["lane_geometry"], ego, radius_m
    )
    roadmark_ids_all, roadmark_distances_all = nearby_features(
        indexes["roadmark_geometry"], ego, radius_m
    )
    ignored_roadmark_ids = [
        feature_id
        for feature_id in roadmark_ids_all
        if indexes["roadmark_by_id"][feature_id]["ignored"]
    ]
    roadmark_ids = [
        feature_id for feature_id in roadmark_ids_all if feature_id not in ignored_roadmark_ids
    ]
    roadmark_distances = {
        feature_id: roadmark_distances_all[feature_id] for feature_id in roadmark_ids
    }
    nearby_lane_set = set(lane_ids)
    topology_ids = [
        topology["topology_id"]
        for topology in indexes["topologies"]
        if topology["source_lane_id"] in nearby_lane_set
        or topology["destination_lane_id"] in nearby_lane_set
    ]

    line_patterns = Counter(
        indexes["line_by_id"][feature_id]["attributes"].get("pattern", "unknown")
        for feature_id in line_ids
    )
    boundary_subclasses = Counter(
        indexes["boundary_by_id"][feature_id].get("subclass") or "unknown"
        for feature_id in boundary_ids
    )
    boundary_attributes = Counter(
        indexes["boundary_by_id"][feature_id].get("boundary_attribute") or "unknown"
        for feature_id in boundary_ids
    )
    roadmark_classes = Counter(
        indexes["roadmark_by_id"][feature_id].get("class") or "unknown"
        for feature_id in roadmark_ids
    )

    def nearest(distances: dict[str, dict]) -> float | None:
        values = [item["minimum_distance_m"] for item in distances.values()]
        return min(values) if values else None

    result = {
        "source_kind": "recording_static_map",
        "available": True,
        "query_radius_m": od.round_or_none(radius_m),
        "nearby_feature_ids": {
            "lane_lines": line_ids,
            "lanes": lane_ids,
            "road_boundaries": boundary_ids,
            "topologies": topology_ids,
            "roadmarks": roadmark_ids,
            "ignored_roadmarks": ignored_roadmark_ids,
            "freespace": [],
        },
        "ego_relative_feature_summaries": {
            "lane_lines": line_distances,
            "lanes": lane_distances,
            "road_boundaries": boundary_distances,
            "roadmarks": roadmark_distances,
        },
        "summary": {
            "nearby_lane_line_count": len(line_ids),
            "nearby_lane_count": len(lane_ids),
            "nearby_road_boundary_count": len(boundary_ids),
            "nearby_topology_count": len(topology_ids),
            "nearby_roadmark_count": len(roadmark_ids),
            "nearby_ignored_roadmark_count": len(ignored_roadmark_ids),
            "nearest_lane_line_distance_m": nearest(line_distances),
            "nearest_lane_distance_m": nearest(lane_distances),
            "nearest_road_boundary_distance_m": nearest(boundary_distances),
            "nearest_roadmark_distance_m": nearest(roadmark_distances),
            "lane_line_pattern_counts": dict(sorted(line_patterns.items())),
            "road_boundary_subclass_counts": dict(sorted(boundary_subclasses.items())),
            "road_boundary_attribute_counts": dict(sorted(boundary_attributes.items())),
            "roadmark_class_counts": dict(sorted(roadmark_classes.items())),
        },
        "quality_flags": {
            "confidence_available": False,
            "freespace_available": False,
            "coordinate_system_explicitly_declared": False,
            "nearby_lane_ids_with_invalid_boundary_ranges": sorted(
                nearby_lane_set & indexes["invalid_lane_ids"]
            ),
        },
        "clipped_geometry_included": include_clipped_geometry,
    }
    if include_clipped_geometry:
        result["clipped_geometry"] = {
            "lane_lines": compact_clipped_geometry(
                line_ids, indexes["line_geometry"], ego, radius_m
            ),
            "road_boundaries": compact_clipped_geometry(
                boundary_ids, indexes["boundary_geometry"], ego, radius_m
            ),
            "roadmarks": compact_clipped_geometry(
                roadmark_ids, indexes["roadmark_geometry"], ego, radius_m
            ),
        }
    return result


def build_recording(
    source_root: Path,
    output_root: Path,
    recording: str,
    ld_radius_m: float,
    include_clipped_geometry: bool,
) -> tuple[Path, dict]:
    recording_dir = source_root / recording
    od_path = recording_dir / "annotations_OD.json"
    ld_path = recording_dir / "annotations_LD.json"
    trajectory_path = recording_dir / "traj_lcs.txt"
    for required in (od_path, ld_path, trajectory_path):
        if not required.is_file():
            raise FileNotFoundError(f"{recording}: missing {required.name}")

    with od_path.open(encoding="utf-8") as handle:
        annotations = json.load(handle)
    with ld_path.open(encoding="utf-8") as handle:
        ld_annotations = json.load(handle)
    trajectory = od.parse_trajectory(trajectory_path)

    od_scene = annotations["scene"]
    ld_scene = ld_annotations["scene"]
    frame_count = od_scene["frameCount"]
    if frame_count != len(trajectory) or ld_scene.get("frameCount") != frame_count:
        raise ValueError(
            f"{recording}: OD frames={frame_count}, LD frames={ld_scene.get('frameCount')}, "
            f"trajectory rows={len(trajectory)}"
        )
    if od_scene.get("id") != ld_scene.get("id") or od_scene.get("name") != ld_scene.get("name"):
        raise ValueError(f"{recording}: OD and LD scene identity does not match")
    timestamps = [row["timestamp"] for row in trajectory]
    if any(right <= left for left, right in zip(timestamps, timestamps[1:])):
        raise ValueError(f"{recording}: trajectory timestamps are not strictly increasing")

    ld_feature_store, ld_indexes = normalize_ld(ld_annotations)
    samples = od.build_object_samples(annotations["objects"], timestamps)
    visible_at_frame = defaultdict(list)
    out_of_range_od_frame_indices = []
    for obj in annotations["objects"]:
        frame_indices = set(obj.get("visible_frames", []))
        frame_indices.update(samples[str(obj["objectId"])]["bbox_by_frame"])
        for frame_index in frame_indices:
            if 0 <= frame_index < frame_count:
                visible_at_frame[frame_index].append(obj)
            else:
                out_of_range_od_frame_indices.append(frame_index)

    frames = []
    missing_geometry_count = 0
    for frame_index, ego in enumerate(trajectory):
        object_states = []
        for obj in visible_at_frame[frame_index]:
            state = od.make_object_state(obj, frame_index, ego, samples)
            if state is None:
                missing_geometry_count += 1
            else:
                object_states.append(state)
        object_states.sort(
            key=lambda state: (
                state["position_ego_m"]["distance"],
                state["class"],
                state["object_id"],
            )
        )
        interaction_candidates = []
        for state in object_states:
            if state["class"] not in od.MOTIONAL_CLASSES:
                continue
            current_metrics = od.constant_velocity_interaction(state)
            future_metrics = od.observed_future_path_overlap(
                state,
                frame_index,
                trajectory,
                samples[state["object_id"]],
                timestamps,
            )
            distance = state["position_ego_m"]["distance"]
            if distance <= 100.0 or future_metrics["observed_future_path_overlap"]:
                interaction_candidates.append(
                    {
                        "object_id": state["object_id"],
                        "class": state["class"],
                        **current_metrics,
                        **future_metrics,
                    }
                )

        frames.append(
            {
                "frame_index": frame_index,
                "timestamp_unix_s": round(ego["timestamp"], 6),
                "time_since_start_s": round(ego["timestamp"] - timestamps[0], 4),
                "ego": {
                    "position_lcs_m": [od.round_or_none(value) for value in ego["position"]],
                    "orientation_lcs_quaternion_xyzw": [
                        od.round_or_none(value) for value in ego["quaternion"]
                    ],
                    "heading_lcs_rad": od.round_or_none(ego["yaw"]),
                    "velocity_lcs_mps": [
                        od.round_or_none(value) for value in ego["velocity"]
                    ],
                    "speed_mps": od.round_or_none(ego["speed"]),
                    "acceleration_mps2": od.round_or_none(ego["acceleration"]),
                    "yaw_rate_radps": od.round_or_none(ego["yaw_rate"]),
                },
                "objects": object_states,
                "scenario_signals": od.scenario_signals(ego, object_states),
                "interaction_candidates": interaction_candidates,
                "ld": build_frame_ld_context(
                    ego, ld_indexes, ld_radius_m, include_clipped_geometry
                ),
            }
        )

    deltas = [right - left for left, right in zip(timestamps, timestamps[1:])]
    result = {
        "schema_version": SCHEMA_VERSION,
        "recording_id": recording,
        "source": {
            "od_annotations": portable_path(od_path),
            "ld_annotations": portable_path(ld_path),
            "trajectory": portable_path(trajectory_path),
            "alignment": {
                "od_to_trajectory": "OD frameIndex maps directly to trajectory row index",
                "ld_temporal_model": "recording_static_map_spatially_queried_at_each_ego_pose",
                "scene_id_match": True,
                "scene_name_match": True,
            },
            "coordinate_system": {
                "od": "LCS",
                "trajectory": "LCS",
                "ld": "inferred_shared_lcs",
                "ld_explicitly_declared": False,
            },
        },
        "recording": {
            "frame_count": frame_count,
            "start_timestamp_unix_s": round(timestamps[0], 6),
            "end_timestamp_unix_s": round(timestamps[-1], 6),
            "duration_s": round(timestamps[-1] - timestamps[0], 4),
            "median_frame_interval_s": round(median(deltas), 6),
            "nominal_frame_rate_hz": round(1.0 / median(deltas), 4),
        },
        "scenario_taxonomy": od.SCENARIO_TAXONOMY,
        "ld_configuration": {
            "nearby_query_radius_m": od.round_or_none(ld_radius_m),
            "include_clipped_geometry": include_clipped_geometry,
            "full_geometry_storage": "ld_feature_store_once_per_recording",
            "frame_storage": "nearby_ids_and_ego_relative_summaries",
        },
        "ld_feature_store": ld_feature_store,
        "data_quality": {
            "trajectory_rows_match_od_frames": True,
            "trajectory_rows_match_ld_scene_frames": True,
            "canonical_frame_count_matches_all_source_frames": len(frames) == frame_count,
            "canonical_frame_indices_are_original": all(
                frame["frame_index"] == index for index, frame in enumerate(frames)
            ),
            "out_of_range_od_frame_indices": sorted(set(out_of_range_od_frame_indices)),
            "object_states_without_usable_geometry": missing_geometry_count,
            "ld": ld_feature_store["quality"],
            "notes": [
                "No source trajectory frame is dropped.",
                "No object state is forward-filled.",
                "Dynamic geometry uses exact per-frame bbox3d only.",
                "Static object-level bbox3d is used only on listed visible frames.",
                "Lead detection remains an OD-only geometric candidate.",
                "Object derivatives are omitted across observation gaps over 0.25 s.",
                "LD is a recording-level static map, not a timestamped sensor stream.",
                "Complete LD geometry is stored once; frames contain compact spatial references.",
                "Valid numerical zero values are retained as zero.",
            ],
        },
        "frames": frames,
    }

    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / f"{recording}_canonical_odld_frames.json"
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=True, separators=(",", ":"))
    return output_path, result


def recording_names(source_root: Path, requested: list[str]) -> list[str]:
    if requested:
        return requested
    return sorted(
        path.name
        for path in source_root.iterdir()
        if path.is_dir()
        and not path.name.startswith("._")
        and (path / "annotations_OD.json").is_file()
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--ld-radius-m", type=float, default=100.0)
    parser.add_argument("--include-clipped-ld-geometry", action="store_true")
    parser.add_argument("recordings", nargs="*")
    args = parser.parse_args()
    if not od.finite_number(args.ld_radius_m) or args.ld_radius_m <= 0:
        parser.error("--ld-radius-m must be a positive finite number")

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "scenario_taxonomy": od.SCENARIO_TAXONOMY,
        "ld_configuration": {
            "nearby_query_radius_m": args.ld_radius_m,
            "include_clipped_geometry": args.include_clipped_ld_geometry,
        },
        "recordings": [],
    }
    for recording in recording_names(args.source_root, args.recordings):
        output_path, result = build_recording(
            args.source_root,
            args.output_root,
            recording,
            args.ld_radius_m,
            args.include_clipped_ld_geometry,
        )
        manifest["recordings"].append(
            {
                "recording_id": recording,
                "path": output_path.name,
                **result["recording"],
                "ld_quality": result["data_quality"]["ld"],
            }
        )
        print(f"Wrote {output_path}")

    manifest_path = args.output_root / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=True, indent=2)
    print(f"Wrote {manifest_path}")


if __name__ == "__main__":
    main()
