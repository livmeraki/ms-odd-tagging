import math

from ms_odd_tagging.scenarios.following_lane.detector import run_following_lane, segment_states
from ms_odd_tagging.scenarios.following_lane.lane_geometry import (
    LaneGeometry,
    adjacent_lanes,
    assign_point_to_lane,
    assign_point_to_probable_route,
    assign_point_to_probable_bridge,
    build_probable_route_bridges,
    build_lane_geometries,
    build_logical_lane_groups,
    lane_centerline_heading_variation_deg,
    refine_groups_from_observed_ego_path,
    split_adjacent_roles,
)


def synthetic_recording(speeds=(10.0,), object_frames=None):
    points = []
    lines = []
    lanes = []
    for lane_index, (lane_id, low, high) in enumerate((("left", 2.0, 6.0), ("ego", -2.0, 2.0), ("right", -6.0, -2.0))):
        left_id, right_id = f"{lane_id}-left", f"{lane_id}-right"
        for edge_id, lateral in ((left_id, high), (right_id, low)):
            ids = [f"{edge_id}-0", f"{edge_id}-1"]
            points.extend([
                {"point_id": ids[0], "position_lcs_m": [0.0, lateral, 0.0]},
                {"point_id": ids[1], "position_lcs_m": [100.0, lateral, 0.0]},
            ])
            lines.append({"line_id": edge_id, "elements": [{"point_id": ids[0], "order": 0}, {"point_id": ids[1], "order": 1}]})
        lanes.append({
            "lane_id": lane_id,
            "boundaries": {
                "left": {"edge_id": left_id, "start_order": 0, "end_order": 1, "edge_reference_valid": True, "endpoint_order_valid": True},
                "right": {"edge_id": right_id, "start_order": 0, "end_order": 1, "edge_reference_valid": True, "endpoint_order_valid": True},
            },
            "validity": {"boundary_ranges_valid": True},
        })
    frames = []
    object_frames = object_frames or {}
    for index, speed in enumerate(speeds):
        objects = []
        for obj in object_frames.get(index, []):
            objects.append({
                "object_id": obj.get("object_id", "lead"), "class": obj.get("class", "car"),
                "annotation_type": obj.get("annotation_type", "dynamic"),
                "position_lcs_m": [obj["x"], obj["y"], 0.0],
                "position_ego_m": {"longitudinal": obj["x"] - index, "lateral": obj["y"]},
            })
        frames.append({
            "frame_index": index, "timestamp_unix_s": 1000.0 + index * 0.1,
            "time_since_start_s": index * 0.1,
            "ego": {"position_lcs_m": [float(index), 0.0, 0.0], "heading_lcs_rad": 0.0, "speed_mps": speed},
            "objects": objects,
            "ld": {"nearby_feature_ids": {"lanes": ["left", "ego", "right"]}},
        })
    return {"recording_id": "synthetic", "ld_feature_store": {"points": points, "lane_lines": lines, "road_boundaries": [], "lanes": lanes, "topologies": []}, "frames": frames}


def test_lane_assignment_and_adjacent_lane_roles():
    recording = synthetic_recording()
    lanes, _ = build_lane_geometries(recording)
    assignment = assign_point_to_lane((10.0, 0.0), 0.0, lanes, lanes)
    assert assignment["lane_id"] == "ego"
    result = run_following_lane(recording)
    frame = result["frames"][0]
    assert frame["ego_lane"]["lane_id"] == "ego"
    assert frame["left_lane"]["lane_id"] == "left"
    assert frame["right_lane"]["lane_id"] == "right"
    assert frame["left_lane"]["same_direction_as_ego"] is True
    assert frame["right_lane"]["same_direction_as_ego"] is True
    assert frame["left_lane"]["heading_difference_deg"] == 0.0


