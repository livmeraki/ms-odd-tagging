"""Per-frame BEV lane candidate generation and ego/adjacent matching."""

from __future__ import annotations

import hashlib
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

    accepted_boundary_attributes = {"drivable"}
    if config.get("include_non_drivable_road_boundaries", False):
        accepted_boundary_attributes.add("non_drivable")
    if config.get("include_drivable_road_boundaries", True):
        for feature_id in nearby.get("road_boundaries", []):
            feature = road_boundaries.get(str(feature_id))
            boundary_attribute = str(feature.get("boundary_attribute") or "").lower() if feature else ""
            if not feature or boundary_attribute not in accepted_boundary_attributes:
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
                        f"bev_{boundary_attribute}_road_boundary",
                        {**(feature.get("attributes") or {}), "boundary_attribute": boundary_attribute},
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


def _lateral_at_longitudinal(
    points: tuple[tuple[float, float], ...],
    longitudinal: float = 0.0,
) -> float | None:
    if not points:
        return None
    ordered = sorted(points, key=lambda point: point[0])
    for start, end in zip(ordered, ordered[1:]):
        low, high = sorted((start[0], end[0]))
        if low - 1e-9 <= longitudinal <= high + 1e-9:
            span = end[0] - start[0]
            ratio = 0.0 if abs(span) <= 1e-9 else (longitudinal - start[0]) / span
            return start[1] + ratio * (end[1] - start[1])
    nearest = min(ordered, key=lambda point: abs(point[0] - longitudinal))
    return nearest[1]


def _coverage_metrics(points: tuple[tuple[float, float], ...]) -> dict[str, float | None]:
    if not points:
        return {
            "backward_coverage_m": None,
            "forward_coverage_m": None,
            "longitudinal_min_m": None,
            "longitudinal_max_m": None,
        }
    longitudinal = [point[0] for point in points]
    minimum = min(longitudinal)
    maximum = max(longitudinal)
    return {
        "backward_coverage_m": round(max(0.0, -minimum), 3),
        "forward_coverage_m": round(max(0.0, maximum), 3),
        "longitudinal_min_m": round(minimum, 3),
        "longitudinal_max_m": round(maximum, 3),
    }


def _shift_lateral(
    points: tuple[tuple[float, float], ...],
    offset_m: float,
) -> tuple[tuple[float, float], ...]:
    return tuple((point[0], point[1] + offset_m) for point in points)


def _single_boundary_lane_id(boundary_id: str, observed_side: str, width_m: float) -> str:
    digest = hashlib.sha1(f"{boundary_id}|{observed_side}|{width_m:.3f}".encode("utf-8")).hexdigest()[:12]
    return f"poc_single_lane_{digest}"


def _extend_single_boundary_to_ego_station(
    points: tuple[tuple[float, float], ...],
    config: dict[str, Any],
) -> tuple[tuple[tuple[float, float], ...], bool, str | None]:
    if not points:
        return points, False, "single_boundary_insufficient_points"
    ordered = _oriented_by_longitudinal(points)
    minimum_x = min(point[0] for point in ordered)
    maximum_x = max(point[0] for point in ordered)
    if minimum_x <= 0.0 <= maximum_x:
        return ordered, False, None
    max_gap = float(config["single_boundary_max_ego_station_gap_m"])
    if minimum_x > 0.0:
        gap = minimum_x
        fit_samples = list(ordered[: max(2, int(config["lane_extension_fit_points"]))])
        insert_at_front = True
        nearest_endpoint = ordered[0]
    else:
        gap = -maximum_x
        fit_samples = list(ordered[-max(2, int(config["lane_extension_fit_points"])) :])
        insert_at_front = False
        nearest_endpoint = ordered[-1]
    if gap > max_gap:
        return ordered, False, "single_boundary_ego_station_gap_too_large"
    fit = _linear_fit(fit_samples)
    if fit is None:
        return ordered, False, "single_boundary_ego_station_fit_failed"
    slope, intercept = fit
    ego_station_point = (0.0, intercept)
    max_drift = float(config["single_boundary_max_station_lateral_drift_m"])
    if abs(ego_station_point[1] - nearest_endpoint[1]) > max_drift:
        return ordered, False, None
    if insert_at_front:
        return (ego_station_point,) + ordered, True, None
    return ordered + (ego_station_point,), True, None


