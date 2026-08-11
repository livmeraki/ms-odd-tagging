from ms_odd_tagging.simplified_taxonomy.manual_gt import build_review_rows, evaluate_gt


def _tags(state="moving", speed="medium", maneuver="lane_keeping", lead="present", interactions=None):
    return {
        "ego_motion": {"state": state, "speed_band": speed},
        "ego_maneuver": {"type": maneuver, "direction": None},
        "traffic_relation": {"lead": lead, "trail": "absent"},
        "road_context": {
            "intersection": "no",
            "traffic_light_intersection": "no",
            "traffic_light_relevant": "no",
            "on_stopline_crosswalk": "no",
        },
        "interaction_tags": interactions or [],
    }


def test_build_review_rows_samples_one_fps_from_ten_hz():
    doc = {"frames": [{"frame_index": i, "simplified_tags": _tags()} for i in range(25)]}
    rows = build_review_rows(doc, source_hz=10.0, sample_hz=1.0)
    assert [r["frame_index"] for r in rows] == [0, 10, 20]
    assert rows[0]["prediction"]["ego_motion"]["state"] == "moving"
    assert rows[0]["reviewed"] is False


def test_evaluate_gt_excludes_unknown_scalar_gt_and_scores_interactions():
    prediction = _tags(interactions=["near_multiple_vehicles"])
    gt = _tags(interactions=["near_multiple_vehicles"])
    gt["traffic_relation"]["trail"] = "unknown"
    doc = {"frames": [{"frame_index": 0, "prediction": prediction, "gt": gt, "reviewed": True}]}
    report = evaluate_gt(doc)
    assert report["reviewed_frames"] == 1
    assert report["scalar_fields"]["traffic_relation.lead"]["f1"] == 1.0
    # unknown GT is excluded rather than treated as a negative/error
    assert report["scalar_fields"]["traffic_relation.trail"]["tp"] == 0
    assert report["interaction_tags"]["near_multiple_vehicles"]["f1"] == 1.0


def test_wrong_scalar_prediction_counts_as_fp_and_fn():
    prediction = _tags(speed="high")
    gt = _tags(speed="medium")
    doc = {"frames": [{"prediction": prediction, "gt": gt, "reviewed": True}]}
    metric = evaluate_gt(doc)["scalar_fields"]["ego_motion.speed_band"]
    assert metric["tp"] == 0
    assert metric["fp"] == 1
    assert metric["fn"] == 1
    assert metric["f1"] == 0.0