def test_crossing_and_opposite_lanes_are_not_adjacent_travel_lanes():
    def lane(lane_id, centerline):
        left = tuple((x, y + 1.5) for x, y in centerline)
        right = tuple((x, y - 1.5) for x, y in centerline)
        return LaneGeometry(
            lane_id,
            f"{lane_id}-left",
            f"{lane_id}-right",
            left,
            right,
            tuple(centerline),
            left + tuple(reversed(right)),
            True,
            None,
            {},
            {},
            "explicitly_drivable",
            False,
            (),
        )

    lanes = {
        "ego": lane("ego", ((0.0, 0.0), (20.0, 0.0))),
        "roundabout": lane("roundabout", ((8.0, 2.0), (12.0, 7.0))),
        "oncoming": lane("oncoming", ((20.0, -4.0), (0.0, -4.0))),
    }
    roles = adjacent_lanes(
        "ego",
        (10.0, 0.0),
        0.0,
        lanes,
        lanes,
        maximum_same_direction_heading_difference_deg=35.0,
    )

    assert roles["left"]["lane_id"] is None
    assert roles["left"]["rejected_lane_id"] == "roundabout"
    assert roles["left"]["same_direction_as_ego"] is False
    assert roles["left"]["direction_relation"] == "crossing_or_diverging"
    assert roles["right"]["lane_id"] is None
    assert roles["right"]["rejected_lane_id"] == "oncoming"
    assert roles["right"]["direction_relation"] == "opposite_direction"


def test_reverse_boundary_range_includes_first_edge_element():
    recording = synthetic_recording()
    ego_lane = next(
        lane for lane in recording["ld_feature_store"]["lanes"]
        if lane["lane_id"] == "ego"
    )
    ego_lane["boundaries"]["right"].update({
        "start_order": 1,
        "end_order": 0,
    })

    lanes, _ = build_lane_geometries(recording)
    assignment = assign_point_to_lane((10.0, 0.0), 0.0, ["ego"], lanes)

    assert lanes["ego"].assignment_valid is True
    assert len(lanes["ego"].right) == 2
    # Geometry construction may normalize the extracted boundary direction to
    # match the opposite edge; both inclusive endpoints must still be present.
    assert set(lanes["ego"].right) == {(0.0, -2.0), (100.0, -2.0)}
    assert assignment["lane_id"] == "ego"


def test_following_lane_lead_track_is_held_through_short_detection_gap():
    recording = synthetic_recording(
        speeds=(10.0, 10.0, 10.0),
        object_frames={1: [{"x": 30.0, "y": 0.0}]},
    )
    result = run_following_lane(recording)
    assert [frame["state"] for frame in result["frames"]] == [
        "following_lane_without_lead", "following_lane_with_lead", "following_lane_with_lead"
    ]
    assert result["frames"][2]["lead"]["tracking_status"] == "held_through_missing_observation"
    assert [interval["frame_count"] for interval in result["intervals"]] == [1, 2]


def test_invalid_speed_and_stationary_break_intervals():
    result = run_following_lane(synthetic_recording(speeds=(10.0, None, math.nan, 0.49, 10.0)))
    assert [frame["state"] for frame in result["frames"]] == [
        "following_lane_without_lead", "unknown", "unknown", "not_applicable", "following_lane_without_lead"
    ]
    assert [(item["start_frame_index"], item["end_frame_index"]) for item in result["intervals"]] == [(0, 0), (4, 4)]


def test_intervals_use_inclusive_observed_frame_boundaries():
    frames = [
        {"frame_index": index, "timestamp_unix_s": 50.0 + index * 0.2, "time_since_start_s": index * 0.2, "state": state}
        for index, state in enumerate(("following_lane_without_lead", "following_lane_without_lead", "following_lane_with_lead", "following_lane_with_lead", "following_lane_with_lead"))
    ]
    intervals = segment_states(frames)
    assert intervals[0]["start_frame_index"] == 0 and intervals[0]["end_frame_index"] == 1
    assert intervals[1]["start_frame_index"] == 2 and intervals[1]["end_frame_index"] == 4
    assert intervals[1]["frame_count"] == 3
    assert all(item["boundary_convention"] == "inclusive_observed_frames" for item in intervals)
    assert intervals[0]["end_timestamp_unix_s"] < intervals[1]["start_timestamp_unix_s"]


