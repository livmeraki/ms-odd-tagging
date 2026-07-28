"""Recording-level ego relations to static crosswalk and stopline geometry.

The canonical ODLD format stores roadmarks once in the recording LCS and
references nearby IDs from each original frame.  This module turns that static
geometry plus the ego pose into reusable, timestamp-aligned spatial states.
It intentionally contains no taxonomy-event logic.
"""

from __future__ import annotations

import math
from typing import Any


CROSSWALK_STATES = {
    "far",
    "approaching",
    "before",
    "on",
    "leaving",
    "passed",
    "unknown",
}
STOPLINE_STATES = {
    "far",
    "approaching",
    "before",
    "overlapping",
    "passed",
    "unknown",
}


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _wrap(value: float) -> float:
    return math.atan2(math.sin(value), math.cos(value))


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _point_segment_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    denominator = dx * dx + dy * dy
    if denominator <= 1e-12:
        return _distance(point, start)
    ratio = max(
        0.0,
        min(
            1.0,
            (
                (point[0] - start[0]) * dx
                + (point[1] - start[1]) * dy
            )
            / denominator,
        ),
    )
    projection = (start[0] + ratio * dx, start[1] + ratio * dy)
    return _distance(point, projection)


def _orientation_difference_deg(first: float, second: float) -> float:
    """Undirected line-orientation difference in [0, 90] degrees."""
    difference = abs(math.degrees(_wrap(first - second)))
    difference = min(difference, 180.0 - difference)
    return abs(difference)


def _point_in_polygon(
    point: tuple[float, float], polygon: tuple[tuple[float, float], ...]
) -> bool:
    if len(polygon) < 3:
        return False
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        if ((current[1] > y) != (previous[1] > y)) and (
            x
            < (previous[0] - current[0])
            * (y - current[1])
            / (previous[1] - current[1])
            + current[0]
        ):
            inside = not inside
        previous = current
    return inside