def _single_boundary_lane_candidates(
    boundaries: list[Boundary],
    config: dict[str, Any],
) -> tuple[list[LaneCandidate], list[dict[str, Any]]]:
    if not config.get("enable_single_boundary_lane_candidates", False):
        return [], []
    lanes: list[LaneCandidate] = []
    rejected: list[dict[str, Any]] = []
    nominal_width = float(config["single_boundary_nominal_lane_width_m"])
    minimum_length = float(config["single_boundary_minimum_length_m"])
    max_abs_lateral = float(config["single_boundary_max_abs_lateral_at_ego_m"])
    pair_score = float(config["single_boundary_pair_score"])
    if nominal_width <= 0.0:
        return [], [{"reasons": ["invalid_single_boundary_nominal_lane_width_m"]}]
    for boundary in boundaries:
        points, station_extended, station_reason = _extend_single_boundary_to_ego_station(
            boundary.points,
            config,
        )
        boundary_lateral = _lateral_at_longitudinal(points)
        length = _polyline_length(points)
        coverage = _coverage_metrics(points)
        reasons = []
        if station_reason:
            reasons.append(station_reason)
        if len(points) < 2:
            reasons.append("single_boundary_insufficient_points")
        if length < minimum_length:
            reasons.append("single_boundary_too_short")
        if boundary_lateral is None or abs(boundary_lateral) > max_abs_lateral:
            reasons.append("single_boundary_lateral_out_of_range")
        if reasons:
            rejected.append(
                {
                    "boundary_id": boundary.boundary_id,
                    "reasons": reasons,
                    "metrics": {
                        "length_m": round(length, 3),
                        "ego_station_extended": station_extended,
                        "boundary_lateral_at_ego_m": None
                        if boundary_lateral is None
                        else round(boundary_lateral, 3),
                        **coverage,
                    },
                }
            )
            continue
        assert boundary_lateral is not None
        observed_side = "left" if boundary_lateral >= 0.0 else "right"
        if observed_side == "left":
            left = points
            right = _shift_lateral(points, -nominal_width)
        else:
            right = points
            left = _shift_lateral(points, nominal_width)
        centerline = tuple(
            ((left_point[0] + right_point[0]) / 2.0, (left_point[1] + right_point[1]) / 2.0)
            for left_point, right_point in zip(left, right)
        )
        synthetic_side = "right" if observed_side == "left" else "left"
        synthetic_id = f"synthetic_{synthetic_side}_from_{boundary.boundary_id}"
        left_id = boundary.boundary_id if observed_side == "left" else synthetic_id
        right_id = boundary.boundary_id if observed_side == "right" else synthetic_id
        lanes.append(
            LaneCandidate(
                _single_boundary_lane_id(boundary.boundary_id, observed_side, nominal_width),
                left_id,
                right_id,
                left,
                right,
                centerline,
                tuple(left + tuple(reversed(right))),
                pair_score,
                {
                    "single_boundary_candidate": True,
                    "source_boundary_id": boundary.boundary_id,
                    "source_kind": boundary.source_kind,
                    "observed_boundary_side": observed_side,
                    "synthetic_boundary_side": synthetic_side,
                    "nominal_width_m": round(nominal_width, 3),
                    "boundary_lateral_at_ego_m": round(boundary_lateral, 3),
                    "center_lateral_at_ego_m": round(boundary_lateral + (-nominal_width / 2.0 if observed_side == "left" else nominal_width / 2.0), 3),
                    "minimum_width_m": round(nominal_width, 3),
                    "median_width_m": round(nominal_width, 3),
                    "maximum_width_m": round(nominal_width, 3),
                    "width_range_m": 0.0,
                    "length_m": round(length, 3),
                    "ego_station_extended": station_extended,
                    **coverage,
                },
            )
        )
    lanes.sort(key=lambda lane: (-lane.pair_score, lane.lane_id))
    return lanes, rejected


