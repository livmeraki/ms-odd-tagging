import json

from ms_odd_tagging.bev_lane_poc.config import load_config
from ms_odd_tagging.bev_lane_poc.runner import extend_boundaries, run_frame, run_recording
from ms_odd_tagging.lanelet2_poc.models import Boundary


def _line(line_id: str, y: float, *, pattern: str = "solid", point_start: int = 0) -> tuple[list[dict], dict]:
    points = [
        {"point_id": f"p{point_start + index}", "position_lcs_m": [float(x), y, 0.0]}
        for index, x in enumerate(range(-20, 81, 5))
    ]
    return points, {
        "line_id": line_id,
        "point_ids": [point["point_id"] for point in points],
        "attributes": {"pattern": pattern},
    }


def _recording(*lines: dict, points: list[dict]) -> dict:
    return {
        "recording_id": "synthetic",
        "ld_feature_store": {
            "points": points,
            "lane_lines": list(lines),
            "road_boundaries": [],
        },
        "frames": [
            {
                "frame_index": 10,
                "ego": {"position_lcs_m": [0.0, 0.0, 0.0], "heading_lcs_rad": 0.0},
                "ld": {
                    "nearby_feature_ids": {
                        "lane_lines": [line["line_id"] for line in lines],
                        "road_boundaries": [],
                    }
                },
            }
        ],
    }


def _polyline(line_id: str, values: list[tuple[float, float]], *, point_start: int = 0) -> tuple[list[dict], dict]:
    points = [
        {"point_id": f"p{point_start + index}", "position_lcs_m": [x, y, 0.0]}
        for index, (x, y) in enumerate(values)
    ]
    return points, {
        "line_id": line_id,
        "point_ids": [point["point_id"] for point in points],
        "attributes": {"pattern": "solid"},
    }


def test_bev_lane_poc_detects_ego_and_adjacent_lanes() -> None:
    all_points = []
    lines = []
    for index, (line_id, lateral) in enumerate(
        [("outer_left", 5.25), ("left", 1.75), ("right", -1.75), ("outer_right", -5.25)]
    ):
        points, line = _line(line_id, lateral, point_start=index * 100)
        all_points.extend(points)
        lines.append(line)
    recording = _recording(*lines, points=all_points)

    result = run_frame(recording, recording["frames"][0], load_config(overrides={"feature_enabled": True}))

    assert result["status"] == "matched"
    assert result["ego_lane"]["boundary_ids"] == {"left": "left", "right": "right"}
    assert result["left_adjacent"]["exists"] is True
    assert result["right_adjacent"]["exists"] is True
    assert result["ego_lane"]["polygon_bev_m"]
    assert result["ego_lane"]["polygon_lcs_m"]


def test_virtual_lines_are_not_used_for_bev_assignment() -> None:
    all_points = []
    lines = []
    for index, (line_id, lateral, pattern) in enumerate(
        [("virtual_left", 1.75, "virtual"), ("right", -1.75, "solid")]
    ):
        points, line = _line(line_id, lateral, pattern=pattern, point_start=index * 100)
        all_points.extend(points)
        lines.append(line)
    recording = _recording(*lines, points=all_points)

    result = run_frame(recording, recording["frames"][0], load_config(overrides={"feature_enabled": True}))

    assert result["status"] == "unmatched"
    assert result["ego_lane"]["exists"] is False
    assert result["candidate_lanes"] == []


def test_duplicate_bev_candidates_are_suppressed() -> None:
    all_points = []
    lines = []
    for index, (line_id, lateral) in enumerate(
        [("left", 1.75), ("left_duplicate", 1.78), ("right", -1.75)]
    ):
        points, line = _line(line_id, lateral, point_start=index * 100)
        all_points.extend(points)
        lines.append(line)
    recording = _recording(*lines, points=all_points)
    config = load_config(
        overrides={
            "feature_enabled": True,
            "minimum_lane_width_m": 2.0,
            "deduplicate_centerline_distance_m": 1.0,
            "deduplicate_lateral_distance_m": 1.0,
        }
    )

    result = run_frame(recording, recording["frames"][0], config)

    assert len(result["candidate_lanes"]) == 1
    assert result["rejections"]["duplicates"]
    assert result["rejections"]["duplicates"][0]["reasons"] == ["duplicate_bev_lane_candidate"]


def test_lane_extension_bridges_longitudinal_fragment_gap_for_pairing() -> None:
    left_points, left = _polyline(
        "left",
        [(float(x), 1.75) for x in range(0, 21, 5)],
        point_start=0,
    )
    right_points, right = _polyline(
        "right",
        [(float(x), -1.75) for x in range(30, 51, 5)],
        point_start=100,
    )
    recording = _recording(left, right, points=left_points + right_points)
    recording["frames"][0]["ego"]["position_lcs_m"] = [25.0, 0.0, 0.0]
    config = load_config(
        overrides={
            "feature_enabled": True,
            "extend_lane_boundaries": True,
            "lane_extension_forward_m": 18.0,
            "lane_extension_backward_m": 18.0,
            "minimum_longitudinal_overlap_m": 10.0,
        }
    )

    result = run_frame(recording, recording["frames"][0], config)

    assert result["status"] == "matched"
    assert result["ego_lane"]["exists"] is True
    assert any(item["extended"] for item in result["lane_extension"]["boundaries"])


def test_lane_extension_can_follow_curvature() -> None:
    config = load_config(
        overrides={
            "extend_lane_boundaries": True,
            "lane_extension_forward_m": 10.0,
            "lane_extension_backward_m": 0.0,
            "lane_extension_step_m": 2.5,
            "lane_extension_allow_curvature": True,
            "lane_extension_max_heading_change_deg": 60.0,
            "lane_extension_max_lateral_drift_m": 8.0,
        }
    )
    boundary = Boundary(
        "curved",
        tuple((float(x), 0.01 * x * x) for x in range(0, 21, 5)),
    )

    extended, debug = extend_boundaries([boundary], config)

    assert debug[0]["extended"] is True
    assert len(extended[0].points) > len(boundary.points)
    last_source = boundary.points[-1]
    last_extended = extended[0].points[-1]
    linear_projection = last_source[1] + 0.35 * (last_extended[0] - last_source[0])
    assert last_extended[1] > linear_projection


def test_disabled_recording_is_noop() -> None:
    result = run_recording({"recording_id": "unused", "frames": []}, load_config())

    assert result["status"] == "disabled"
    assert result["frames"] == []


def test_cli_json_shape_is_serializable() -> None:
    all_points = []
    lines = []
    for index, (line_id, lateral) in enumerate([("left", 1.75), ("right", -1.75)]):
        points, line = _line(line_id, lateral, point_start=index * 100)
        all_points.extend(points)
        lines.append(line)
    recording = _recording(*lines, points=all_points)
    result = run_recording(recording, load_config(overrides={"feature_enabled": True}), frame_indices={10})

    assert json.loads(json.dumps(result))["schema_version"] == "bev-lane-poc-v1"