def _segments_intersect(a, b, c, d) -> bool:
    def orientation(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (
            q[1] - p[1]
        ) * (r[0] - p[0])

    values = (
        orientation(a, b, c),
        orientation(a, b, d),
        orientation(c, d, a),
        orientation(c, d, b),
    )
    if values[0] * values[1] < 0 and values[2] * values[3] < 0:
        return True
    epsilon = 1e-9
    for value, point, start, end in (
        (values[0], c, a, b),
        (values[1], d, a, b),
        (values[2], a, c, d),
        (values[3], b, c, d),
    ):
        if abs(value) <= epsilon and _point_segment_distance(point, start, end) <= epsilon:
            return True
    return False


def _polygon_overlap(
    first: tuple[tuple[float, float], ...],
    second: tuple[tuple[float, float], ...],
) -> bool:
    if len(first) < 3 or len(second) < 3:
        return False
    if any(_point_in_polygon(point, second) for point in first):
        return True
    if any(_point_in_polygon(point, first) for point in second):
        return True
    first_edges = zip(first, first[1:] + first[:1])
    second_edges = list(zip(second, second[1:] + second[:1]))
    return any(
        _segments_intersect(a, b, c, d)
        for a, b in first_edges
        for c, d in second_edges
    )


def _polygon_distance(
    first: tuple[tuple[float, float], ...],
    second: tuple[tuple[float, float], ...],
) -> float:
    if _polygon_overlap(first, second):
        return 0.0
    first_edges = list(zip(first, first[1:] + first[:1]))
    second_edges = list(zip(second, second[1:] + second[:1]))
    distances = [
        _point_segment_distance(point, start, end)
        for point in first
        for start, end in second_edges
    ] + [
        _point_segment_distance(point, start, end)
        for point in second
        for start, end in first_edges
    ]
    return min(distances, default=math.inf)


def _bbox(polygon: tuple[tuple[float, float], ...]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def _bbox_iou(
    first: tuple[tuple[float, float], ...],
    second: tuple[tuple[float, float], ...],
) -> float:
    a, b = _bbox(first), _bbox(second)
    width = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    height = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    intersection = width * height
    first_area = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    second_area = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = first_area + second_area - intersection
    return intersection / union if union > 1e-9 else 0.0


def _center(polygon: tuple[tuple[float, float], ...]) -> tuple[float, float]:
    return (
        sum(point[0] for point in polygon) / len(polygon),
        sum(point[1] for point in polygon) / len(polygon),
    )


def _principal_orientation(
    polygon: tuple[tuple[float, float], ...]
) -> float | None:
    if len(polygon) < 2:
        return None
    center = _center(polygon)
    xx = sum((point[0] - center[0]) ** 2 for point in polygon)
    yy = sum((point[1] - center[1]) ** 2 for point in polygon)
    xy = sum(
        (point[0] - center[0]) * (point[1] - center[1])
        for point in polygon
    )
    if xx + yy <= 1e-12:
        return None
    return 0.5 * math.atan2(2.0 * xy, xx - yy)


def _ego_footprint(
    position: tuple[float, float],
    heading: float,
    length_m: float,
    width_m: float,
) -> tuple[tuple[float, float], ...]:
    half_length, half_width = length_m / 2.0, width_m / 2.0
    cosine, sine = math.cos(heading), math.sin(heading)
    result = []
    for longitudinal, lateral in (
        (half_length, half_width),
        (half_length, -half_width),
        (-half_length, -half_width),
        (-half_length, half_width),
    ):
        result.append(
            (
                position[0] + cosine * longitudinal - sine * lateral,
                position[1] + sine * longitudinal + cosine * lateral,
            )
        )
    return tuple(result)


def _ego_coordinates(
    point: tuple[float, float],
    position: tuple[float, float],
    heading: float,
) -> tuple[float, float]:
    dx, dy = point[0] - position[0], point[1] - position[1]
    cosine, sine = math.cos(heading), math.sin(heading)
    return cosine * dx + sine * dy, -sine * dx + cosine * dy


def _extract_tracks(
    recording: dict[str, Any], settings: dict[str, Any]
) -> list[dict[str, Any]]:
    store = recording.get("ld_feature_store") or {}
    crosswalk_classes = {
        str(value).lower() for value in settings["crosswalk_classes"]
    }
    stopline_classes = {
        str(value).lower() for value in settings["stopline_classes"]
    }
    raw_tracks = []
    for feature in store.get("roadmarks", []):
        class_name = str(feature.get("class", "")).lower()
        feature_type = (
            "crosswalk"
            if class_name in crosswalk_classes
            else "stopline"
            if class_name in stopline_classes
            else None
        )
        if feature_type is None or feature.get("ignored") is True:
            continue
        polygon = tuple(
            (float(position[0]), float(position[1]))
            for point in feature.get("points", [])
            if isinstance((position := point.get("position_lcs_m")), (list, tuple))
            and len(position) >= 2
            and _finite(position[0])
            and _finite(position[1])
        )
        if len(polygon) < 3:
            continue
        confidence = feature.get("confidence")
        if not _finite(confidence):
            confidence = (feature.get("attributes") or {}).get("confidence")
        if (
            _finite(confidence)
            and float(confidence) < settings["minimum_feature_confidence"]
        ):
            continue
        source_id = str(feature.get("roadmark_id"))
        raw_tracks.append(
            {
                "track_id": f"{feature_type}:{source_id}",
                "feature_type": feature_type,
                "source_feature_ids": [source_id],
                "class": feature.get("class"),
                "subclass": feature.get("subclass"),
                "shape_type": feature.get("shape_type"),
                "polygon_lcs_m": polygon,
                "center_lcs_m": _center(polygon),
                "orientation_lcs_rad": _principal_orientation(polygon),
                "confidence": float(confidence) if _finite(confidence) else None,
                "confidence_available": _finite(confidence),
                "geometry_source": "recording_static_roadmark_polygon",
            }
        )

    tracks: list[dict[str, Any]] = []
    for candidate in sorted(raw_tracks, key=lambda item: item["track_id"]):
        duplicate = None
        for existing in tracks:
            if existing["feature_type"] != candidate["feature_type"]:
                continue
            orientations_valid = (
                existing["orientation_lcs_rad"] is not None
                and candidate["orientation_lcs_rad"] is not None
            )
            orientation_difference = (
                _orientation_difference_deg(
                    existing["orientation_lcs_rad"],
                    candidate["orientation_lcs_rad"],
                )
                if orientations_valid
                else math.inf
            )
            if (
                _distance(existing["center_lcs_m"], candidate["center_lcs_m"])
                <= settings["duplicate_feature_center_distance_m"]
                and orientation_difference
                <= settings["maximum_orientation_difference_deg"]
                and _bbox_iou(
                    existing["polygon_lcs_m"], candidate["polygon_lcs_m"]
                )
                >= settings["duplicate_feature_minimum_bbox_iou"]
            ):
                duplicate = existing
                break
        if duplicate is None:
            tracks.append(candidate)
        else:
            duplicate["source_feature_ids"].extend(
                candidate["source_feature_ids"]
            )
            duplicate["source_feature_ids"].sort()
    return tracks


def _associate_stoplines(
    tracks: list[dict[str, Any]], settings: dict[str, Any]
) -> list[dict[str, Any]]:
    crosswalks = [track for track in tracks if track["feature_type"] == "crosswalk"]
    associations = []
    for stopline in (
        track for track in tracks if track["feature_type"] == "stopline"
    ):
        candidates = []
        for crosswalk in crosswalks:
            if (
                stopline["orientation_lcs_rad"] is None
                or crosswalk["orientation_lcs_rad"] is None
            ):
                continue
            orientation_difference = _orientation_difference_deg(
                stopline["orientation_lcs_rad"],
                crosswalk["orientation_lcs_rad"],
            )
            polygon_distance = _polygon_distance(
                stopline["polygon_lcs_m"], crosswalk["polygon_lcs_m"]
            )
            center_distance = _distance(
                stopline["center_lcs_m"], crosswalk["center_lcs_m"]
            )
            if (
                polygon_distance
                <= settings["maximum_feature_association_distance_m"]
                and orientation_difference
                <= settings["maximum_orientation_difference_deg"]
            ):
                candidates.append(
                    {
                        "crosswalk_track_id": crosswalk["track_id"],
                        "geometry_distance_m": polygon_distance,
                        "center_distance_m": center_distance,
                        "orientation_difference_deg": orientation_difference,
                        "score": polygon_distance
                        + 0.1 * center_distance
                        + 0.05 * orientation_difference,
                    }
                )
        candidates.sort(key=lambda item: (item["score"], item["crosswalk_track_id"]))
        best = candidates[0] if candidates else None
        ambiguous = (
            len(candidates) > 1
            and candidates[1]["score"] - candidates[0]["score"]
            < settings["association_ambiguity_margin"]
        )
        associations.append(
            {
                "stopline_track_id": stopline["track_id"],
                "crosswalk_track_id": (
                    best["crosswalk_track_id"] if best is not None else None
                ),
                "valid": best is not None and not ambiguous,
                "status": (
                    "valid"
                    if best is not None and not ambiguous
                    else "ambiguous"
                    if ambiguous
                    else "unassociated"
                ),
                "confidence": (
                    "high"
                    if best is not None
                    and best["geometry_distance_m"] <= 5.0
                    and best["orientation_difference_deg"] <= 15.0
                    and not ambiguous
                    else "medium"
                    if best is not None and not ambiguous
                    else "uncertain"
                ),
                "geometry_distance_m": (
                    round(best["geometry_distance_m"], 3)
                    if best is not None
                    else None
                ),
                "center_distance_m": (
                    round(best["center_distance_m"], 3)
                    if best is not None
                    else None
                ),
                "orientation_difference_deg": (
                    round(best["orientation_difference_deg"], 2)
                    if best is not None
                    else None
                ),
                "candidate_count": len(candidates),
            }
        )
    return associations


def build_road_feature_relations(
    recording: dict[str, Any], settings: dict[str, Any]
) -> dict[str, Any]:
    """Build per-frame relations without changing canonical frame identity."""
    tracks = _extract_tracks(recording, settings)
    associations = _associate_stoplines(tracks, settings)
    observed_bounds = {
        track["track_id"]: {"first": None, "last": None} for track in tracks
    }
    ever_on = {track["track_id"]: False for track in tracks}
    frame_relations = []
    for frame in recording.get("frames", []):
        ego = frame.get("ego") or {}
        position_value = ego.get("position_lcs_m") or []
        heading = ego.get("heading_lcs_rad")
        valid_pose = (
            len(position_value) >= 2
            and _finite(position_value[0])
            and _finite(position_value[1])
            and _finite(heading)
        )
        position = (
            (float(position_value[0]), float(position_value[1]))
            if valid_pose
            else None
        )
        heading_value = float(heading) if valid_pose else None
        nearby_ids = set(
            str(value)
            for value in (
                ((frame.get("ld") or {}).get("nearby_feature_ids") or {}).get(
                    "roadmarks", []
                )
            )
        )
        crosswalk_relations = []
        stopline_relations = []
        for track in tracks:
            observed = any(
                source_id in nearby_ids
                for source_id in track["source_feature_ids"]
            )
            bounds = observed_bounds[track["track_id"]]
            if observed:
                bounds["first"] = (
                    frame["frame_index"]
                    if bounds["first"] is None
                    else bounds["first"]
                )
                bounds["last"] = frame["frame_index"]
            if not valid_pose or position is None or heading_value is None:
                relation = {
                    "track_id": track["track_id"],
                    "feature_type": track["feature_type"],
                    "state": "unknown",
                    "relation_valid": False,
                    "observed_this_frame": observed,
                }
            else:
                ego_polygon = _ego_footprint(
                    position,
                    heading_value,
                    settings["ego_footprint_length_m"],
                    settings["ego_footprint_width_m"],
                )
                expanded_ego_polygon = _ego_footprint(
                    position,
                    heading_value,
                    settings["ego_footprint_length_m"]
                    + (
                        settings["stopline_overlap_width_m"]
                        if track["feature_type"] == "stopline"
                        else 2.0 * settings["crosswalk_entry_tolerance_m"]
                    ),
                    settings["ego_footprint_width_m"]
                    + (
                        settings["stopline_overlap_width_m"]
                        if track["feature_type"] == "stopline"
                        else 2.0 * settings["crosswalk_entry_tolerance_m"]
                    ),
                )
                relative = [
                    _ego_coordinates(point, position, heading_value)
                    for point in track["polygon_lcs_m"]
                ]
                longitudinal = [value[0] for value in relative]
                lateral = [value[1] for value in relative]
                half_length = settings["ego_footprint_length_m"] / 2.0
                if min(longitudinal) > half_length:
                    signed_clearance = min(longitudinal) - half_length
                elif max(longitudinal) < -half_length:
                    signed_clearance = max(longitudinal) + half_length
                else:
                    signed_clearance = 0.0
                center_relative = _ego_coordinates(
                    track["center_lcs_m"], position, heading_value
                )
                axis_difference = (
                    _orientation_difference_deg(
                        track["orientation_lcs_rad"], heading_value
                    )
                    if track["orientation_lcs_rad"] is not None
                    else None
                )
                orientation_compatible = (
                    axis_difference is not None
                    and abs(90.0 - axis_difference)
                    <= settings["crossing_orientation_tolerance_deg"]
                )
                corridor_half_width = (
                    settings["ego_footprint_width_m"] / 2.0
                    + settings["crosswalk_entry_tolerance_m"]
                )
                corridor_compatible = (
                    min(lateral) <= corridor_half_width
                    and max(lateral) >= -corridor_half_width
                )
                path_compatible = orientation_compatible and corridor_compatible
                overlap = _polygon_overlap(
                    expanded_ego_polygon, track["polygon_lcs_m"]
                )
                nearest_distance = _polygon_distance(
                    ego_polygon, track["polygon_lcs_m"]
                )
                if not path_compatible:
                    state = "far"
                elif track["feature_type"] == "crosswalk":
                    if overlap:
                        state = "on"
                        ever_on[track["track_id"]] = True
                    elif (
                        signed_clearance
                        > settings["approaching_distance_m"]
                    ):
                        state = "far"
                    elif signed_clearance > settings["stopping_region_distance_m"]:
                        state = "approaching"
                    elif signed_clearance > settings["crosswalk_entry_tolerance_m"]:
                        state = "before"
                    elif (
                        ever_on[track["track_id"]]
                        and signed_clearance
                        >= -settings["crosswalk_exit_tolerance_m"]
                    ):
                        state = "leaving"
                    elif signed_clearance < -settings["crosswalk_exit_tolerance_m"]:
                        state = "passed"
                    else:
                        state = "before"
                else:
                    if overlap:
                        state = "overlapping"
                    elif signed_clearance > settings["approaching_distance_m"]:
                        state = "far"
                    elif signed_clearance > settings["stopping_region_distance_m"]:
                        state = "approaching"
                    elif signed_clearance > 0:
                        state = "before"
                    else:
                        state = "passed"
                relation = {
                    "track_id": track["track_id"],
                    "feature_type": track["feature_type"],
                    "source_feature_ids": track["source_feature_ids"],
                    "state": state,
                    "signed_longitudinal_distance_m": round(
                        signed_clearance, 3
                    ),
                    "feature_center_longitudinal_m": round(
                        center_relative[0], 3
                    ),
                    "lateral_offset_m": round(center_relative[1], 3),
                    "nearest_geometry_distance_m": round(nearest_distance, 3),
                    "ego_footprint_overlap": overlap,
                    "path_compatible": path_compatible,
                    "orientation_compatible": orientation_compatible,
                    "corridor_compatible": corridor_compatible,
                    "orientation_difference_from_ego_deg": (
                        round(axis_difference, 2)
                        if axis_difference is not None
                        else None
                    ),
                    "feature_confidence": track["confidence"],
                    "feature_confidence_available": track[
                        "confidence_available"
                    ],
                    "relation_valid": True,
                    "observed_this_frame": observed,
                }
            (
                crosswalk_relations
                if track["feature_type"] == "crosswalk"
                else stopline_relations
            ).append(relation)
        frame_relations.append(
            {
                "frame_index": frame["frame_index"],
                "time_since_start_s": frame.get("time_since_start_s"),
                "crosswalk_relations": crosswalk_relations,
                "stopline_relations": stopline_relations,
            }
        )

    serialized_tracks = []
    for track in tracks:
        bounds = observed_bounds[track["track_id"]]
        serialized_tracks.append(
            {
                **track,
                "polygon_lcs_m": [list(point) for point in track["polygon_lcs_m"]],
                "center_lcs_m": list(track["center_lcs_m"]),
                "first_observed_frame": bounds["first"],
                "last_observed_frame": bounds["last"],
            }
        )
    return {
        "schema_version": "road-feature-relations-v1",
        "recording_id": recording.get("recording_id"),
        "coordinate_system": "recording_lcs_m",
        "ego_footprint": {
            "length_m": settings["ego_footprint_length_m"],
            "width_m": settings["ego_footprint_width_m"],
        },
        "tracks": serialized_tracks,
        "stopline_crosswalk_associations": associations,
        "frames": frame_relations,
    }


def summarize_road_feature_relations(payload: dict[str, Any]) -> dict[str, Any]:
    transitions = []
    frames = payload.get("frames", [])
    for track in payload.get("tracks", []):
        relation_key = (
            "crosswalk_relations"
            if track["feature_type"] == "crosswalk"
            else "stopline_relations"
        )
        prior_state = None
        for frame in frames:
            relation = next(
                (
                    item
                    for item in frame.get(relation_key, [])
                    if item["track_id"] == track["track_id"]
                ),
                None,
            )
            state = relation.get("state") if relation else "unknown"
            if state != prior_state:
                transitions.append(
                    {
                        "track_id": track["track_id"],
                        "feature_type": track["feature_type"],
                        "frame_index": frame["frame_index"],
                        "time_since_start_s": frame.get("time_since_start_s"),
                        "from_state": prior_state,
                        "to_state": state,
                        "signed_longitudinal_distance_m": (
                            relation.get("signed_longitudinal_distance_m")
                            if relation
                            else None
                        ),
                    }
                )
                prior_state = state
    return {
        "track_counts": {
            "crosswalk": sum(
                track["feature_type"] == "crosswalk"
                for track in payload.get("tracks", [])
            ),
            "stopline": sum(
                track["feature_type"] == "stopline"
                for track in payload.get("tracks", [])
            ),
        },
        "associations": payload.get("stopline_crosswalk_associations", []),
        "state_transitions": transitions,
    }
