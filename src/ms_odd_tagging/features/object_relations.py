"""Recording-level ego-to-object normalization, tracking, and proximity relations."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from statistics import median
from typing import Any


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _point_segment_distance(point, start, end) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    denominator = dx * dx + dy * dy
    if denominator <= 1e-12:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    ratio = max(
        0.0,
        min(
            1.0,
            ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy)
            / denominator,
        ),
    )
    projection = (start[0] + ratio * dx, start[1] + ratio * dy)
    return math.hypot(point[0] - projection[0], point[1] - projection[1])


def _point_in_polygon(point, polygon) -> bool:
    inside = False
    previous = polygon[-1]
    for current in polygon:
        if ((current[1] > point[1]) != (previous[1] > point[1])) and (
            point[0]
            < (previous[0] - current[0])
            * (point[1] - current[1])
            / (previous[1] - current[1])
            + current[0]
        ):
            inside = not inside
        previous = current
    return inside


def _orientation(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (
        b[1] - a[1]
    ) * (c[0] - a[0])


def _segments_intersect(a, b, c, d) -> bool:
    values = (
        _orientation(a, b, c),
        _orientation(a, b, d),
        _orientation(c, d, a),
        _orientation(c, d, b),
    )
    if values[0] * values[1] < 0 and values[2] * values[3] < 0:
        return True
    epsilon = 1e-9
    checks = (
        (values[0], c, a, b),
        (values[1], d, a, b),
        (values[2], a, c, d),
        (values[3], b, c, d),
    )
    return any(
        abs(value) <= epsilon
        and _point_segment_distance(point, start, end) <= epsilon
        for value, point, start, end in checks
    )


def _polygon_distance(first, second) -> float:
    first_edges = list(zip(first, first[1:] + first[:1]))
    second_edges = list(zip(second, second[1:] + second[:1]))
    if (
        any(_point_in_polygon(point, second) for point in first)
        or any(_point_in_polygon(point, first) for point in second)
        or any(
            _segments_intersect(a, b, c, d)
            for a, b in first_edges
            for c, d in second_edges
        )
    ):
        return 0.0
    return min(
        [
            _point_segment_distance(point, start, end)
            for point in first
            for start, end in second_edges
        ]
        + [
            _point_segment_distance(point, start, end)
            for point in second
            for start, end in first_edges
        ]
    )


def _rectangle(
    center: tuple[float, float],
    heading: float,
    length: float,
    width: float,
) -> tuple[tuple[float, float], ...]:
    cosine, sine = math.cos(heading), math.sin(heading)
    result = []
    for longitudinal, lateral in (
        (length / 2.0, width / 2.0),
        (length / 2.0, -width / 2.0),
        (-length / 2.0, -width / 2.0),
        (-length / 2.0, width / 2.0),
    ):
        result.append(
            (
                center[0] + cosine * longitudinal - sine * lateral,
                center[1] + sine * longitudinal + cosine * lateral,
            )
        )
    return tuple(result)


def _category(class_name: str, settings: dict[str, Any]) -> str | None:
    normalized = class_name.lower()
    for category in ("pedestrian", "bicycle", "motorcycle", "vehicle"):
        if normalized in {
            str(value).lower()
            for value in settings["class_mappings"][category]
        }:
            return category
    return None


def _dimensions_valid(dimensions: Any) -> bool:
    return (
        isinstance(dimensions, dict)
        and _finite(dimensions.get("length"))
        and _finite(dimensions.get("width"))
        and float(dimensions["length"]) > 0
        and float(dimensions["width"]) > 0
    )


def _dimension_difference(first: dict[str, float], second: dict[str, float]) -> float:
    return max(
        abs(first[key] - second[key]) / max(first[key], second[key], 1e-6)
        for key in ("length", "width")
    )


def _long_vehicle(
    class_name: str,
    dimensions: dict[str, float],
    settings: dict[str, Any],
) -> tuple[bool, str | None]:
    length = dimensions["length"]
    explicit = class_name.lower() in {
        str(value).lower() for value in settings["long_vehicle_classes"]
    }
    if explicit and length >= settings["long_vehicle_class_minimum_length_m"]:
        return True, "explicit_class_and_minimum_length"
    if length >= settings["long_vehicle_dimension_threshold_m"]:
        return True, "bbox_length_threshold"
    return False, None


def _intervals(
    active: list[bool],
    timestamps: list[float],
    *,
    minimum_duration_s: float,
    maximum_missing_gap_s: float,
    merge_gap_s: float,
) -> list[tuple[int, int]]:
    raw: list[tuple[int, int]] = []
    start = last_active = None
    for index, is_active in enumerate(active):
        if is_active:
            if start is None:
                start = index
            last_active = index
        elif (
            start is not None
            and last_active is not None
            and timestamps[index] - timestamps[last_active]
            > maximum_missing_gap_s + 1e-9
        ):
            if timestamps[last_active] - timestamps[start] + 1e-9 >= minimum_duration_s:
                raw.append((start, last_active))
            start = last_active = None
    if start is not None and last_active is not None:
        if timestamps[last_active] - timestamps[start] + 1e-9 >= minimum_duration_s:
            raw.append((start, last_active))
    merged: list[tuple[int, int]] = []
    for interval in raw:
        if (
            merged
            and timestamps[interval[0]] - timestamps[merged[-1][1]]
            <= merge_gap_s + 1e-9
        ):
            merged[-1] = (merged[-1][0], interval[1])
        else:
            merged.append(interval)
    return merged


def build_object_relations(
    recording: dict[str, Any], settings: dict[str, Any]
) -> dict[str, Any]:
    """Normalize OD observations and retain original recording frame identity."""
    frames = recording.get("frames", [])
    timestamps = [
        float(frame["time_since_start_s"])
        if _finite(frame.get("time_since_start_s"))
        else math.nan
        for frame in frames
    ]
    positive_steps = [
        current - previous
        for previous, current in zip(timestamps, timestamps[1:])
        if math.isfinite(previous)
        and math.isfinite(current)
        and current > previous
    ]
    nominal_step = median(positive_steps) if positive_steps else 0.0
    tracks: dict[str, dict[str, Any]] = {}
    source_to_track: dict[str, str] = {}
    frame_payloads = []

    for frame_position, frame in enumerate(frames):
        timestamp = timestamps[frame_position]
        ego = frame.get("ego") or {}
        ego_position = ego.get("position_lcs_m") or []
        ego_heading = ego.get("heading_lcs_rad")
        valid_ego = (
            len(ego_position) >= 2
            and _finite(ego_position[0])
            and _finite(ego_position[1])
            and _finite(ego_heading)
            and math.isfinite(timestamp)
        )
        ego_center = (
            (float(ego_position[0]), float(ego_position[1]))
            if valid_ego
            else None
        )
        ego_polygon = (
            _rectangle(
                ego_center,
                float(ego_heading),
                settings["ego_footprint_length_m"],
                settings["ego_footprint_width_m"],
            )
            if valid_ego and ego_center is not None
            else None
        )
        candidates = []
        for raw in frame.get("objects", []):
            class_name = str(raw.get("class") or "")
            category = _category(class_name, settings)
            position = raw.get("position_lcs_m") or []
            dimensions_value = raw.get("dimensions_m")
            if (
                category is None
                or len(position) < 2
                or not _finite(position[0])
                or not _finite(position[1])
                or not _dimensions_valid(dimensions_value)
            ):
                continue
            confidence = raw.get("confidence")
            if (
                _finite(confidence)
                and float(confidence) < settings["minimum_object_confidence"]
            ):
                continue
            dimensions = {
                "length": float(dimensions_value["length"]),
                "width": float(dimensions_value["width"]),
                "height": (
                    float(dimensions_value["height"])
                    if _finite(dimensions_value.get("height"))
                    else None
                ),
            }
            source_id_value = raw.get("object_id")
            source_id = (
                str(source_id_value)
                if source_id_value not in (None, "")
                else None
            )
            heading_relative = raw.get("heading_relative_rad")
            heading_available = valid_ego and _finite(heading_relative)
            object_heading = (
                float(ego_heading) + float(heading_relative)
                if heading_available
                else float(ego_heading)
                if valid_ego
                else None
            )
            candidates.append(
                {
                    "source_object_id": source_id,
                    "class_name": class_name,
                    "subclass": raw.get("subclass"),
                    "normalized_category": category,
                    "annotation_type": raw.get("annotation_type"),
                    "position_lcs_m": [float(position[0]), float(position[1])],
                    "dimensions_m": dimensions,
                    "heading_lcs_rad": object_heading,
                    "heading_available": heading_available,
                    "heading_source": (
                        "od_bbox_orientation"
                        if heading_available
                        else "ego_heading_fallback"
                        if valid_ego
                        else "unavailable"
                    ),
                    "confidence": float(confidence) if _finite(confidence) else None,
                    "confidence_available": _finite(confidence),
                    "canonical_velocity_lcs_mps": raw.get("velocity_lcs_mps"),
                    "canonical_velocity_source": raw.get("velocity_source"),
                    "raw_position_ego_m": raw.get("position_ego_m") or {},
                }
            )

        # Same-frame near-identical boxes are aliases, not distinct participants.
        deduplicated = []
        duplicate_aliases: dict[int, list[str]] = defaultdict(list)
        for candidate in candidates:
            duplicate_index = None
            for index, existing in enumerate(deduplicated):
                center_distance = math.hypot(
                    candidate["position_lcs_m"][0] - existing["position_lcs_m"][0],
                    candidate["position_lcs_m"][1] - existing["position_lcs_m"][1],
                )
                if (
                    candidate["normalized_category"]
                    == existing["normalized_category"]
                    and center_distance
                    <= settings["duplicate_observation_distance_m"]
                    and _dimension_difference(
                        candidate["dimensions_m"], existing["dimensions_m"]
                    )
                    <= settings["maximum_dimension_ratio_difference"]
                ):
                    duplicate_index = index
                    break
            if duplicate_index is None:
                deduplicated.append(candidate)
            elif candidate["source_object_id"] is not None:
                duplicate_aliases[duplicate_index].append(
                    candidate["source_object_id"]
                )

        frame_relations = []
        current_tracks: set[str] = set()
        for candidate_index, candidate in enumerate(deduplicated):
            source_id = candidate["source_object_id"]
            track_id = source_to_track.get(source_id) if source_id else None
            # A tentative ID-switch association is disproven if both source IDs
            # later coexist. Split the returning source so one normalized track
            # cannot produce two observations in the same frame.
            if track_id in current_tracks:
                source_to_track.pop(source_id, None)
                track_id = None
            id_switch_associated = False
            if track_id is None:
                association_candidates = []
                for existing_id, track in tracks.items():
                    if existing_id in current_tracks or track["last_frame_position"] >= frame_position:
                        continue
                    dt = timestamp - track["last_timestamp_s"]
                    if (
                        not math.isfinite(dt)
                        or dt <= 0
                        or dt > settings["maximum_missing_frame_gap_s"] + nominal_step
                        or track["normalized_category"]
                        != candidate["normalized_category"]
                        or _dimension_difference(
                            track["representative_dimensions_m"],
                            candidate["dimensions_m"],
                        )
                        > settings["maximum_dimension_ratio_difference"]
                    ):
                        continue
                    displacement = math.hypot(
                        candidate["position_lcs_m"][0]
                        - track["last_position_lcs_m"][0],
                        candidate["position_lcs_m"][1]
                        - track["last_position_lcs_m"][1],
                    )
                    if (
                        displacement
                        <= settings["maximum_tracking_association_distance_m"]
                        and displacement / dt
                        <= settings["maximum_physically_plausible_object_speed_mps"]
                    ):
                        association_candidates.append((displacement, existing_id))
                association_candidates.sort()
                if (
                    len(association_candidates) == 1
                    and tracks[association_candidates[0][1]][
                        "last_frame_position"
                    ]
                    in {frame_position - 1, frame_position - 2}
                ):
                    track_id = association_candidates[0][1]
                    id_switch_associated = source_id is not None
                else:
                    base_id = source_id or f"anonymous-{frame['frame_index']}"
                    track_id = f"object:{base_id}"
                    suffix = 2
                    while track_id in tracks:
                        track_id = f"object:{base_id}:{suffix}"
                        suffix += 1
                    tracks[track_id] = {
                        "track_id": track_id,
                        "source_object_ids": [],
                        "class_names": [],
                        "normalized_category": candidate["normalized_category"],
                        "normalized_categories": [
                            candidate["normalized_category"]
                        ],
                        "long_vehicle": False,
                        "long_vehicle_reasons": [],
                        "first_frame": frame["frame_index"],
                        "last_frame": frame["frame_index"],
                        "first_timestamp_s": timestamp,
                        "last_timestamp_s": timestamp,
                        "last_frame_position": frame_position,
                        "last_position_lcs_m": candidate["position_lcs_m"],
                        "representative_dimensions_m": candidate["dimensions_m"],
                        "observation_count": 0,
                        "id_switch_count": 0,
                        "duplicate_alias_ids": [],
                        "rejected_velocity_count": 0,
                    }
                if source_id:
                    source_to_track[source_id] = track_id
            track = tracks[track_id]
            if source_id and source_id not in track["source_object_ids"]:
                track["source_object_ids"].append(source_id)
            if candidate["class_name"] not in track["class_names"]:
                track["class_names"].append(candidate["class_name"])
            aliases = duplicate_aliases.get(candidate_index, [])
            for alias in aliases:
                if alias not in track["duplicate_alias_ids"]:
                    track["duplicate_alias_ids"].append(alias)
                source_to_track[alias] = track_id
            if id_switch_associated:
                track["id_switch_count"] += 1

            object_speed = None
            object_velocity = None
            velocity_source = "unavailable"
            velocity = candidate["canonical_velocity_lcs_mps"]
            if (
                isinstance(velocity, (list, tuple))
                and len(velocity) >= 2
                and _finite(velocity[0])
                and _finite(velocity[1])
            ):
                speed = math.hypot(float(velocity[0]), float(velocity[1]))
                if speed <= settings["maximum_physically_plausible_object_speed_mps"]:
                    object_speed = speed
                    object_velocity = [float(velocity[0]), float(velocity[1])]
                    velocity_source = (
                        "measured"
                        if candidate["canonical_velocity_source"] == "measured"
                        else "derived_global"
                    )
                else:
                    track["rejected_velocity_count"] += 1
            elif (
                track["observation_count"] > 0
                and not id_switch_associated
                and math.isfinite(timestamp)
            ):
                dt = timestamp - track["last_timestamp_s"]
                displacement = math.hypot(
                    candidate["position_lcs_m"][0]
                    - track["last_position_lcs_m"][0],
                    candidate["position_lcs_m"][1]
                    - track["last_position_lcs_m"][1],
                )
                if (
                    0 < dt <= settings["maximum_velocity_sample_gap_s"]
                    and displacement / dt
                    <= settings["maximum_physically_plausible_object_speed_mps"]
                ):
                    object_speed = displacement / dt
                    object_velocity = [
                        (
                            candidate["position_lcs_m"][0]
                            - track["last_position_lcs_m"][0]
                        )
                        / dt,
                        (
                            candidate["position_lcs_m"][1]
                            - track["last_position_lcs_m"][1]
                        )
                        / dt,
                    ]
                    velocity_source = "derived_global"
                elif dt > 0:
                    track["rejected_velocity_count"] += 1

            valid_relation = (
                valid_ego
                and ego_polygon is not None
                and candidate["heading_lcs_rad"] is not None
            )
            if valid_relation and ego_center is not None and ego_polygon is not None:
                object_polygon = _rectangle(
                    tuple(candidate["position_lcs_m"]),
                    candidate["heading_lcs_rad"],
                    candidate["dimensions_m"]["length"],
                    candidate["dimensions_m"]["width"],
                )
                nearest_distance = _polygon_distance(ego_polygon, object_polygon)
                dx = candidate["position_lcs_m"][0] - ego_center[0]
                dy = candidate["position_lcs_m"][1] - ego_center[1]
                cosine, sine = math.cos(float(ego_heading)), math.sin(float(ego_heading))
                longitudinal = cosine * dx + sine * dy
                lateral = -sine * dx + cosine * dy
                center_distance = math.hypot(dx, dy)
                bearing = math.degrees(math.atan2(lateral, longitudinal))
                inside_region = (
                    nearest_distance <= settings["generic_proximity_radius_m"]
                    and -settings["backward_region_limit_m"]
                    <= longitudinal
                    <= settings["forward_region_limit_m"]
                    and abs(lateral) <= settings["lateral_region_limit_m"]
                )
            else:
                object_polygon = ()
                nearest_distance = longitudinal = lateral = center_distance = bearing = None
                inside_region = False

            age_s = max(0.0, timestamp - track["first_timestamp_s"])
            long_vehicle, long_reason = _long_vehicle(
                candidate["class_name"],
                candidate["dimensions_m"],
                settings,
            )
            normalized_categories = [candidate["normalized_category"]]
            if long_vehicle:
                normalized_categories.append("long_vehicle")
                track["long_vehicle"] = True
                if long_reason not in track["long_vehicle_reasons"]:
                    track["long_vehicle_reasons"].append(long_reason)
                if "long_vehicle" not in track["normalized_categories"]:
                    track["normalized_categories"].append("long_vehicle")
            relation = {
                "track_id": track_id,
                "source_object_id": source_id,
                "source_object_ids": sorted(track["source_object_ids"]),
                "duplicate_alias_ids": sorted(track["duplicate_alias_ids"]),
                "class_name": candidate["class_name"],
                "subclass": candidate["subclass"],
                "normalized_category": candidate["normalized_category"],
                # Multi-label taxonomy keeps long vehicles inside the vehicle
                # population while also exposing the requested specialization.
                "normalized_categories": normalized_categories,
                "annotation_type": candidate["annotation_type"],
                "frame_index": frame["frame_index"],
                "timestamp_s": timestamp,
                "center_lcs_m": candidate["position_lcs_m"],
                "dimensions_m": candidate["dimensions_m"],
                "heading_lcs_rad": candidate["heading_lcs_rad"],
                "heading_available": candidate["heading_available"],
                "heading_source": candidate["heading_source"],
                "confidence": candidate["confidence"],
                "confidence_available": candidate["confidence_available"],
                "coordinate_frame": "recording_lcs_m",
                "coordinate_frame_valid": valid_relation,
                "center_distance_m": (
                    round(center_distance, 3) if center_distance is not None else None
                ),
                "nearest_footprint_distance_m": (
                    round(nearest_distance, 3)
                    if nearest_distance is not None
                    else None
                ),
                "signed_longitudinal_m": (
                    round(longitudinal, 3) if longitudinal is not None else None
                ),
                "signed_lateral_m": (
                    round(lateral, 3) if lateral is not None else None
                ),
                "relative_bearing_deg": (
                    round(bearing, 2) if bearing is not None else None
                ),
                "inside_proximity_region": inside_region,
                "valid_spatial_relation": valid_relation,
                "object_speed_mps": (
                    round(object_speed, 4) if object_speed is not None else None
                ),
                "object_velocity_lcs_mps": (
                    [round(component, 4) for component in object_velocity]
                    if object_velocity is not None
                    else None
                ),
                "velocity_source": velocity_source,
                "track_age_s": round(age_s, 4),
                "long_vehicle": long_vehicle,
                "long_vehicle_reason": long_reason,
                "object_footprint_lcs_m": [
                    [round(point[0], 4), round(point[1], 4)]
                    for point in object_polygon
                ],
                "id_switch_associated": id_switch_associated,
            }
            frame_relations.append(relation)
            current_tracks.add(track_id)
            track["last_frame"] = frame["frame_index"]
            track["last_timestamp_s"] = timestamp
            track["last_frame_position"] = frame_position
            track["last_position_lcs_m"] = candidate["position_lcs_m"]
            track["observation_count"] += 1
        frame_payloads.append(
            {
                "frame_index": frame["frame_index"],
                "time_since_start_s": frame.get("time_since_start_s"),
                "objects": sorted(
                    frame_relations, key=lambda item: item["track_id"]
                ),
            }
        )

    velocity_filter = settings["velocity_filter"]
    if velocity_filter.get("enabled"):
        window = int(velocity_filter["window_samples"])
        prior_values: dict[str, list[float]] = defaultdict(list)
        for frame in frame_payloads:
            for relation in frame["objects"]:
                speed = relation.get("object_speed_mps")
                if (
                    speed is None
                    or relation.get("velocity_source")
                    not in {"derived_global", "derived_relative_compensated"}
                ):
                    continue
                history = prior_values[relation["track_id"]]
                history.append(float(speed))
                relation["object_speed_mps"] = round(
                    median(history[-window:]), 4
                )
                relation["velocity_filter"] = {
                    "method": "causal_median",
                    "window_samples": window,
                }

    serialized_tracks = []
    for track in tracks.values():
        serialized_tracks.append(
            {
                key: value
                for key, value in track.items()
                if key
                not in {
                    "last_frame_position",
                    "last_position_lcs_m",
                    "last_timestamp_s",
                }
            }
        )
    serialized_tracks.sort(key=lambda item: item["track_id"])
    return {
        "schema_version": "ego-object-relations-v1",
        "recording_id": recording.get("recording_id"),
        "coordinate_system": "recording_lcs_m",
        "ego_footprint": {
            "length_m": settings["ego_footprint_length_m"],
            "width_m": settings["ego_footprint_width_m"],
        },
        "proximity_region": {
            "nearest_footprint_radius_m": settings["generic_proximity_radius_m"],
            "forward_limit_m": settings["forward_region_limit_m"],
            "backward_limit_m": settings["backward_region_limit_m"],
            "lateral_limit_m": settings["lateral_region_limit_m"],
            "surrounding_not_front_only": True,
        },
        "tracks": serialized_tracks,
        "frames": frame_payloads,
    }


def summarize_object_relations(payload: dict[str, Any]) -> dict[str, Any]:
    counts = Counter(
        track["normalized_category"] for track in payload.get("tracks", [])
    )
    return {
        "track_counts_by_category": dict(sorted(counts.items())),
        "track_count": len(payload.get("tracks", [])),
        "id_switch_associations": sum(
            track.get("id_switch_count", 0) for track in payload.get("tracks", [])
        ),
        "duplicate_alias_count": sum(
            len(track.get("duplicate_alias_ids", []))
            for track in payload.get("tracks", [])
        ),
        "long_vehicle_track_count": sum(
            bool(track.get("long_vehicle"))
            for track in payload.get("tracks", [])
        ),
        "rejected_velocity_count": sum(
            track.get("rejected_velocity_count", 0)
            for track in payload.get("tracks", [])
        ),
    }


__all__ = [
    "build_object_relations",
    "summarize_object_relations",
    "_intervals",
]