def test_mutual_continuation_merges_segments_without_merging_parallel_lane():
    def lane(lane_id, start, end, lateral):
        center = ((start, lateral), (end, lateral))
        return LaneGeometry(
            lane_id, f"{lane_id}-left", f"{lane_id}-right",
            ((start, lateral + 2), (end, lateral + 2)),
            ((start, lateral - 2), (end, lateral - 2)), center,
            ((start, lateral + 2), (end, lateral + 2), (end, lateral - 2), (start, lateral - 2)),
            True, None, {}, {}, "explicitly_drivable", False, (),
        )
    lanes = {
        "a": lane("a", 0.0, 20.0, 0.0),
        "b": lane("b", 20.2, 40.0, 0.0),
        "parallel": lane("parallel", 0.0, 40.0, 4.0),
    }
    groups = build_logical_lane_groups(lanes, [])
    assert groups["a"] == groups["b"]
    assert groups["a"] != groups["parallel"]


def test_intersection_line_attribute_is_preserved_as_lane_evidence():
    recording = synthetic_recording()
    recording["ld_feature_store"]["lane_lines"][2]["attributes"] = {"intersection": True, "pattern": "virtual"}
    lanes, _ = build_lane_geometries(recording)
    assert lanes["ego"].intersection_connector is True
    assert "left_boundary_attribute" in lanes["ego"].intersection_evidence


def test_explicit_non_drivable_boundary_excludes_lane_assignment():
    recording = synthetic_recording()
    recording["ld_feature_store"]["lane_lines"][2]["attributes"] = {"drivable": True}
    recording["ld_feature_store"]["lane_lines"][3]["attributes"] = {"drivable": False}
    lanes, _ = build_lane_geometries(recording)
    assert lanes["ego"].drivable_status == "explicitly_non_drivable"
    assignment = assign_point_to_lane((10.0, 0.0), 0.0, ["ego"], lanes)
    assert assignment["lane_id"] is None


def test_nearest_drivable_road_boundary_is_normalized_as_lane_line():
    recording = synthetic_recording()
    lines = recording["ld_feature_store"]["lane_lines"]
    road_edge = next(line for line in lines if line["line_id"] == "ego-right")
    recording["ld_feature_store"]["lane_lines"] = [
        line for line in lines if line["line_id"] != "ego-right"
    ]
    recording["ld_feature_store"]["road_boundaries"] = [
        {
            "road_boundary_id": "ego-right",
            "elements": road_edge["elements"],
            "boundary_attribute": "drivable",
            "attributes": {},
        }
    ]
    lanes, _ = build_lane_geometries(recording)
    assignment = assign_point_to_lane((10.0, -1.8), 0.0, ["ego"], lanes)
    assert assignment["lane_id"] == "ego"
    assert lanes["ego"].right_attributes["drivable"] is True
    assert lanes["ego"].right_attributes["pattern"] == "solid"
    assert assignment["nearest_boundary_source_kind"] == "road_boundary"
    assert assignment["nearest_boundary_attribute"] == "drivable"
    assert assignment["nearest_boundary_normalized_as_lane_line"] is True


def test_stale_endpoint_metadata_recovers_lane_from_physical_edges():
    recording = synthetic_recording()
    lines = recording["ld_feature_store"]["lane_lines"]
    road_edge = next(line for line in lines if line["line_id"] == "ego-right")
    recording["ld_feature_store"]["lane_lines"] = [
        line for line in lines if line["line_id"] != "ego-right"
    ]
    recording["ld_feature_store"]["road_boundaries"] = [{
        "road_boundary_id": "ego-right",
        "elements": road_edge["elements"],
        "boundary_attribute": "drivable",
        "attributes": {},
    }]
    ego_lane = next(
        lane for lane in recording["ld_feature_store"]["lanes"]
        if lane["lane_id"] == "ego"
    )
    ego_lane["boundaries"]["right"].update({
        "end_order": 99,
        "endpoint_order_valid": False,
        "geometry_fallback": "full_edge",
    })
    ego_lane["validity"]["boundary_ranges_valid"] = False

    lanes, _ = build_lane_geometries(recording)
    assignment = assign_point_to_lane((10.0, 0.0), 0.0, ["ego"], lanes)

    assert lanes["ego"].assignment_valid is True
    assert lanes["ego"].geometry_recovered is True
    assert lanes["ego"].recovery_method == "validated_aligned_full_edge_pair"
    assert lanes["ego"].recovery_evidence["recovered_sides"] == ["right"]
    assert assignment["lane_id"] == "ego"
    assert assignment["method"] == "recovered_physical_boundary_polygon_and_heading"
    assert assignment["confidence"] == "medium"
    assert assignment["virtual_boundary_count"] == 0


