"""Per-frame BEV lane candidate generation and ego/adjacent matching."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable

from ms_odd_tagging.input_generator.model_input import (
    ego_heading,
    lcs_to_ego,
    ld_feature_lcs_points,
    ld_feature_lookup,
    ld_point_lookup,
)
from ms_odd_tagging.lanelet2_poc.geometry import (
    distance,
    filter_local_boundaries,
    match_ego,
    merge_boundary_fragments,
    nearest_heading,
    pair_boundaries,
    polyline_distance,
    wrap_angle,
)
from ms_odd_tagging.lanelet2_poc.models import Boundary, LaneCandidate

LogFunction = Callable[[dict[str, Any]], None]


def _finite_pose(frame: dict[str, Any]) -> tuple[tuple[float, float], float] | None:
    ego = frame.get("ego") or {}
    position = ego.get("position_lcs_m") or []
    yaw = ego_heading(ego)
    if (
        len(position) < 2
        or not isinstance(yaw, (int, float))
        or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in position[:2])
        or not math.isfinite(yaw)
    ):
        return None
    return (float(position[0]), float(position[1])), float(yaw)


def _ego_to_lcs(point: tuple[float, float], ego_position: tuple[float, float], ego_yaw: float) -> tuple[float, float]:
    longitudinal, lateral = point
    cosine, sine = math.cos(ego_yaw), math.sin(ego_yaw)
    return (
        ego_position[0] + cosine * longitudinal - sine * lateral,
        ego_position[1] + sine * longitudinal + cosine * lateral,
    )


def _within_bev(point: tuple[float, float], config: dict[str, Any]) -> bool:
    longitudinal, lateral = point
    return (
        -float(config["back_m"]) <= longitudinal <= float(config["forward_m"])
        and -float(config["right_m"]) <= lateral <= float(config["left_m"])
    )


def _feature_boundaries(recording: dict[str, Any], frame: dict[str, Any], config: dict[str, Any]) -> list[Boundary]:
    pose = _finite_pose(frame)
    if pose is None:
        return []
    ego_position, ego_yaw = pose
    nearby = (frame.get("ld") or {}).get("nearby_feature_ids") or {}
    points_by_id = ld_point_lookup(recording)
    lane_lines = ld_feature_lookup(recording, "lane_lines", "line_id")
    road_boundaries = ld_feature_lookup(recording, "road_boundaries", "road_boundary_id")
    output: list[Boundary] = []

    for feature_id in nearby.get("lane_lines", []):
        feature = lane_lines.get(str(feature_id))
        if not feature:
            continue
        attributes = feature.get("attributes") or {}
        if (
            config.get("exclude_virtual_lane_lines", True)
            and str(attributes.get("pattern") or "").lower() == "virtual"
        ):
            continue
        points = tuple(
            lcs_to_ego(point, ego_position, ego_yaw)
            for point in ld_feature_lcs_points(feature, points_by_id)
        )
        if any(_within_bev(point, config) for point in points):
            output.append(Boundary(str(feature_id), points, "bev_lane_line", dict(attributes)))

    if config.get("include_drivable_road_boundaries", True):
        for feature_id in nearby.get("road_boundaries", []):
            feature = road_boundaries.get(str(feature_id))
            if not feature or str(feature.get("boundary_attribute") or "").lower() != "drivable":
                continue
            points = tuple(
                lcs_to_ego(point, ego_position, ego_yaw)
                for point in ld_feature_lcs_points(feature, points_by_id)
            )
            if any(_within_bev(point, config) for point in points):
                output.append(
                    Boundary(
                        str(feature_id),
                        points,
                        "bev_drivable_road_boundary",
                        {**(feature.get("attributes") or {}), "boundary_attribute": "drivable"},
                    )
                )
    return output


def _polyline_length(points: tuple[tuple[float, float], ...]) -> float:
    return sum(distance(a, b) for a, b in zip(points, points[1:]))


def _oriented_by_longitudinal(points: tuple[tuple[float, float], ...]) -> tuple[tuple[float, float], ...]:
    if len(points) < 2 or points[0][0] <= points[-1][0]:
        return points
    return tuple(reversed(points))


def _quadratic_fit(samples: list[tuple[float, float]]) -> tuple[float, float, float] | None:
    if len(samples) < 3:
        return None
    n = float(len(samples))
    sx = sum(x for x, _ in samples)
    sx2 = sum(x * x for x, _ in samples)
    sx3 = sum(x * x * x for x, _ in samples)
    sx4 = sum(x * x * x * x for x, _ in samples)
    sy = sum(y for _, y in samples)
    sxy = sum(x * y for x, y in samples)
    sx2y = sum(x * x * y for x, y in samples)
    matrix = [
        [sx4, sx3, sx2, sx2y],
        [sx3, sx2, sx, sxy],
        [sx2, sx, n, sy],
    ]
    for pivot in range(3):
        row = max(range(pivot, 3), key=lambda index: abs(matrix[index][pivot]))
        if abs(matrix[row][pivot]) <= 1e-9:
            return None
        if row != pivot:
            matrix[pivot], matrix[row] = matrix[row], matrix[pivot]
        divisor = matrix[pivot][pivot]
        for column in range(pivot, 4):
            matrix[pivot][column] /= divisor
        for row in range(3):
            if row == pivot:
                continue
            factor = matrix[row][pivot]
            for column in range(pivot, 4):
                matrix[row][column] -= factor * matrix[pivot][column]
    return matrix[0][3], matrix[1][3], matrix[2][3]


def _linear_fit(samples: list[tuple[float, float]]) -> tuple[float, float] | None:
    if len(samples) < 2:
        return None
    n = float(len(samples))
    sx = sum(x for x, _ in samples)
    sy = sum(y for _, y in samples)
    sx2 = sum(x * x for x, _ in samples)
    sxy = sum(x * y for x, y in samples)
    denominator = n * sx2 - sx * sx
    if abs(denominator) <= 1e-9:
        return None
    slope = (n * sxy - sx * sy) / denominator
    intercept = (sy - slope * sx) / n
    return slope, intercept


def _extend_side(
    points: tuple[tuple[float, float], ...],
    *,
    side: str,
    distance_m: float,
    config: dict[str, Any],
) -> tuple[list[tuple[float, float]], list[str]]:
    if distance_m <= 0.0 or len(points) < 2:
        return [], []
    step = max(0.5, float(config["lane_extension_step_m"]))
    fit_count = max(2, int(config["lane_extension_fit_points"]))
    source = list(points[:fit_count] if side == "backward" else points[-fit_count:])
    if len(source) < 2:
        return [], ["insufficient_fit_points"]
    endpoint = points[0] if side == "backward" else points[-1]
    use_curvature = bool(config.get("lane_extension_allow_curvature", True))
    quadratic = _quadratic_fit(source) if use_curvature else None
    linear = _linear_fit(source)
    if quadratic is None and linear is None:
        return [], ["fit_failed"]

    def value_at(x: float) -> float:
        if quadratic is not None:
            a, b, c = quadratic
            return a * x * x + b * x + c
        assert linear is not None
        slope, intercept = linear
        return slope * x + intercept

    def heading_at(x: float) -> float:
        if quadratic is not None:
            a, b, _ = quadratic
            return math.atan2(2.0 * a * x + b, 1.0)
        assert linear is not None
        return math.atan2(linear[0], 1.0)

    endpoint_heading = heading_at(endpoint[0])
    sign = -1.0 if side == "backward" else 1.0
    max_heading = math.radians(float(config["lane_extension_max_heading_change_deg"]))
    max_drift = float(config["lane_extension_max_lateral_drift_m"])
    generated = []
    reasons = []
    travelled = step
    while travelled <= distance_m + 1e-6:
        x = endpoint[0] + sign * travelled
        y = value_at(x)
        if not _within_bev((x, y), config):
            reasons.append("extension_reached_bev_extent")
            break
        if abs(wrap_angle(heading_at(x) - endpoint_heading)) > max_heading:
            reasons.append("extension_heading_change_capped")
            break
        if abs(y - endpoint[1]) > max_drift:
            reasons.append("extension_lateral_drift_capped")
            break
        generated.append((x, y))
        travelled += step
    if side == "backward":
        generated.reverse()
    return generated, reasons


def extend_boundaries(
    boundaries: list[Boundary],
    config: dict[str, Any],
) -> tuple[list[Boundary], list[dict[str, Any]]]:
    if not config.get("extend_lane_boundaries", False):
        return boundaries, []
    output = []
    debug = []
    for boundary in boundaries:
        points = _oriented_by_longitudinal(boundary.points)
        reasons = []
        if _polyline_length(points) < float(config["lane_extension_min_source_length_m"]):
            output.append(boundary)
            debug.append(
                {
                    "boundary_id": boundary.boundary_id,
                    "extended": False,
                    "reasons": ["source_boundary_too_short"],
                }
            )
            continue
        backward, backward_reasons = _extend_side(
            points,
            side="backward",
            distance_m=float(config["lane_extension_backward_m"]),
            config=config,
        )
        forward, forward_reasons = _extend_side(
            points,
            side="forward",
            distance_m=float(config["lane_extension_forward_m"]),
            config=config,
        )
        reasons.extend(backward_reasons)
        reasons.extend(forward_reasons)
        extended_points = tuple(backward + list(points) + forward)
        attributes = dict(boundary.attributes)
        if backward or forward:
            attributes["bev_lane_extension"] = {
                "backward_points": len(backward),
                "forward_points": len(forward),
                "allow_curvature": bool(config.get("lane_extension_allow_curvature", True)),
            }
        output.append(
            Boundary(boundary.boundary_id, extended_points, boundary.source_kind, attributes)
        )
        debug.append(
            {
                "boundary_id": boundary.boundary_id,
                "extended": bool(backward or forward),
                "backward_points": len(backward),
                "forward_points": len(forward),
                "reasons": sorted(set(reasons)),
            }
        )
    return output, debug


def _mean_centerline_distance(first: LaneCandidate, second: LaneCandidate) -> float:
    if not first.centerline or not second.centerline:
        return math.inf
    return sum(polyline_distance(point, second.centerline) for point in first.centerline) / len(first.centerline)


def deduplicate_lanes(lanes: list[LaneCandidate], config: dict[str, Any]) -> tuple[list[LaneCandidate], list[dict[str, Any]]]:
    kept: list[LaneCandidate] = []
    rejected: list[dict[str, Any]] = []
    centerline_threshold = float(config["deduplicate_centerline_distance_m"])
    lateral_threshold = float(config["deduplicate_lateral_distance_m"])
    for lane in sorted(lanes, key=lambda item: (-item.pair_score, item.lane_id)):
        duplicate_of = None
        lane_lateral = sum(point[1] for point in lane.centerline) / len(lane.centerline)
        for existing in kept:
            existing_lateral = sum(point[1] for point in existing.centerline) / len(existing.centerline)
            same_boundaries = {
                lane.left_boundary_id,
                lane.right_boundary_id,
            } == {existing.left_boundary_id, existing.right_boundary_id}
            near_centerline = _mean_centerline_distance(lane, existing) <= centerline_threshold
            near_lateral = abs(lane_lateral - existing_lateral) <= lateral_threshold
            if same_boundaries or (near_centerline and near_lateral):
                duplicate_of = existing.lane_id
                break
        if duplicate_of is None:
            kept.append(lane)
        else:
            rejected.append(
                {
                    "lane_id": lane.lane_id,
                    "duplicate_of": duplicate_of,
                    "reasons": ["duplicate_bev_lane_candidate"],
                }
            )
    return kept, rejected


def _lane_output(
    lane: LaneCandidate | None,
    ego_position: tuple[float, float],
    ego_yaw: float,
    *,
    confidence: float | None = None,
    selection_source: str | None = None,
    rejection_reasons: list[str] | None = None,
) -> dict[str, Any]:
    if lane is None:
        return {
            "exists": False,
            "lane_id": None,
            "boundary_ids": {"left": None, "right": None},
            "polygon_bev_m": [],
            "polygon_lcs_m": [],
            "confidence": 0.0,
            "selection_source": selection_source,
            "rejection_reasons": rejection_reasons or [],
        }
    return {
        "exists": True,
        "lane_id": lane.lane_id,
        "boundary_ids": {"left": lane.left_boundary_id, "right": lane.right_boundary_id},
        "polygon_bev_m": [[round(x, 3), round(y, 3)] for x, y in lane.polygon],
        "polygon_lcs_m": [
            [round(x, 3), round(y, 3)]
            for x, y in (_ego_to_lcs(point, ego_position, ego_yaw) for point in lane.polygon)
        ],
        "confidence": round(lane.pair_score if confidence is None else confidence, 4),
        "selection_source": selection_source,
        "rejection_reasons": rejection_reasons or [],
    }


def _adjacent_lanes(
    lanes: list[LaneCandidate],
    ego_lane_id: str | None,
    config: dict[str, Any],
) -> tuple[dict[str, str | None], dict[str, Any]]:
    if ego_lane_id is None:
        return {"left": None, "right": None}, {"method": "no_ego_lane", "rejected": []}
    ego_lane = next(lane for lane in lanes if lane.lane_id == ego_lane_id)
    ego_heading = nearest_heading((0.0, 0.0), ego_lane.centerline) or 0.0
    rejected = []
    selected: dict[str, tuple[float, LaneCandidate] | None] = {"left": None, "right": None}
    for lane in lanes:
        if lane.lane_id == ego_lane_id:
            continue
        nearest = min(lane.centerline, key=lambda point: distance((0.0, 0.0), point))
        lateral = nearest[1]
        side = "left" if lateral > 0 else "right"
        lane_heading = nearest_heading((0.0, 0.0), lane.centerline)
        heading_difference = (
            math.inf
            if lane_heading is None
            else abs(math.degrees(wrap_angle(lane_heading - ego_heading)))
        )
        reasons = []
        if not (
            float(config["minimum_adjacent_lateral_offset_m"])
            <= abs(lateral)
            <= float(config["maximum_adjacent_lateral_offset_m"])
        ):
            reasons.append("adjacent_lateral_offset_out_of_range")
        if heading_difference > float(config["maximum_adjacent_heading_difference_deg"]):
            reasons.append("adjacent_heading_mismatch")
        record = {
            "lane_id": lane.lane_id,
            "side": side,
            "lateral_offset_m": round(lateral, 3),
            "heading_difference_deg": round(heading_difference, 3),
            "reasons": reasons,
        }
        if reasons:
            rejected.append(record)
            continue
        score = abs(lateral) - lane.pair_score
        if selected[side] is None or score < selected[side][0]:
            selected[side] = (score, lane)
    return (
        {
            "left": selected["left"][1].lane_id if selected["left"] else None,
            "right": selected["right"][1].lane_id if selected["right"] else None,
        },
        {"method": "bev_lateral_same_direction", "rejected": rejected},
    )


def _build_lanes_from_boundaries(
    boundaries: list[Boundary],
    config: dict[str, Any],
) -> tuple[list[Boundary], list[LaneCandidate], dict[str, list[dict[str, Any]]]]:
    local, boundary_rejections = filter_local_boundaries(
        boundaries, (0.0, 0.0, 0.0), config
    )
    lanes, pair_rejections = pair_boundaries(local, (0.0, 0.0, 0.0), config)
    lanes, duplicate_rejections = deduplicate_lanes(lanes, config)
    return local, lanes, {
        "boundaries": boundary_rejections,
        "pairs": pair_rejections,
        "duplicates": duplicate_rejections,
    }


def run_frame(
    recording: dict[str, Any],
    frame: dict[str, Any],
    config: dict[str, Any],
    *,
    log: LogFunction | None = None,
) -> dict[str, Any]:
    pose = _finite_pose(frame)
    frame_index = frame.get("frame_index")
    if pose is None:
        return {
            "frame_index": frame_index,
            "status": "invalid_input",
            "rejection_reasons": ["ego_pose_must_be_finite_x_y_yaw"],
            "ego_lane": _lane_output(None, (0.0, 0.0), 0.0, rejection_reasons=["invalid_ego_pose"]),
            "left_adjacent": _lane_output(None, (0.0, 0.0), 0.0, rejection_reasons=["invalid_ego_pose"]),
            "right_adjacent": _lane_output(None, (0.0, 0.0), 0.0, rejection_reasons=["invalid_ego_pose"]),
        }
    ego_position, ego_yaw = pose
    boundaries = _feature_boundaries(recording, frame, config)
    merged = merge_boundary_fragments(boundaries, (0.0, 0.0, 0.0), config)
    extended, extension_debug = extend_boundaries(merged, config)
    local, lanes, rejections = _build_lanes_from_boundaries(extended, config)
    match = match_ego(lanes, (0.0, 0.0, 0.0), config)
    matching_source = (
        "extended_boundaries"
        if config.get("extend_lane_boundaries", False)
        else "merged_boundaries"
    )
    if config.get("extend_lane_boundaries", False) and match["lane_id"] is None:
        fallback_local, fallback_lanes, fallback_rejections = _build_lanes_from_boundaries(
            merged, config
        )
        fallback_match = match_ego(fallback_lanes, (0.0, 0.0, 0.0), config)
        if fallback_match["lane_id"] is not None:
            local = fallback_local
            lanes = fallback_lanes
            rejections = fallback_rejections
            match = fallback_match
            matching_source = "merged_boundaries_after_extension_unmatched"
    by_id = {lane.lane_id: lane for lane in lanes}
    neighbors, adjacency = _adjacent_lanes(lanes, match["lane_id"], config)
    result = {
        "frame_index": frame_index,
        "status": "matched" if match["lane_id"] else "unmatched",
        "coordinate_system": "BEV_EGO_METERS",
        "ego_pose_lcs": {"x": ego_position[0], "y": ego_position[1], "yaw": ego_yaw},
        "bev_extent_m": {
            "left": config["left_m"],
            "right": config["right_m"],
            "back": config["back_m"],
            "forward": config["forward_m"],
        },
        "ego_lane": _lane_output(
            by_id.get(match["lane_id"]),
            ego_position,
            ego_yaw,
            confidence=match.get("confidence"),
            selection_source=match.get("method"),
            rejection_reasons=[] if match["lane_id"] else ["no_acceptable_ego_lane"],
        ),
        "left_adjacent": _lane_output(
            by_id.get(neighbors["left"]),
            ego_position,
            ego_yaw,
            selection_source=adjacency["method"],
            rejection_reasons=[] if neighbors["left"] else ["no_bev_left_neighbor"],
        ),
        "right_adjacent": _lane_output(
            by_id.get(neighbors["right"]),
            ego_position,
            ego_yaw,
            selection_source=adjacency["method"],
            rejection_reasons=[] if neighbors["right"] else ["no_bev_right_neighbor"],
        ),
        "matching": match,
        "matching_source": matching_source,
        "adjacency": adjacency,
        "candidate_lanes": [
            {
                **lane.as_dict(),
                "polygon_bev_m": [[round(x, 3), round(y, 3)] for x, y in lane.polygon],
            }
            for lane in lanes
        ],
        "lane_extension": {
            "enabled": bool(config.get("extend_lane_boundaries", False)),
            "used_for_matching": matching_source == "extended_boundaries",
            "boundaries": extension_debug,
        },
        "rejections": rejections,
    }
    if log:
        log(
            {
                "event": "bev_lane_poc_frame",
                "frame_index": frame_index,
                "status": result["status"],
                "boundary_count": len(boundaries),
                "extended_boundary_count": sum(
                    1 for item in extension_debug if item.get("extended")
                ),
                "candidate_lane_count": len(lanes),
                "matching_source": matching_source,
                "ego_lane_id": result["ego_lane"]["lane_id"],
                "left_adjacent_lane_id": result["left_adjacent"]["lane_id"],
                "right_adjacent_lane_id": result["right_adjacent"]["lane_id"],
            }
        )
    return result


def run_recording(
    recording: dict[str, Any],
    config: dict[str, Any],
    *,
    frame_indices: set[int] | None = None,
    log: LogFunction | None = None,
) -> dict[str, Any]:
    if not config.get("feature_enabled", False):
        return {
            "schema_version": "bev-lane-poc-v1",
            "feature_enabled": False,
            "status": "disabled",
            "recording_id": recording.get("recording_id"),
            "frames": [],
        }
    frames = []
    for frame in recording.get("frames", []):
        frame_index = int(frame["frame_index"])
        if frame_indices is not None and frame_index not in frame_indices:
            continue
        frames.append(run_frame(recording, frame, config, log=log))
    return {
        "schema_version": "bev-lane-poc-v1",
        "feature_enabled": True,
        "status": "completed",
        "recording_id": recording.get("recording_id"),
        "assumptions": [
            "LD lane points are converted into ego-heading-up BEV meters per frame.",
            "Virtual lane lines are excluded from assignment by default.",
            "Selected BEV polygons are back-projected to LCS only for comparison.",
            "Topology classification is not part of this first BEV geometry POC.",
        ],
        "config": config,
        "frames": frames,
    }


def jsonl_logger(path: Path) -> LogFunction:
    path.parent.mkdir(parents=True, exist_ok=True)

    def write(event: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=True, separators=(",", ":")) + "\n")

    return write
