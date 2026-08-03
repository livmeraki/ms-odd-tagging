from __future__ import annotations

import math

from ms_odd_tagging.ld_topology.pipeline import classify_recording, classify_scene


def _recording(lanes_spec, frames=None):
    points, lane_lines, road_boundaries, lanes = [], [], [], []
    point_id = 1

    def add_edge(edge_id, pts, intersection=False, kind="line"):
        nonlocal point_id
        elems = []
        dense = []
        for a, b in zip(pts, pts[1:]):
            if not dense:
                dense.append(a)
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            steps = max(1, math.ceil(length / 8.0))
            for step in range(1, steps + 1):
                ratio = step / steps
                dense.append((a[0] + ratio * (b[0] - a[0]), a[1] + ratio * (b[1] - a[1])))
        for order, (x, y) in enumerate(dense or pts, start=1):
            pid = str(point_id)
            point_id += 1
            points.append({"point_id": pid, "position_lcs_m": [x, y, 0.0]})
            elems.append({"point_id": pid, "order": order})
        if kind == "line":
            lane_lines.append(
                {
                    "line_id": edge_id,
                    "elements": elems,
                    "point_ids": [e["point_id"] for e in elems],
                    "attributes": {"intersection": intersection},
                }
            )
        else:
            road_boundaries.append(
                {
                    "road_boundary_id": edge_id,
                    "elements": elems,
                    "point_ids": [e["point_id"] for e in elems],
                    "attributes": {},
                    "boundary_attribute": "drivable",
                }
            )
        return len(elems)

    for index, spec in enumerate(lanes_spec):
        left_id = f"l{index}"
        right_id = f"r{index}"
        left_count = add_edge(left_id, spec["left"], spec.get("left_i", False), spec.get("left_kind", "line"))
        right_count = add_edge(right_id, spec["right"], spec.get("right_i", False), spec.get("right_kind", "line"))
        left_start, left_end = spec.get("left_range", (1, left_count))
        right_start, right_end = spec.get("right_range", (1, right_count))
        lanes.append(
            {
                "lane_id": f"lane{index}",
                "boundaries": {
                    "left": {"edge_id": left_id, "start_order": left_start, "end_order": left_end},
                    "right": {"edge_id": right_id, "start_order": right_start, "end_order": right_end},
                },
            }
        )
    return {
        "recording_id": "synthetic",
        "ld_feature_store": {
            "points": points,
            "lane_lines": lane_lines,
            "road_boundaries": road_boundaries,
            "lanes": lanes,
        },
        "frames": frames or [_frame(0, 0.0, 0.0)],
    }


def _frame(index, x, y, yaw=0.0):
    return {
        "frame_index": index,
        "timestamp_unix_s": index * 0.1,
        "ego": {"position_lcs_m": [x, y, 0.0], "heading_lcs_rad": yaw},
    }


def _lane(start, end, width=4.0, intersection=True, left_kind="line", right_kind="line", left_i=None, right_i=None):
    sx, sy = start
    ex, ey = end
    length = math.hypot(ex - sx, ey - sy)
    nx, ny = -(ey - sy) / length * width / 2.0, (ex - sx) / length * width / 2.0
    return {
        "left": [(sx + nx, sy + ny), (ex + nx, ey + ny)],
        "right": [(sx - nx, sy - ny), (ex - nx, ey - ny)],
        "left_i": intersection if left_i is None else left_i,
        "right_i": intersection if right_i is None else right_i,
        "left_kind": left_kind,
        "right_kind": right_kind,
    }


def _point_between(start, end, ratio):
    return (start[0] + (end[0] - start[0]) * ratio, start[1] + (end[1] - start[1]) * ratio)


def _road_with_transition(start, end, width=4.0, core_start=0.35, core_end=0.65):
    a = _point_between(start, end, core_start)
    b = _point_between(start, end, core_end)
    return [
        _lane(start, a, width=width, intersection=False),
        _lane(a, b, width=width, intersection=True),
        _lane(b, end, width=width, intersection=False),
    ]