def _boundary_source_ids(boundaries_by_id: dict[str, Boundary], boundary_id: str) -> list[str]:
    boundary = boundaries_by_id.get(boundary_id)
    if boundary is None:
        return [boundary_id]
    source_ids = (boundary.attributes or {}).get("merged_from_boundary_ids")
    if isinstance(source_ids, list) and source_ids:
        return [str(item) for item in source_ids]
    return [boundary.boundary_id]


def _lane_stable_key(lane: LaneCandidate, boundaries_by_id: dict[str, Boundary]) -> str:
    left = ",".join(_boundary_source_ids(boundaries_by_id, lane.left_boundary_id))
    right = ",".join(_boundary_source_ids(boundaries_by_id, lane.right_boundary_id))
    return f"L:{left}|R:{right}"


def _lane_assignment_metrics(lane: LaneCandidate) -> dict[str, Any]:
    center_lateral = _lateral_at_longitudinal(lane.centerline)
    left_lateral = _lateral_at_longitudinal(lane.left)
    right_lateral = _lateral_at_longitudinal(lane.right)
    width = (
        None
        if left_lateral is None or right_lateral is None
        else abs(left_lateral - right_lateral)
    )
    heading = nearest_heading((0.0, 0.0), lane.centerline)
    coverage = _coverage_metrics(lane.centerline)
    return {
        "center_lateral_at_ego_m": None if center_lateral is None else round(center_lateral, 3),
        "left_boundary_lateral_at_ego_m": None if left_lateral is None else round(left_lateral, 3),
        "right_boundary_lateral_at_ego_m": None if right_lateral is None else round(right_lateral, 3),
        "width_at_ego_m": None if width is None else round(width, 3),
        "heading_at_ego_deg": None if heading is None else round(math.degrees(heading), 3),
        **coverage,
    }


