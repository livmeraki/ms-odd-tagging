from ms_odd_tagging.lanelet2_poc.config import load_config
from ms_odd_tagging.lanelet2_poc.models import Boundary
from ms_odd_tagging.lanelet2_poc.runner import run_frame, run_recording


def boundary(boundary_id, y):
    return Boundary(boundary_id, tuple((float(x), y) for x in range(-20, 81, 5)))


def test_runner_outputs_ids_polygons_confidence_and_neighbor_existence():
    config = load_config(overrides={"feature_enabled": True, "require_lanelet2": False})
    result = run_frame(
        [
            boundary("outer_left", 5.25),
            boundary("left", 1.75),
            boundary("right", -1.75),
            boundary("outer_right", -5.25),
        ],
        (0.0, 0.0, 0.0),
        config,
        frame_index=7,
    )

    assert result["status"] == "matched"
    assert result["frame_index"] == 7
    assert result["ego_lane"]["boundary_ids"] == {"left": "left", "right": "right"}
    assert result["ego_lane"]["polygon_lcs_m"]
    assert result["ego_lane"]["confidence"] > 0
    assert result["left_adjacent"]["exists"] is True
    assert result["right_adjacent"]["exists"] is True
    assert set(result["routing"]["queries"]) == {
        "left",
        "right",
        "adjacentLeft",
        "adjacentRight",
    }


def test_missing_outer_boundaries_returns_no_adjacent_lanes():
    config = load_config(overrides={"feature_enabled": True, "require_lanelet2": False})
    result = run_frame(
        [boundary("left", 1.75), boundary("right", -1.75)],
        (0.0, 0.0, 0.0),
        config,
    )

    assert result["ego_lane"]["exists"] is True
    assert result["left_adjacent"]["exists"] is False
    assert result["right_adjacent"]["exists"] is False


def test_invalid_ego_pose_is_structured_not_an_exception():
    config = load_config(overrides={"feature_enabled": True, "require_lanelet2": False})
    result = run_frame([], (float("nan"), 0.0, 0.0), config)
    assert result["status"] == "invalid_input"
    assert result["rejection_reasons"] == ["ego_pose_must_be_finite_x_y_yaw"]


def test_disabled_recording_call_is_a_noop():
    result = run_recording({"recording_id": "unused"}, load_config())
    assert result["status"] == "disabled"
    assert result["frames"] == []
