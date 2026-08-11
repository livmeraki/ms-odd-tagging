from ms_odd_tagging.simplified_taxonomy import map_scenario_labels


def test_maps_lane_keeping_with_lead_and_speed():
    result = map_scenario_labels(
        ["following_lane_with_lead", "medium_magnitude_speed"]
    ).to_dict()

    assert result["ego_maneuver"] == {"type": "lane_keeping", "direction": None}
    assert result["traffic_relation"]["lead"] == "present"
    assert result["ego_motion"]["speed_band"] == "medium"


def test_maps_turn_and_intersection_context():
    result = map_scenario_labels(
        ["starting_left_turn", "on_traffic_light_intersection"]
    ).to_dict()

    assert result["ego_motion"]["state"] == "starting"
    assert result["ego_maneuver"] == {"type": "turn", "direction": "left"}
    assert result["road_context"]["intersection"] == "yes"
    assert result["road_context"]["traffic_light_intersection"] == "yes"


def test_preserves_unknown_and_reports_unmapped_labels():
    result = map_scenario_labels(["some_future_scenario"]).to_dict()

    assert result["ego_motion"]["state"] == "unknown"
    assert result["ego_maneuver"]["type"] == "unknown"
    assert result["unmapped_scenarios"] == ["some_future_scenario"]


def test_interaction_tags_are_parallel_not_maneuver_overrides():
    result = map_scenario_labels(
        ["following_lane_without_lead", "waiting_for_pedestrian_to_cross"]
    ).to_dict()

    assert result["ego_maneuver"]["type"] == "lane_keeping"
    assert result["traffic_relation"]["lead"] == "absent"
    assert result["interaction_tags"] == ["waiting_for_pedestrian_to_cross"]