def _assignment_quality(
    lane: LaneCandidate | None,
    match: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    if lane is None:
        return {
            "state": "unknown",
            "confidence": 0.0,
            "reasons": ["no_acceptable_ego_lane"],
        }
    metrics = _lane_assignment_metrics(lane)
    reasons = []
    confidence = float(match.get("confidence") or 0.0)
    if confidence < float(config["minimum_assignment_confidence"]):
        reasons.append("assignment_confidence_below_threshold")
    if match.get("ambiguous") is True:
        reasons.append("assignment_ambiguous")
    forward = metrics.get("forward_coverage_m")
    backward = metrics.get("backward_coverage_m")
    center_lateral = metrics.get("center_lateral_at_ego_m")
    width = metrics.get("width_at_ego_m")
    if forward is None or forward < float(config["minimum_assignment_forward_coverage_m"]):
        reasons.append("insufficient_forward_lane_coverage")
    if backward is None or backward < float(config["minimum_assignment_backward_coverage_m"]):
        reasons.append("insufficient_backward_lane_coverage")
    if center_lateral is None or abs(center_lateral) > float(config["maximum_assignment_abs_center_lateral_m"]):
        reasons.append("ego_not_near_candidate_centerline")
    if width is None:
        reasons.append("width_at_ego_unavailable")
    elif width < float(config["minimum_assignment_width_at_ego_m"]):
        reasons.append("width_at_ego_too_narrow")
    elif width > float(config["maximum_assignment_width_at_ego_m"]):
        reasons.append("width_at_ego_too_wide")
    return {
        "state": "stable_candidate" if not reasons else "weak_candidate",
        "confidence": round(confidence, 4),
        "reasons": reasons,
        "metrics": metrics,
    }


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
    stable_key: str | None = None,
    assignment_quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if lane is None:
        return {
            "exists": False,
            "lane_id": None,
            "stable_key": None,
            "boundary_ids": {"left": None, "right": None},
            "polygon_bev_m": [],
            "polygon_lcs_m": [],
            "confidence": 0.0,
            "selection_source": selection_source,
            "rejection_reasons": rejection_reasons or [],
            "assignment_quality": assignment_quality
            or {
                "state": "unknown",
                "confidence": 0.0,
                "reasons": rejection_reasons or [],
            },
        }
    return {
        "exists": True,
        "lane_id": lane.lane_id,
        "stable_key": stable_key,
        "boundary_ids": {"left": lane.left_boundary_id, "right": lane.right_boundary_id},
        "polygon_bev_m": [[round(x, 3), round(y, 3)] for x, y in lane.polygon],
        "polygon_lcs_m": [
            [round(x, 3), round(y, 3)]
            for x, y in (_ego_to_lcs(point, ego_position, ego_yaw) for point in lane.polygon)
        ],
        "confidence": round(lane.pair_score if confidence is None else confidence, 4),
        "selection_source": selection_source,
        "rejection_reasons": rejection_reasons or [],
        "assignment_quality": assignment_quality
        or {
            "state": "not_evaluated",
            "confidence": round(lane.pair_score if confidence is None else confidence, 4),
            "reasons": [],
            "metrics": _lane_assignment_metrics(lane),
        },
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
    paired_lanes, pair_rejections = pair_boundaries(local, (0.0, 0.0, 0.0), config)
    single_lanes, single_rejections = _single_boundary_lane_candidates(local, config)
    lanes = paired_lanes + single_lanes
    lanes, duplicate_rejections = deduplicate_lanes(lanes, config)
    return local, lanes, {
        "boundaries": boundary_rejections,
        "pairs": pair_rejections,
        "single_boundary": single_rejections,
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
    boundaries_by_id = {boundary.boundary_id: boundary for boundary in local}
    ego_lane = by_id.get(match["lane_id"])
    ego_quality = _assignment_quality(ego_lane, match, config)
    result = {
        "frame_index": frame_index,
        "timestamp_unix_s": frame.get("timestamp_unix_s"),
        "time_since_start_s": frame.get("time_since_start_s"),
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
            ego_lane,
            ego_position,
            ego_yaw,
            confidence=match.get("confidence"),
            selection_source=match.get("method"),
            rejection_reasons=[] if match["lane_id"] else ["no_acceptable_ego_lane"],
            stable_key=(
                _lane_stable_key(ego_lane, boundaries_by_id) if ego_lane else None
            ),
            assignment_quality=ego_quality,
        ),
        "left_adjacent": _lane_output(
            by_id.get(neighbors["left"]),
            ego_position,
            ego_yaw,
            selection_source=adjacency["method"],
            rejection_reasons=[] if neighbors["left"] else ["no_bev_left_neighbor"],
            stable_key=(
                _lane_stable_key(by_id[neighbors["left"]], boundaries_by_id)
                if neighbors["left"] in by_id
                else None
            ),
        ),
        "right_adjacent": _lane_output(
            by_id.get(neighbors["right"]),
            ego_position,
            ego_yaw,
            selection_source=adjacency["method"],
            rejection_reasons=[] if neighbors["right"] else ["no_bev_right_neighbor"],
            stable_key=(
                _lane_stable_key(by_id[neighbors["right"]], boundaries_by_id)
                if neighbors["right"] in by_id
                else None
            ),
        ),
        "assignment_quality": ego_quality,
        "matching": match,
        "matching_source": matching_source,
        "adjacency": adjacency,
        "candidate_lanes": [
            {
                **lane.as_dict(),
                "polygon_bev_m": [[round(x, 3), round(y, 3)] for x, y in lane.polygon],
                "stable_key": _lane_stable_key(lane, boundaries_by_id),
                "assignment_metrics": _lane_assignment_metrics(lane),
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


def _frame_time_s(frame: dict[str, Any], fallback_position: int) -> float:
    for key in ("time_since_start_s", "timestamp_unix_s"):
        value = frame.get(key)
        if isinstance(value, (int, float)) and math.isfinite(value):
            return float(value)
    return float(fallback_position)


def _stable_assignment_summary(
    frames: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    if not frames:
        return {
            "frame_count": 0,
            "matched_frame_count": 0,
            "stable_candidate_frame_count": 0,
            "weak_candidate_frame_count": 0,
            "unknown_frame_count": 0,
            "stable_runs": [],
            "transitions": [],
        }
    stable_runs = []
    transitions = []
    previous_key = None
    previous_stable_key = None
    run_start = 0

    def lane_key(frame: dict[str, Any]) -> str | None:
        quality = frame.get("assignment_quality") or {}
        if quality.get("state") != "stable_candidate":
            return None
        return (frame.get("ego_lane") or {}).get("stable_key")

    def close_run(end_position: int) -> None:
        key = lane_key(frames[run_start])
        if key is None:
            return
        start_frame = frames[run_start]
        end_frame = frames[end_position]
        start_time = _frame_time_s(start_frame, run_start)
        end_time = _frame_time_s(end_frame, end_position)
        stable_runs.append(
            {
                "stable_key": key,
                "lane_id": (start_frame.get("ego_lane") or {}).get("lane_id"),
                "start_frame": start_frame.get("frame_index"),
                "end_frame": end_frame.get("frame_index"),
                "frame_count": end_position - run_start + 1,
                "duration_s": round(max(0.0, end_time - start_time), 4),
                "mean_confidence": round(
                    sum(
                        float((frame.get("assignment_quality") or {}).get("confidence") or 0.0)
                        for frame in frames[run_start : end_position + 1]
                    )
                    / (end_position - run_start + 1),
                    4,
                ),
            }
        )

    for position, frame in enumerate(frames):
        key = lane_key(frame)
        if position == 0:
            previous_key = key
            previous_stable_key = key
            continue
        if key != previous_key:
            close_run(position - 1)
            run_start = position
            if key is not None and previous_stable_key is not None and key != previous_stable_key:
                transitions.append(
                    {
                        "from_stable_key": previous_stable_key,
                        "to_stable_key": key,
                        "transition_frame": frame.get("frame_index"),
                        "transition_position": position,
                    }
                )
            if key is not None:
                previous_stable_key = key
            previous_key = key
    close_run(len(frames) - 1)

    min_duration = float(config.get("minimum_stable_run_duration_s", 0.0))
    stable_runs = [
        {
            **run,
            "meets_minimum_duration": run["duration_s"] + 1e-9 >= min_duration,
        }
        for run in stable_runs
    ]
    quality_states = [
        (frame.get("assignment_quality") or {}).get("state", "unknown")
        for frame in frames
    ]
    return {
        "frame_count": len(frames),
        "matched_frame_count": sum(frame.get("status") == "matched" for frame in frames),
        "stable_candidate_frame_count": quality_states.count("stable_candidate"),
        "weak_candidate_frame_count": quality_states.count("weak_candidate"),
        "unknown_frame_count": quality_states.count("unknown"),
        "unique_stable_lane_count": len(
            {run["stable_key"] for run in stable_runs if run["meets_minimum_duration"]}
        ),
        "stable_runs": stable_runs,
        "transitions": transitions,
        "minimum_stable_run_duration_s": min_duration,
    }


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
    assignment_summary = _stable_assignment_summary(frames, config)
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
        "assignment_summary": assignment_summary,
        "frames": frames,
    }


def jsonl_logger(path: Path) -> LogFunction:
    path.parent.mkdir(parents=True, exist_ok=True)

    def write(event: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=True, separators=(",", ":")) + "\n")

    return write