def test_short_physical_connector_recovers_with_stable_width():
    recording = synthetic_recording()
    ego_lane = next(
        lane for lane in recording["ld_feature_store"]["lanes"]
        if lane["lane_id"] == "ego"
    )
    ego_lane["boundaries"]["right"].update({
        "end_order": 99,
        "endpoint_order_valid": False,
        "geometry_fallback": "full_edge",
    })
    ego_lane["validity"]["boundary_ranges_valid"] = False
    for point in recording["ld_feature_store"]["points"]:
        if point["point_id"] == "ego-right-0":
            point["position_lcs_m"][0] = 96.0
        elif point["point_id"] == "ego-right-1":
            point["position_lcs_m"][0] = 200.0

    lanes, _ = build_lane_geometries(recording)
    assignment = assign_point_to_lane((98.0, 0.0), 0.0, ["ego"], lanes)

    assert lanes["ego"].assignment_valid is True
    assert lanes["ego"].geometry_recovered is True
    assert lanes["ego"].recovery_evidence["shared_longitudinal_overlap_m"] == 4.0
    assert assignment["lane_id"] == "ego"


def test_full_edge_recovery_rejects_implausible_lane_width():
    recording = synthetic_recording()
    ego_lane = next(
        lane for lane in recording["ld_feature_store"]["lanes"]
        if lane["lane_id"] == "ego"
    )
    ego_lane["boundaries"]["right"].update({
        "end_order": 99,
        "endpoint_order_valid": False,
        "geometry_fallback": "full_edge",
    })
    ego_lane["validity"]["boundary_ranges_valid"] = False
    for point in recording["ld_feature_store"]["points"]:
        if point["point_id"].startswith("ego-right-"):
            point["position_lcs_m"][1] = -10.0

    lanes, _ = build_lane_geometries(recording)

    assert lanes["ego"].assignment_valid is False
    assert lanes["ego"].geometry_recovered is False
    assert lanes["ego"].invalid_reason == "invalid_or_incomplete_boundary_range"


def test_full_edge_recovery_does_not_manufacture_lane_from_virtual_edge():
    recording = synthetic_recording()
    ego_lane = next(
        lane for lane in recording["ld_feature_store"]["lanes"]
        if lane["lane_id"] == "ego"
    )
    ego_lane["boundaries"]["left"].update({
        "end_order": 99,
        "endpoint_order_valid": False,
        "geometry_fallback": "full_edge",
    })
    ego_lane["validity"]["boundary_ranges_valid"] = False
    ego_left = next(
        line for line in recording["ld_feature_store"]["lane_lines"]
        if line["line_id"] == "ego-left"
    )
    ego_left["attributes"] = {"pattern": "virtual"}

    lanes, _ = build_lane_geometries(recording)

    assert lanes["ego"].assignment_valid is False
    assert lanes["ego"].geometry_recovered is False


def test_observed_directed_path_keeps_one_id_across_intersection_branch():
    def lane(lane_id, start, end, lateral=0.0):
        center = ((start, lateral), (end, lateral))
        return LaneGeometry(
            lane_id, None, None,
            ((start, lateral + 2), (end, lateral + 2)),
            ((start, lateral - 2), (end, lateral - 2)), center,
            ((start, lateral + 2), (end, lateral + 2), (end, lateral - 2), (start, lateral - 2)),
            True, None, {}, {}, "explicitly_drivable", False, (),
        )
    lanes = {
        "before": lane("before", 0.0, 20.0),
        "connector": lane("connector", 20.0, 30.0),
        "driven_branch": lane("driven_branch", 30.0, 50.0),
        "other_branch": lane("other_branch", 30.0, 50.0, 4.0),
    }
    topologies = [
        {"source_lane_id": "before", "destination_lane_id": "connector", "subclass": "intersection_in", "validity": {"lane_references_resolve": True}},
        {"source_lane_id": "connector", "destination_lane_id": "driven_branch", "subclass": "branch", "validity": {"lane_references_resolve": True}},
        {"source_lane_id": "connector", "destination_lane_id": "other_branch", "subclass": "branch", "validity": {"lane_references_resolve": True}},
    ]
    base = build_logical_lane_groups(lanes, topologies)
    refined = refine_groups_from_observed_ego_path(
        lanes, topologies, base, [(0, "before"), (1, "connector"), (2, "driven_branch")]
    )
    assert refined["before"] == refined["connector"] == refined["driven_branch"]
    assert refined["other_branch"] != refined["driven_branch"]


