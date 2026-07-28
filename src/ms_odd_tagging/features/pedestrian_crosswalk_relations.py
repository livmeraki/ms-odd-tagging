"""Shared pedestrian-to-crosswalk and ego interaction relations."""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from ms_odd_tagging.features.road_feature_relations import (
    _point_in_polygon,
    _polygon_distance,
)


PEDESTRIAN_CROSSWALK_STATES = {
    "outside",
    "near_edge",
    "on_crosswalk",
    "leaving",
    "unknown",
}


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _signed_area(polygon: tuple[tuple[float, float], ...]) -> float:
    return 0.5 * sum(
        first[0] * second[1] - second[0] * first[1]
        for first, second in zip(polygon, polygon[1:] + polygon[:1])
    )


def _polygon_area(polygon: tuple[tuple[float, float], ...]) -> float:
    return abs(_signed_area(polygon))


def _is_convex(polygon: tuple[tuple[float, float], ...]) -> bool:
    if len(polygon) < 3:
        return False
    signs = []
    for first, second, third in zip(
        polygon,
        polygon[1:] + polygon[:1],
        polygon[2:] + polygon[:2],
    ):
        cross = (
            (second[0] - first[0]) * (third[1] - second[1])
            - (second[1] - first[1]) * (third[0] - second[0])
        )
        if abs(cross) > 1e-9:
            signs.append(cross > 0)
    return bool(signs) and all(sign == signs[0] for sign in signs)


def _line_intersection(first, second, clip_first, clip_second):
    first_dx, first_dy = second[0] - first[0], second[1] - first[1]
    clip_dx = clip_second[0] - clip_first[0]
    clip_dy = clip_second[1] - clip_first[1]
    denominator = first_dx * clip_dy - first_dy * clip_dx
    if abs(denominator) <= 1e-12:
        return second
    ratio = (
        (clip_first[0] - first[0]) * clip_dy
        - (clip_first[1] - first[1]) * clip_dx
    ) / denominator
    return (first[0] + ratio * first_dx, first[1] + ratio * first_dy)


def _clip_convex(
    subject: tuple[tuple[float, float], ...],
    clip: tuple[tuple[float, float], ...],
) -> tuple[tuple[float, float], ...]:
    output = list(subject)
    orientation = 1.0 if _signed_area(clip) >= 0 else -1.0
    for clip_first, clip_second in zip(clip, clip[1:] + clip[:1]):
        input_points = output
        output = []
        if not input_points:
            break

        def inside(point):
            cross = (
                (clip_second[0] - clip_first[0])
                * (point[1] - clip_first[1])
                - (clip_second[1] - clip_first[1])
                * (point[0] - clip_first[0])
            )
            return orientation * cross >= -1e-9

        previous = input_points[-1]
        for current in input_points:
            current_inside, previous_inside = inside(current), inside(previous)
            if current_inside:
                if not previous_inside:
                    output.append(
                        _line_intersection(
                            previous, current, clip_first, clip_second
                        )
                    )
                output.append(current)
            elif previous_inside:
                output.append(
                    _line_intersection(
                        previous, current, clip_first, clip_second
                    )
                )
            previous = current
    return tuple(output)


def _overlap_ratio(
    footprint: tuple[tuple[float, float], ...],
    crosswalk: tuple[tuple[float, float], ...],
) -> tuple[float, str]:
    footprint_area = _polygon_area(footprint)
    if footprint_area <= 1e-9:
        return 0.0, "invalid_footprint"
    if _is_convex(crosswalk):
        intersection = _clip_convex(footprint, crosswalk)
        return min(1.0, _polygon_area(intersection) / footprint_area), (
            "footprint_polygon_intersection"
        )
    center = (
        sum(point[0] for point in footprint) / len(footprint),
        sum(point[1] for point in footprint) / len(footprint),
    )
    samples = (*footprint, center)
    ratio = sum(_point_in_polygon(point, crosswalk) for point in samples) / len(
        samples
    )
    return ratio, "footprint_point_sample_fallback"


