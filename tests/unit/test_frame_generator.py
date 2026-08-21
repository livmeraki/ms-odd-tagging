from __future__ import annotations

import json
from pathlib import Path

from ms_odd_tagging.frame_inputs import generator


def test_frame_metadata_describes_centered_bev(
    tmp_path: Path,
    monkeypatch,
) -> None:
    canonical = tmp_path / "rec_canonical_odld_frames.json"
    canonical.write_text(
        json.dumps(
            {
                "recording_id": "rec",
                "scenario_taxonomy": [],
                "ld_feature_store": {},
                "frames": [
                    {
                        "frame_index": 0,
                        "timestamp_unix_s": 1.0,
                        "time_since_start_s": 0.0,
                        "ego": {
                            "position_lcs_m": [0.0, 0.0, 0.0],
                            "heading_lcs_rad": 0.0,
                            "speed_mps": 0.0,
                        },
                        "objects": [],
                        "scenario_signals": {
                            "nearby_30m_counts": {
                                "pedestrian": 0,
                                "motorcycle": 0,
                            }
                        },
                        "interaction_candidates": [],
                        "ld": {"available": False},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        generator,
        "load_config",
        lambda: {
            "enabled_scenarios": [],
            "object_relations": {"generic_proximity_radius_m": 30.0},
            "object_path_crossing_interactions": {
                "arc_inner_radius_m": 2.0,
                "arc_outer_radius_m": 30.0,
                "arc_half_angle_deg": 30.0,
            },
        },
    )
    monkeypatch.setattr(generator, "detect_recording_events", lambda *_: ([], {}))
    monkeypatch.setattr(
        "ms_odd_tagging.scenarios.following_lane.detector.run_following_lane",
        lambda recording: {
            "recording_id": recording["recording_id"],
            "frames": [{"frame_index": 0, "state": "not_applicable"}],
        },
    )
    monkeypatch.setattr(
        generator,
        "render_bev_png",
        lambda *args, **kwargs: Path(args[2]).write_bytes(b"png"),
    )

    generator.build_recording(
        canonical,
        tmp_path / "out",
        extent=(45.0, 45.0, 25.0, 95.0),
        size=(320, 288),
        max_objects=80,
        frames_per_second=1.0,
    )

    frame = json.loads(
        (tmp_path / "out" / "rec" / "frame_000000" / "frame.json").read_text(
            encoding="utf-8"
        )
    )
    assert frame["bev"]["ego_position"] == "center"
    assert frame["bev"]["extent_m"] == {
        "left": 45.0,
        "right": 45.0,
        "behind": 60.0,
        "ahead": 60.0,
    }
    assert frame["bev"]["configured_extent_m"] == {
        "left": 45.0,
        "right": 45.0,
        "behind": 25.0,
        "ahead": 95.0,
    }