def test_first_observed_lane_selects_only_its_upstream_branch():
    def lane(lane_id, start, end, lateral=0.0):
        center = ((start, lateral), (end, lateral))
        return LaneGeometry(
            lane_id, None, None,
            ((start, lateral + 2), (end, lateral + 2)),
            ((start, lateral - 2), (end, lateral - 2)), center,
            ((start, lateral + 2), (end, lateral + 2), (end, lateral - 2), (start, lateral - 2)),
            True, None, {}, {}, "explicitly_drivable", False, (),
        )
    lanes = {
        "upstream": lane("upstream", 0.0, 20.0),
        "connector": lane("connector", 20.0, 30.0),
        "observed": lane("observed", 45.0, 65.0),
        "sibling": lane("sibling", 45.0, 65.0, 4.0),
    }
    topologies = [
        {"source_lane_id": "upstream", "destination_lane_id": "connector"},
        {"source_lane_id": "connector", "destination_lane_id": "observed"},
        {"source_lane_id": "connector", "destination_lane_id": "sibling"},
    ]
    base = {lane_id: f"base-{lane_id}" for lane_id in lanes}

    refined = refine_groups_from_observed_ego_path(
        lanes, topologies, base, [(100, "observed")]
    )

    assert refined["upstream"] == refined["connector"] == refined["observed"]
    assert refined["sibling"] != refined["observed"]


def test_probable_route_corridor_extends_endpoint_but_respects_lane_width():
    recording = synthetic_recording()
    lanes, _ = build_lane_geometries(recording)
    groups = {lane_id: f"route-{lane_id}" for lane_id in lanes}
    inside_extension = assign_point_to_probable_route(
        (110.0, 0.2), 0.0, "route-ego", lanes, groups, maximum_extension_m=15.0
    )
    outside_width = assign_point_to_probable_route(
        (110.0, 8.0), 0.0, "route-ego", lanes, groups, maximum_extension_m=15.0
    )
    assert inside_extension is not None
    assert inside_extension["confidence"] == "probable"
    assert inside_extension["extension_distance_m"] == 10.0
    assert outside_width is None


def test_left_split_role_and_lane_aligned_gap_bridge():
    def lane(lane_id, points, lateral=0.0):
        center = tuple((x, y + lateral) for x, y in points)
        left = tuple((x, y + lateral + 2.0) for x, y in points)
        right = tuple((x, y + lateral - 2.0) for x, y in points)
        return LaneGeometry(
            lane_id, None, None, left, right, center,
            left + tuple(reversed(right)), True, None, {}, {},
            "explicitly_drivable", False, (),
        )
    lanes = {
        "source": lane("source", [(0.0, 0.0), (20.0, 0.0)]),
        "straight": lane("straight", [(20.0, 0.0), (35.0, 0.0)]),
        "left_branch": lane("left_branch", [(20.0, 0.5), (35.0, 5.0)]),
        "after_gap": lane("after_gap", [(45.0, 0.0), (60.0, 0.0)]),
    }
    topologies = [
        {"source_lane_id": "source", "destination_lane_id": "straight", "subclass": "type_transition"},
        {"source_lane_id": "source", "destination_lane_id": "left_branch", "subclass": "branch"},
    ]
    groups = {
        "source": "route-main", "straight": "route-main",
        "after_gap": "route-main", "left_branch": "route-left",
    }
    roles = split_adjacent_roles("source", (18.0, 0.0), lanes, topologies, groups)
    bridges = build_probable_route_bridges(lanes, groups)
    assert roles["left"]["lane_id"] == "left_branch"
    assert roles["left"]["method"] == "topology_split_signed_direction"
    assert any(
        item["source_lane_id"] == "straight" and item["destination_lane_id"] == "after_gap"
        for item in bridges
    )