def build_pedestrian_crosswalk_relations(
    object_relations: dict[str, Any],
    road_feature_relations: dict[str, Any],
    settings: dict[str, Any],
    object_settings: dict[str, Any],
    road_settings: dict[str, Any],
) -> dict[str, Any]:
    """Join existing normalized pedestrian and crosswalk tracks frame by frame."""
    pedestrian_confidence = settings.get("pedestrian_confidence_threshold")
    if pedestrian_confidence is None:
        pedestrian_confidence = object_settings["minimum_object_confidence"]
    crosswalk_confidence = settings.get("crosswalk_confidence_threshold")
    if crosswalk_confidence is None:
        crosswalk_confidence = road_settings["minimum_feature_confidence"]
    minimum_track_age = settings.get("minimum_track_age_s")
    if minimum_track_age is None:
        minimum_track_age = object_settings["minimum_track_age_s"]

    crosswalk_tracks = {
        track["track_id"]: track
        for track in road_feature_relations.get("tracks", [])
        if track.get("feature_type") == "crosswalk"
        and len(track.get("polygon_lcs_m", [])) >= 3
        and (
            track.get("confidence") is None
            or float(track["confidence"]) >= crosswalk_confidence
        )
    }
    object_frames = {
        frame["frame_index"]: frame
        for frame in object_relations.get("frames", [])
    }
    road_frames = {
        frame["frame_index"]: frame
        for frame in road_feature_relations.get("frames", [])
    }
    previous: dict[str, dict[str, Any]] = {}
    bounds: dict[tuple[str, str], dict[str, int | None]] = {}
    result_frames = []

    all_frame_indexes = sorted(set(object_frames) | set(road_frames))
    for frame_index in all_frame_indexes:
        object_frame = object_frames.get(frame_index, {"objects": []})
        road_frame = road_frames.get(frame_index, {"crosswalk_relations": []})
        road_by_id = {
            relation["track_id"]: relation
            for relation in road_frame.get("crosswalk_relations", [])
        }
        interactions = []
        for pedestrian in object_frame.get("objects", []):
            if (
                pedestrian.get("normalized_category") != "pedestrian"
                or not pedestrian.get("valid_spatial_relation")
                or pedestrian.get("track_age_s", 0.0) + 1e-9
                < minimum_track_age
                or (
                    pedestrian.get("confidence") is not None
                    and pedestrian["confidence"] < pedestrian_confidence
                )
            ):
                continue
            footprint = tuple(
                (float(point[0]), float(point[1]))
                for point in pedestrian.get("object_footprint_lcs_m", [])
                if len(point) >= 2
                and _finite(point[0])
                and _finite(point[1])
            )
            if len(footprint) < 3:
                continue
            candidates = []
            for crosswalk_id, track in crosswalk_tracks.items():
                ego_relation = road_by_id.get(crosswalk_id)
                if (
                    not ego_relation
                    or not ego_relation.get("relation_valid")
                    or not ego_relation.get("path_compatible")
                    or ego_relation.get("state")
                    in {"far", "unknown", "passed"}
                ):
                    continue
                crosswalk_polygon = tuple(
                    (float(point[0]), float(point[1]))
                    for point in track["polygon_lcs_m"]
                )
                overlap_ratio, overlap_method = _overlap_ratio(
                    footprint, crosswalk_polygon
                )
                edge_distance = _polygon_distance(
                    footprint, crosswalk_polygon
                )
                center = (
                    sum(point[0] for point in footprint) / len(footprint),
                    sum(point[1] for point in footprint) / len(footprint),
                )
                center_on = _point_in_polygon(center, crosswalk_polygon)
                on = (
                    overlap_ratio
                    >= settings["pedestrian_crosswalk_overlap_threshold"]
                    or center_on
                )
                if on:
                    state = "on_crosswalk"
                elif edge_distance <= settings["maximum_edge_distance_m"]:
                    state = "near_edge"
                else:
                    state = "outside"
                candidates.append(
                    {
                        "crosswalk_id": crosswalk_id,
                        "state": state,
                        "overlap_ratio": overlap_ratio,
                        "overlap_method": overlap_method,
                        "nearest_crosswalk_distance_m": edge_distance,
                        "center_on_crosswalk": center_on,
                        "ego_relation": ego_relation,
                        "crosswalk_confidence": track.get("confidence"),
                    }
                )
            if not candidates:
                continue
            candidates.sort(
                key=lambda item: (
                    item["state"] != "on_crosswalk",
                    -item["overlap_ratio"],
                    item["nearest_crosswalk_distance_m"],
                    item["crosswalk_id"],
                )
            )
            prior = previous.get(pedestrian["track_id"])
            if prior:
                prior_candidate = next(
                    (
                        item
                        for item in candidates
                        if item["crosswalk_id"] == prior["crosswalk_id"]
                    ),
                    None,
                )
                if (
                    prior_candidate
                    and prior_candidate["nearest_crosswalk_distance_m"]
                    <= settings["maximum_edge_distance_m"]
                    + settings["association_hysteresis_m"]
                    and candidates[0]["state"] != "on_crosswalk"
                ):
                    candidates.remove(prior_candidate)
                    candidates.insert(0, prior_candidate)
            best = candidates[0]
            ambiguous = (
                len(candidates) > 1
                and candidates[1]["state"] == best["state"]
                and abs(
                    candidates[1]["nearest_crosswalk_distance_m"]
                    - best["nearest_crosswalk_distance_m"]
                )
                <= settings["same_crosswalk_association_tolerance_m"]
                and abs(
                    candidates[1]["overlap_ratio"] - best["overlap_ratio"]
                )
                <= settings["overlap_ambiguity_tolerance"]
            )
            state = best["state"]
            if (
                prior
                and prior["crosswalk_id"] == best["crosswalk_id"]
                and prior["state"] == "on_crosswalk"
                and state == "near_edge"
            ):
                state = "leaving"
            association_valid = not ambiguous and state in {
                "on_crosswalk",
                "near_edge",
                "leaving",
            }
            key = (pedestrian["track_id"], best["crosswalk_id"])
            bound = bounds.setdefault(key, {"first": None, "last": None})
            if association_valid:
                bound["first"] = (
                    frame_index if bound["first"] is None else bound["first"]
                )
                bound["last"] = frame_index
            relation = {
                "pedestrian_track_id": pedestrian["track_id"],
                "source_pedestrian_ids": pedestrian.get(
                    "source_object_ids", []
                ),
                "crosswalk_track_id": best["crosswalk_id"],
                "frame_index": frame_index,
                "timestamp_s": object_frame.get("time_since_start_s"),
                "pedestrian_footprint_lcs_m": [
                    list(point) for point in footprint
                ],
                "pedestrian_center_lcs_m": pedestrian.get("center_lcs_m"),
                "crosswalk_overlap_ratio": round(best["overlap_ratio"], 4),
                "overlap_method": best["overlap_method"],
                "nearest_crosswalk_distance_m": round(
                    best["nearest_crosswalk_distance_m"], 4
                ),
                "state": "unknown" if ambiguous else state,
                "relation_confidence": (
                    "uncertain"
                    if ambiguous
                    else "confirmed"
                    if state == "on_crosswalk"
                    else "provisional"
                ),
                "association_valid": association_valid,
                "association_ambiguous": ambiguous,
                "candidate_crosswalk_count": len(candidates),
                "near_ego": pedestrian.get("inside_proximity_region") is True,
                "pedestrian_ego_distance_m": pedestrian.get(
                    "nearest_footprint_distance_m"
                ),
                "signed_longitudinal_m": pedestrian.get(
                    "signed_longitudinal_m"
                ),
                "signed_lateral_m": pedestrian.get("signed_lateral_m"),
                "ego_crosswalk_state": best["ego_relation"].get("state"),
                "ego_on_same_crosswalk": (
                    best["ego_relation"].get("state") == "on"
                    and best["ego_relation"].get("ego_footprint_overlap")
                    is True
                ),
                "crosswalk_path_compatible": True,
                "pedestrian_confidence": pedestrian.get("confidence"),
                "crosswalk_confidence": best["crosswalk_confidence"],
            }
            interactions.append(relation)
            if not ambiguous:
                previous[pedestrian["track_id"]] = {
                    "crosswalk_id": best["crosswalk_id"],
                    "state": state,
                }
        result_frames.append(
            {
                "frame_index": frame_index,
                "time_since_start_s": object_frame.get("time_since_start_s"),
                "interactions": interactions,
            }
        )

    relation_tracks = [
        {
            "pedestrian_track_id": pedestrian_id,
            "crosswalk_track_id": crosswalk_id,
            "first_valid_frame": bound["first"],
            "last_valid_frame": bound["last"],
        }
        for (pedestrian_id, crosswalk_id), bound in sorted(bounds.items())
    ]
    return {
        "schema_version": "pedestrian-crosswalk-relations-v1",
        "recording_id": object_relations.get("recording_id"),
        "coordinate_system": "recording_lcs_m",
        "proximity_source": "object_relations.inside_proximity_region",
        "pedestrian_footprint_source": (
            "normalized_object_ground_footprint_lcs"
        ),
        "frames": result_frames,
        "relation_tracks": relation_tracks,
    }


def summarize_pedestrian_crosswalk_relations(
    payload: dict[str, Any],
) -> dict[str, Any]:
    relations = [
        relation
        for frame in payload.get("frames", [])
        for relation in frame.get("interactions", [])
    ]
    return {
        "relation_track_count": len(payload.get("relation_tracks", [])),
        "state_counts": dict(
            sorted(Counter(item["state"] for item in relations).items())
        ),
        "ambiguous_association_count": sum(
            item.get("association_ambiguous") is True for item in relations
        ),
        "on_crosswalk_relation_count": sum(
            item.get("state") == "on_crosswalk" for item in relations
        ),
    }


__all__ = [
    "PEDESTRIAN_CROSSWALK_STATES",
    "build_pedestrian_crosswalk_relations",
    "summarize_pedestrian_crosswalk_relations",
]