def _branch_with_transition(outer, inner, width=4.0, core_ratio=0.72):
    a = _point_between(outer, inner, core_ratio)
    return [
        _lane(outer, a, width=width, intersection=False),
        _lane(a, inner, width=width, intersection=True),
    ]


def _class_for(specs, frames=None):
    result = classify_recording(_recording(specs, frames))
    return result["frames"][0], result


def test_normal_parallel_road():
    frame, _ = _class_for([_lane((-30, 0), (30, 0), intersection=False)])
    assert frame["topology_class"] == "normal"
    assert frame["arm_count"] == 0


def test_simple_lane_split_remains_normal_without_intersection_marking():
    specs = [
        _lane((-30, 0), (0, 0), intersection=False),
        _lane((0, 0), (30, 8), intersection=False),
        _lane((0, 0), (30, -8), intersection=False),
    ]
    frame, _ = _class_for(specs)
    assert frame["topology_class"] == "normal"


def test_four_arm_perpendicular_x_intersection():
    specs = [
        *_road_with_transition((-30, 0), (30, 0)),
        *_road_with_transition((0, -30), (0, 30)),
    ]
    frame, _ = _class_for(specs)
    assert frame["topology_class"] == "x-intersection"
    assert frame["arm_count"] == 4


def test_skewed_four_arm_x_intersection():
    specs = [
        *_road_with_transition((-30, -5), (30, 5)),
        *_road_with_transition((-8, 30), (8, -30)),
    ]
    frame, _ = _class_for(specs)
    assert frame["topology_class"] == "x-intersection"


def test_three_arm_t_intersection():
    specs = [
        *_road_with_transition((-30, 0), (30, 0)),
        *_branch_with_transition((0, -30), (0, 0)),
    ]
    frame, _ = _class_for(specs)
    assert frame["topology_class"] == "t-intersection"
    assert frame["arm_count"] == 3


def test_curved_t_intersection():
    curved = _lane((0, -8), (0, 0))
    curved["left"] = [(-2, -8), (-4, -4), (-2, 2)]
    curved["right"] = [(2, -8), (4, -4), (2, 2)]
    specs = [
        *_road_with_transition((-30, 0), (30, 0)),
        _lane((0, -30), (0, -8), intersection=False),
        curved,
    ]
    frame, _ = _class_for(specs)
    assert frame["topology_class"] == "t-intersection"


def test_balanced_y_intersection():
    specs = [
        *_branch_with_transition((0, -30), (0, 0)),
        *_branch_with_transition((-24, 24), (0, 0)),
        *_branch_with_transition((24, 24), (0, 0)),
    ]
    frame, _ = _class_for(specs)
    assert frame["topology_class"] == "y-intersection"


def test_asymmetric_y_intersection():
    specs = [
        *_branch_with_transition((0, -30), (0, 0)),
        *_branch_with_transition((-30, 18), (0, 0)),
        *_branch_with_transition((18, 30), (0, 0)),
    ]
    frame, _ = _class_for(specs)
    assert frame["topology_class"] == "y-intersection"


def test_roundabout_with_four_approaches():
    circle_left, circle_right = [], []
    for i in range(33):
        a = 2 * math.pi * i / 32
        circle_left.append((8 * math.cos(a), 8 * math.sin(a)))
        circle_right.append((4 * math.cos(a), 4 * math.sin(a)))
    ring = {"left": circle_left, "right": circle_right, "left_i": True, "right_i": True}
    specs = [
        ring,
        _lane((-45, 0), (-30, 0), intersection=False),
        _lane((-30, 0), (-8, 0)),
        _lane((8, 0), (30, 0)),
        _lane((30, 0), (45, 0), intersection=False),
        _lane((0, -45), (0, -30), intersection=False),
        _lane((0, -30), (0, -8)),
        _lane((0, 8), (0, 30)),
        _lane((0, 30), (0, 45), intersection=False),
    ]
    frame, _ = _class_for(specs, [_frame(0, 6, 0)])
    assert frame["topology_class"] == "roundabout"
    assert frame["arm_count"] >= 4