def test_validated_bridge_assigns_without_temporal_gate():
    def lane(lane_id, start, end):
        center = ((start, 0.0), (end, 0.0))
        left = ((start, 2.0), (end, 2.0))
        right = ((start, -2.0), (end, -2.0))
        return LaneGeometry(
            lane_id, None, None, left, right, center,
            left + tuple(reversed(right)), True, None, {}, {},
            "explicitly_drivable", False, (),
        )
    lanes = {
        "before": lane("before", 0.0, 20.0),
        "after": lane("after", 30.0, 50.0),
    }
    groups = {"before": "route-main", "after": "route-main"}
    bridges = build_probable_route_bridges(lanes, groups)

    assignment = assign_point_to_probable_bridge(
        (25.0, 0.0), 0.0, bridges, lanes,
        preferred_logical_lane_id="route-main",
    )
    wrong_heading = assign_point_to_probable_bridge(
        (25.0, 0.0), math.pi, bridges, lanes,
        preferred_logical_lane_id="route-main",
    )

    assert assignment is not None
    assert assignment["confidence"] == "probable"
    assert assignment["method"] == "inside_directed_lane_boundary_bridge"
    assert assignment["inside_probable_bridge"] is True
    assert wrong_heading is None


def test_lead_outside_exact_polygon_and_gap_bridge_is_rejected():
    recording = synthetic_recording(
        speeds=(10.0,),
        object_frames={0: [{"x": 60.0, "y": 0.0}]},
    )
    for point in recording["ld_feature_store"]["points"]:
        if point["point_id"].endswith("-1"):
            point["position_lcs_m"][0] = 50.0
    result = run_following_lane(recording)
    assert result["frames"][0]["lead"] is None
    assert result["frames"][0]["state"] == "following_lane_without_lead"


def test_curved_virtual_lane_is_rejected_but_straight_virtual_lane_remains_fallback():
    def lane(lane_id, center, pattern):
        left = tuple((x, y + 2.0) for x, y in center)
        right = tuple((x, y - 2.0) for x, y in center)
        attributes = {"source_kind": "lane_line", "pattern": pattern, "drivable": True}
        return LaneGeometry(
            lane_id, f"{lane_id}-left", f"{lane_id}-right",
            left, right, tuple(center), left + tuple(reversed(right)),
            True, None, attributes, attributes,
            "explicitly_drivable", False, (),
        )

    curved = lane("curved", ((0.0, 0.0), (5.0, 0.0), (8.0, 3.0), (8.0, 8.0)), "virtual")
    straight = lane("straight", ((0.0, 0.0), (5.0, 0.0), (10.0, 0.0)), "virtual")
    assignment = assign_point_to_lane(
        (1.0, 0.0), 0.0, ["curved", "straight"],
        {"curved": curved, "straight": straight},
        maximum_virtual_lane_curvature_deg=25.0,
    )

    assert lane_centerline_heading_variation_deg(curved) > 25.0
    assert assignment["lane_id"] == "straight"
    assert assignment["boundary_reliability"] == "virtual_only"
    assert assignment["confidence"] == "medium"


def test_dashed_and_drivable_boundary_evidence_beats_straight_virtual_polygon():
    center = ((0.0, 0.0), (20.0, 0.0))
    left = ((0.0, 2.0), (20.0, 2.0))
    right = ((0.0, -2.0), (20.0, -2.0))
    polygon = left + tuple(reversed(right))
    virtual_attributes = {"source_kind": "lane_line", "pattern": "virtual", "drivable": True}
    dashed_attributes = {"source_kind": "lane_line", "pattern": "dashed", "drivable": True}
    boundary_attributes = {
        "source_kind": "road_boundary",
        "pattern": "solid",
        "boundary_attribute": "drivable",
        "drivable": True,
        "normalized_as_lane_line": True,
    }
    lanes = {
        "virtual": LaneGeometry(
            "virtual", "v-left", "v-right", left, right, center, polygon,
            True, None, virtual_attributes, virtual_attributes,
            "explicitly_drivable", False, (),
        ),
        "grounded": LaneGeometry(
            "grounded", "dashed", "boundary", left, right, center, polygon,
            True, None, dashed_attributes, boundary_attributes,
            "explicitly_drivable", False, (),
        ),
    }

    assignment = assign_point_to_lane((5.0, 0.0), 0.0, lanes, lanes)

    assert assignment["lane_id"] == "grounded"
    assert assignment["boundary_reliability"] == "dashed_with_drivable_road_boundary"
    assert assignment["boundary_evidence_score_adjustment"] < 0.0
