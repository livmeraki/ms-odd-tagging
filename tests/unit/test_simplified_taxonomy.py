from ms_odd_tagging.simplified_taxonomy import map_scenario_labels
from ms_odd_tagging.simplified_taxonomy.exporter import convert_frame_document


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


def test_parallel_export_preserves_original_frame_fields():
    source = {
        "recording_id": "rec-1",
        "frames": [
            {
                "frame_index": 10,
                "timestamp": 1.0,
                "scenarios": ["following_lane_with_lead", "medium_magnitude_speed"],
                "existing_debug": {"keep": True},
            }
        ],
    }

    converted = convert_frame_document(source)
    frame = converted["frames"][0]

    assert source["frames"][0].get("simplified_tags") is None
    assert frame["frame_index"] == 10
    assert frame["existing_debug"] == {"keep": True}
    assert frame["scenarios"] == source["frames"][0]["scenarios"]
    assert frame["simplified_tags"]["ego_maneuver"]["type"] == "lane_keeping"
    assert frame["simplified_tags"]["traffic_relation"]["lead"] == "present"


def test_parallel_export_supports_tag_objects_and_tracks_unmapped():
    converted = convert_frame_document(
        [
            {
                "frame_index": 20,
                "tags": [
                    {"scenario": "on_intersection"},
                    {"name": "future_tag"},
                ],
            }
        ]
    )

    simplified = converted[0]["simplified_tags"]
    assert simplified["road_context"]["intersection"] == "yes"
    assert simplified["unmapped_scenarios"] == ["future_tag"]