def test_partial_intersection_marking_on_one_boundary_counts():
    spec = _lane((-30, 0), (30, 0), left_i=True, right_i=False, right_kind="road_boundary")
    scene = classify_scene(_recording([spec]))
    lane = scene["lanes"][0]
    assert lane["left_boundary_intersection"] is True
    assert lane["right_boundary_intersection"] is False
    assert lane["intersection_evidence"] == "partial"


def test_intersection_fan_lane_allows_wider_width_range_than_normal_lane():
    wide_intersection = _lane((-10, 0), (10, 0), width=9.5, intersection=True)
    scene = classify_scene(_recording([wide_intersection]))
    assert scene["lanes"][0]["intersection_evidence"] == "strong"
    wide_normal = _lane((-10, 0), (10, 0), width=9.5, intersection=False)
    scene = classify_scene(_recording([wide_normal]))
    assert scene["lanes"] == []
    assert scene["parse"]["rejected_lanes"][0]["reasons"] == ["lane_too_wide"]


def test_post_expansion_merge_connects_nearby_partial_corridors():
    specs = [
        _lane((-24, 0), (-12, 0), intersection=True),
        _lane((-12, 0), (-0.3, 0), left_i=True, right_i=False),
        _lane((0.3, 0), (12, 0), left_i=True, right_i=False),
        _lane((12, 0), (24, 0), intersection=True),
    ]
    scene = classify_scene(_recording(specs))
    assert len(scene["components"]) == 1
    component = scene["components"][0]
    assert component["evidence_counts"] == {"strong": 2, "partial": 2, "none": 0}
    assert component["diagnostics"]["merged_component_ids"]


def test_multiple_parallel_lanes_grouped_as_one_arm_per_side():
    specs = [
        *_road_with_transition((-30, -2), (30, -2)),
        *_road_with_transition((-30, 2), (30, 2)),
        *_road_with_transition((0, -30), (0, 30)),
        *_road_with_transition((4, -30), (4, 30)),
    ]
    frame, _ = _class_for(specs)
    assert frame["topology_class"] == "x-intersection"
    assert frame["arm_count"] == 4


def test_fragmented_intersection_true_geometry_is_not_confident_topology():
    specs = [_lane((-50, 0), (-35, 0)), _lane((35, 0), (50, 0))]
    frame, result = _class_for(specs)
    assert frame["topology_class"] == "normal"
    assert len(result["components"]) == 2


def test_ego_approaching_but_outside_intersection_stays_normal():
    specs = [
        *_road_with_transition((-30, 0), (30, 0)),
        *_road_with_transition((0, -30), (0, 30)),
    ]
    frame, _ = _class_for(specs, [_frame(0, -28, 0)])
    assert frame["topology_class"] == "normal"
    assert frame["ego_inside_topology_polygon"] is False


def test_ego_inside_and_then_exiting_intersection():
    frames = [_frame(0, 0, 0), _frame(1, 7, 0), _frame(2, 30, 0)]
    specs = [
        *_road_with_transition((-30, 0), (30, 0)),
        *_road_with_transition((0, -30), (0, 30)),
    ]
    result = classify_recording(_recording(specs, frames))
    assert result["frames"][0]["topology_class"] == "x-intersection"
    assert result["frames"][1]["topology_class"] == "x-intersection"
    assert result["frames"][2]["topology_class"] == "normal"


def test_reversed_ranges_preserve_valid_referenced_geometry():
    spec = _lane((-30, 0), (30, 0))
    spec["left_range"] = (2, 1)
    spec["right_range"] = (2, 1)
    scene = classify_scene(_recording([spec]))
    lane = scene["lanes"][0]
    assert lane["geometry_source"]["left"]["reversed_range"] is True
    assert lane["validation"]["valid"] is True
