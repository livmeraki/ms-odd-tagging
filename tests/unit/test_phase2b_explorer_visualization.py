from __future__ import annotations

import json
import inspect
import math
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts" / "odld_explorer"
sys.path.insert(0, str(SCRIPT_DIR))

import generate_odld_dataset_explorers_w_scenario_tag as explorer  # noqa: E402

from ms_odd_tagging.tagger.rule_based.scenario_event import ScenarioEvent  # noqa: E402


def _index_row(recording: str) -> dict:
    return {
        "recording": recording,
        "file": f"{recording}_animated_odld_explorer.html",
        "frames": 4,
        "duration": 0.3,
        "objects": 1,
        "lines": 2,
        "boundaries": 1,
        "roadmarks": 1,
        "tagScenarios": 1,
        "tagEvents": 1,
        "tagScenarioList": ["stationary"],
        "topClasses": "car:1",
        "thumbnail": "<svg></svg>",
    }


def _write_manifest(output_dir: Path, rows: list[dict]) -> None:
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": explorer.MANIFEST_SCHEMA_VERSION,
                "index": "index.html",
                "recordings": rows,
            }
        ),
        encoding="utf-8",
    )


def _write_canonical(canonical_dir: Path, recording: str) -> None:
    (canonical_dir / f"{recording}_canonical_odld_frames.json").write_text(
        json.dumps({"recording_id": recording}), encoding="utf-8"
    )


def test_index_links_to_same_output_directory() -> None:
    page = explorer.index_html(
        [
            {
                "file": "sample_animated_odld_explorer.html",
                "thumbnail": "<svg></svg>",
                "recording": "sample",
                "frames": 4,
                "duration": 0.3,
                "objects": 1,
                "lines": 2,
                "boundaries": 1,
                "roadmarks": 1,
                "tagScenarios": 1,
                "tagEvents": 1,
                "tagScenarioList": ["stationary"],
                "topClasses": "car:1",
            }
        ]
    )
    assert 'href="sample_animated_odld_explorer.html"' in page
    assert "const INDEX_ROWS =" in page
    assert 'id="recordingSearch"' in page
    assert 'id="scenarioFilter"' in page
    assert 'id="sortField"' in page
    assert '<input type="checkbox" value="stationary">' in page
    assert "selectedScenarios.every" in page
    assert "dataset_scene_explorers_odld_w_scenario_tag/" not in page


def test_row_from_existing_explorer_payload(tmp_path: Path) -> None:
    output = tmp_path / "sample_animated_odld_explorer.html"
    data = {
        "summary": {
            "recording": "sample",
            "frames": 4,
            "durationSec": 0.3,
            "objects": 1,
            "classCounts": {"car": 1},
        },
        "trajectory": {"x": [0], "y": [0]},
        "objects": [],
        "ld": {
            "summary": {"laneLines": 2, "roadBoundaries": 1, "roadmarks": 1},
        },
        "tags": {"scenarios": ["stationary"], "events": [{"scenario": "stationary"}]},
    }
    output.write_text(
        f"<script>const DATA = {json.dumps(data)};\nconst x = 1;</script>",
        encoding="utf-8",
    )

    row = explorer.row_from_explorer(output)

    assert row["recording"] == "sample"
    assert row["file"] == output.name
    assert row["tagScenarios"] == 1
    assert row["tagEvents"] == 1
    assert row["tagScenarioList"] == ["stationary"]
    assert row["topClasses"] == "car:1"


def test_following_lane_intervals_are_added_to_scenario_tags() -> None:
    tags = {
        "available": True,
        "sourceKind": "canonical_per_frame_rule_events",
        "scenarios": ["stationary"],
        "events": [
            {
                "scenario": "stationary",
                "startFrame": 0,
                "endFrame": 4,
                "startTime": 0.0,
                "endTime": 0.4,
                "evidence": {},
            }
        ],
    }
    following = {
        "intervals": [
            {
                "scenario": "following_lane_with_lead",
                "start_frame_index": 5,
                "end_frame_index": 12,
                "start_time_since_start_s": 0.5,
                "end_time_since_start_s": 1.2,
                "frame_count": 8,
                "boundary_convention": "inclusive_observed_frames",
            },
            {
                "scenario": "following_lane_without_lead",
                "start_frame_index": 13,
                "end_frame_index": 20,
                "start_time_since_start_s": 1.3,
                "end_time_since_start_s": 2.0,
                "frame_count": 8,
                "boundary_convention": "inclusive_observed_frames",
            },
        ]
    }

    merged = explorer.add_following_lane_tags(tags, following)

    assert "following_lane_with_lead" in merged["scenarios"]
    assert "following_lane_without_lead" in merged["scenarios"]
    assert "generated_lane_tracker" in merged["sourceKind"]
    assert [
        event["scenario"]
        for event in merged["events"]
        if event.get("source") == "generated_lane_tracker"
    ] == ["following_lane_with_lead", "following_lane_without_lead"]


def test_write_explorer_atomically_publishes_after_injection(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "sample_animated_odld_explorer.html"
    seen = []

    monkeypatch.setattr(explorer, "scene_html", lambda data: "base")

    def inject(path: Path, canonical: dict) -> None:
        seen.append((path.name, output.exists()))
        path.write_text(path.read_text(encoding="utf-8") + "+injected", encoding="utf-8")

    monkeypatch.setattr(explorer, "inject_lane_tracker", inject)

    explorer.write_explorer_atomically(output, {}, {})

    assert seen == [(f".{output.name}.tmp", False)]
    assert output.read_text(encoding="utf-8") == "base+injected"
    assert not (tmp_path / f".{output.name}.tmp").exists()


def test_write_explorer_atomically_keeps_final_absent_on_injection_failure(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "sample_animated_odld_explorer.html"
    monkeypatch.setattr(explorer, "scene_html", lambda data: "base")
    monkeypatch.setattr(
        explorer,
        "inject_lane_tracker",
        lambda path, canonical: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    try:
        explorer.write_explorer_atomically(output, {}, {})
    except KeyboardInterrupt:
        pass

    assert not output.exists()
    assert (tmp_path / f".{output.name}.tmp").is_file()


def test_existing_rows_by_recording_reads_all_generated_explorers(tmp_path: Path) -> None:
    for recording in ("rec-a", "rec-b"):
        data = {
            "summary": {
                "recording": recording,
                "frames": 4,
                "durationSec": 0.3,
                "objects": 1,
                "classCounts": {"car": 1},
            },
            "trajectory": {"x": [0], "y": [0]},
            "objects": [],
            "ld": {
                "summary": {"laneLines": 2, "roadBoundaries": 1, "roadmarks": 1},
            },
            "tags": {"scenarios": [], "events": []},
        }
        (tmp_path / f"{recording}_animated_odld_explorer.html").write_text(
            f"<script>const DATA = {json.dumps(data)};\nconst x = 1;</script>",
            encoding="utf-8",
        )

    rows = explorer.existing_rows_by_recording(tmp_path)

    assert sorted(rows) == ["rec-a", "rec-b"]


def test_main_skip_reuses_existing_row_without_reparse(
    tmp_path: Path, monkeypatch
) -> None:
    canonical_dir = tmp_path / "canonical"
    output_dir = tmp_path / "explorers"
    canonical_dir.mkdir()
    output_dir.mkdir()
    recording = "sample"
    _write_canonical(canonical_dir, recording)
    (output_dir / explorer.explorer_output_name(recording)).write_text(
        "<html></html>", encoding="utf-8"
    )
    _write_manifest(output_dir, [_index_row(recording)])
    monkeypatch.setattr(
        explorer,
        "row_from_explorer",
        lambda path: (_ for _ in ()).throw(AssertionError("reparsed skipped explorer")),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_odld_dataset_explorers_w_scenario_tag.py",
            "--canonical-dir",
            str(canonical_dir),
            "--output-dir",
            str(output_dir),
            "--index-path",
            str(tmp_path / "index.html"),
        ],
    )

    explorer.main()

    assert (tmp_path / "index.html").is_file()
    assert (output_dir / "manifest.json").is_file()


def test_main_skip_check_does_not_parse_unrelated_explorers(
    tmp_path: Path, monkeypatch
) -> None:
    canonical_dir = tmp_path / "canonical"
    output_dir = tmp_path / "explorers"
    canonical_dir.mkdir()
    output_dir.mkdir()
    requested = "requested"
    unrelated = "unrelated"
    _write_canonical(canonical_dir, requested)
    for recording in (requested, unrelated):
        (output_dir / explorer.explorer_output_name(recording)).write_text(
            "<html></html>", encoding="utf-8"
        )
    _write_manifest(output_dir, [_index_row(requested), _index_row(unrelated)])
    parsed = []
    monkeypatch.setattr(
        explorer,
        "row_from_explorer",
        lambda path: parsed.append(path) or _index_row(path.name.split("_animated")[0]),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_odld_dataset_explorers_w_scenario_tag.py",
            "--canonical-dir",
            str(canonical_dir),
            "--output-dir",
            str(output_dir),
            "--index-path",
            str(tmp_path / "index.html"),
            requested,
        ],
    )

    explorer.main()

    assert parsed == []


def test_multiple_requested_recordings_do_one_final_index_rebuild(
    tmp_path: Path, monkeypatch
) -> None:
    canonical_dir = tmp_path / "canonical"
    output_dir = tmp_path / "explorers"
    canonical_dir.mkdir()
    output_dir.mkdir()
    for recording in ("rec-a", "rec-b", "rec-c"):
        _write_canonical(canonical_dir, recording)
        (output_dir / explorer.explorer_output_name(recording)).write_text(
            "<html></html>", encoding="utf-8"
        )
    _write_manifest(
        output_dir,
        [_index_row("rec-a"), _index_row("rec-b"), _index_row("rec-c")],
    )
    rebuild_calls = []
    monkeypatch.setattr(
        explorer,
        "rebuild_rows_from_outputs",
        lambda output, rows: rebuild_calls.append((output, sorted(rows))) or list(rows.values()),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_odld_dataset_explorers_w_scenario_tag.py",
            "--canonical-dir",
            str(canonical_dir),
            "--output-dir",
            str(output_dir),
            "--index-path",
            str(tmp_path / "index.html"),
            "rec-a",
            "rec-b",
        ],
    )

    explorer.main()

    assert len(rebuild_calls) == 1
    assert rebuild_calls[0][1] == ["rec-a", "rec-b", "rec-c"]


def test_index_write_happens_once_after_all_requested_recordings(
    tmp_path: Path, monkeypatch
) -> None:
    canonical_dir = tmp_path / "canonical"
    output_dir = tmp_path / "explorers"
    canonical_dir.mkdir()
    output_dir.mkdir()
    skipped = "rec-skip"
    generated = "rec-new"
    _write_canonical(canonical_dir, skipped)
    _write_canonical(canonical_dir, generated)
    (output_dir / explorer.explorer_output_name(skipped)).write_text(
        "<html></html>", encoding="utf-8"
    )
    _write_manifest(output_dir, [_index_row(skipped)])
    operations = []
    generated_data = {
        "summary": {
            "frames": 4,
            "durationSec": 0.3,
            "objects": 1,
            "classCounts": {"car": 1},
        },
        "trajectory": {"x": [0.0, 1.0], "y": [0.0, 0.0]},
        "objects": [],
        "ld": {"summary": {"laneLines": 2, "roadBoundaries": 1, "roadmarks": 1}},
        "tags": {"scenarios": ["stationary"], "events": [{"scenario": "stationary"}]},
    }

    def build_base_data(scene_dir: Path) -> dict:
        operations.append(f"generate:{scene_dir.name}")
        return dict(generated_data)

    def rebuild_rows(output_dir_arg: Path, rows_by_recording: dict[str, dict]) -> list[dict]:
        operations.append("rebuild")
        return list(rows_by_recording.values())

    def write_index(index_path: Path, output_dir_arg: Path, rows: list[dict]) -> None:
        operations.append("write")
        index_path.write_text("index", encoding="utf-8")
        (output_dir_arg / "manifest.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(explorer, "build_base_data", build_base_data)
    monkeypatch.setattr(
        explorer,
        "build_ld_payload",
        lambda canonical: {"summary": {"laneLines": 2, "roadBoundaries": 1, "roadmarks": 1}},
    )
    monkeypatch.setattr(explorer, "build_road_feature_payload", lambda canonical: {})
    monkeypatch.setattr(explorer, "build_object_relation_payload", lambda canonical: {})
    monkeypatch.setattr(explorer, "build_object_path_crossing_payload", lambda canonical: {})
    monkeypatch.setattr(
        explorer,
        "build_tag_payload",
        lambda recording, window_dir, canonical: {
            "scenarios": ["stationary"],
            "events": [{"scenario": "stationary"}],
        },
    )
    monkeypatch.setattr(explorer, "write_debug_payloads", lambda *args: {"od": 0, "ld": 0})
    monkeypatch.setattr(
        explorer,
        "write_explorer_atomically",
        lambda output, data, canonical: output.write_text("<html></html>", encoding="utf-8"),
    )
    monkeypatch.setattr(explorer, "rebuild_rows_from_outputs", rebuild_rows)
    monkeypatch.setattr(explorer, "write_index_and_manifest", write_index)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_odld_dataset_explorers_w_scenario_tag.py",
            "--canonical-dir",
            str(canonical_dir),
            "--output-dir",
            str(output_dir),
            "--index-path",
            str(tmp_path / "index.html"),
            skipped,
            generated,
        ],
    )

    explorer.main()

    assert operations == [f"generate:{generated}", "rebuild", "write"]


def test_missing_requested_explorer_is_generated(tmp_path: Path, monkeypatch) -> None:
    canonical_dir = tmp_path / "canonical"
    output_dir = tmp_path / "explorers"
    canonical_dir.mkdir()
    output_dir.mkdir()
    recording = "missing"
    _write_canonical(canonical_dir, recording)
    data = {
        "summary": {
            "frames": 4,
            "durationSec": 0.3,
            "objects": 1,
            "classCounts": {"car": 1},
        },
        "trajectory": {"x": [0.0, 1.0], "y": [0.0, 0.0]},
        "objects": [],
        "ld": {"summary": {"laneLines": 2, "roadBoundaries": 1, "roadmarks": 1}},
        "tags": {"scenarios": ["stationary"], "events": [{"scenario": "stationary"}]},
    }
    monkeypatch.setattr(explorer, "build_base_data", lambda scene_dir: dict(data))
    monkeypatch.setattr(
        explorer,
        "build_ld_payload",
        lambda canonical: {"summary": {"laneLines": 2, "roadBoundaries": 1, "roadmarks": 1}},
    )
    monkeypatch.setattr(explorer, "build_road_feature_payload", lambda canonical: {})
    monkeypatch.setattr(explorer, "build_object_relation_payload", lambda canonical: {})
    monkeypatch.setattr(explorer, "build_object_path_crossing_payload", lambda canonical: {})
    monkeypatch.setattr(
        explorer,
        "build_tag_payload",
        lambda recording, window_dir, canonical: {
            "scenarios": ["stationary"],
            "events": [{"scenario": "stationary"}],
        },
    )
    monkeypatch.setattr(explorer, "write_debug_payloads", lambda *args: {"od": 0, "ld": 0})
    monkeypatch.setattr(
        explorer,
        "write_explorer_atomically",
        lambda output, data, canonical: output.write_text("<html></html>", encoding="utf-8"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_odld_dataset_explorers_w_scenario_tag.py",
            "--canonical-dir",
            str(canonical_dir),
            "--output-dir",
            str(output_dir),
            "--index-path",
            str(tmp_path / "index.html"),
            recording,
        ],
    )

    explorer.main()

    assert (output_dir / explorer.explorer_output_name(recording)).is_file()
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["recordings"][0]["recording"] == recording


def test_manifest_metadata_is_reused_without_html_parsing(
    tmp_path: Path, monkeypatch
) -> None:
    output_dir = tmp_path
    recording = "sample"
    (output_dir / explorer.explorer_output_name(recording)).write_text(
        "<html></html>", encoding="utf-8"
    )
    row = _index_row(recording)
    _write_manifest(output_dir, [row])
    monkeypatch.setattr(
        explorer,
        "row_from_explorer",
        lambda path: (_ for _ in ()).throw(AssertionError("parsed manifest row")),
    )

    rows = explorer.rebuild_rows_from_outputs(output_dir, explorer.read_manifest_rows(output_dir))

    assert rows == [row]


def test_html_parsing_is_final_rebuild_fallback(tmp_path: Path, monkeypatch) -> None:
    recording = "sample"
    output_path = tmp_path / explorer.explorer_output_name(recording)
    output_path.write_text("<html></html>", encoding="utf-8")
    _write_manifest(
        tmp_path,
        [{"recording": recording, "file": output_path.name, "frames": 4}],
    )
    parsed = []
    monkeypatch.setattr(
        explorer,
        "row_from_explorer",
        lambda path: parsed.append(path) or _index_row(recording),
    )

    rows = explorer.rebuild_rows_from_outputs(tmp_path, explorer.read_manifest_rows(tmp_path))

    assert parsed == [output_path]
    assert rows == [_index_row(recording)]


def test_index_from_existing_still_forces_full_html_rebuild(
    tmp_path: Path, monkeypatch
) -> None:
    output_dir = tmp_path / "explorers"
    output_dir.mkdir()
    recording = "sample"
    output_path = output_dir / explorer.explorer_output_name(recording)
    output_path.write_text("<html></html>", encoding="utf-8")
    parsed = []
    monkeypatch.setattr(
        explorer,
        "row_from_explorer",
        lambda path: parsed.append(path) or _index_row(recording),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_odld_dataset_explorers_w_scenario_tag.py",
            "--index-from-existing",
            "--output-dir",
            str(output_dir),
            "--index-path",
            str(tmp_path / "index.html"),
        ],
    )

    explorer.main()

    assert parsed == [output_path]
    assert (tmp_path / "index.html").is_file()


def test_empty_index_path_writes_default_next_to_output_dir(tmp_path: Path) -> None:
    output_dir = tmp_path / "quick_exploration_outputs" / "dataset_scene_explorers_odld_w_scenario_tag"
    output_dir.mkdir(parents=True)

    explorer.write_index_and_manifest(Path("."), output_dir, [])

    assert (tmp_path / "quick_exploration_outputs" / "dataset_odld_explorer_w_scenario_tag_index.html").is_file()


def test_directory_index_path_writes_index_html_inside_directory(tmp_path: Path) -> None:
    output_dir = tmp_path / "explorers"
    index_dir = tmp_path / "index_dir"
    output_dir.mkdir()
    index_dir.mkdir()

    explorer.write_index_and_manifest(index_dir, output_dir, [])

    assert (index_dir / "index.html").is_file()


def _canonical() -> dict:
    roadmark = {
        "roadmark_id": "cw1",
        "class": "crosswalk",
        "subclass": None,
        "shape_type": "polygon",
        "points": [
            {"position_lcs_m": [9.0, -3.0, 0.0]},
            {"position_lcs_m": [11.0, -3.0, 0.0]},
            {"position_lcs_m": [11.0, 3.0, 0.0]},
            {"position_lcs_m": [9.0, 3.0, 0.0]},
        ],
        "attributes": {},
        "ignored": False,
    }
    frames = []
    for index, x in enumerate((0.0, 5.0, 10.0, 15.0)):
        frames.append(
            {
                "frame_index": index,
                "time_since_start_s": index * 0.1,
                "ego": {
                    "position_lcs_m": [x, 0.0, 0.0],
                    "heading_lcs_rad": 0.0,
                    "speed_mps": 5.0,
                    "acceleration_mps2": 0.0,
                    "velocity_lcs_mps": [5.0, 0.0, 0.0],
                    "yaw_rate_radps": 0.0,
                },
                "ld": {"nearby_feature_ids": {"roadmarks": ["cw1"]}},
            }
        )
    return {
        "recording_id": "sample",
        "frames": frames,
        "ld_feature_store": {"roadmarks": [roadmark]},
    }


def test_compact_evidence_keeps_phase2b_debug_values() -> None:
    compact = explorer.compact_tag_evidence(
        {
            "road_feature_event_id": "crosswalk-traversal:crosswalk:cw1:2",
            "crosswalk_id": "crosswalk:cw1",
            "entry_frame": 2,
            "crossing_progress_m": 8.5,
            "association_confidence": "high",
            "large_internal_payload": list(range(100)),
        }
    )
    assert compact["crosswalk_id"] == "crosswalk:cw1"
    assert compact["entry_frame"] == 2
    assert compact["crossing_progress_m"] == 8.5
    assert "large_internal_payload" not in compact


def test_stale_window_events_are_replaced_by_current_detection(
    tmp_path: Path, monkeypatch
) -> None:
    stale = {
        "rule_config_version": "phase2-basic-lane-change-v1",
        "rule_based_events": [
            {
                "scenario": "stationary",
                "start_frame": 0,
                "end_frame": 1,
                "start_timestamp_s": 0.0,
                "end_timestamp_s": 0.1,
            }
        ],
    }
    (tmp_path / "sample_motional_windows_odld.json").write_text(
        json.dumps(stale), encoding="utf-8"
    )
    current = ScenarioEvent(
        "traversing_crosswalk",
        2,
        3,
        0.2,
        0.3,
        0.1,
        detector_version="phase2b-crosswalk-v1",
        evidence={"crosswalk_id": "crosswalk:cw1"},
    )
    monkeypatch.setattr(
        explorer, "detect_recording_events", lambda canonical, config: ([current], {})
    )
    payload = explorer.build_tag_payload("sample", tmp_path, _canonical())
    assert payload["configVersion"] == "phase3c-forward-arc-crossing-v3"
    assert payload["sourceKind"] == (
        "canonical_per_frame_rule_events_stale_window_replaced"
    )
    assert payload["scenarios"] == ["traversing_crosswalk"]


def test_unreliable_jerk_events_are_hidden_from_visualization(
    tmp_path: Path, monkeypatch
) -> None:
    current = [
        ScenarioEvent(
            "high_magnitude_jerk",
            0,
            1,
            0.0,
            0.1,
            0.1,
            detector_version="phase2-motion-v1",
        ),
        ScenarioEvent(
            "traversing_crosswalk",
            2,
            3,
            0.2,
            0.3,
            0.1,
            detector_version="phase2b-crosswalk-v1",
        ),
    ]
    monkeypatch.setattr(
        explorer, "detect_recording_events", lambda canonical, config: (current, {})
    )

    payload = explorer.build_tag_payload("sample", tmp_path, _canonical())

    assert payload["scenarios"] == ["traversing_crosswalk"]
    assert [event["scenario"] for event in payload["events"]] == [
        "traversing_crosswalk"
    ]


def test_relation_payload_contains_geometry_states_and_footprint() -> None:
    payload = explorer.build_road_feature_payload(_canonical())
    assert payload["schemaVersion"] == "road-feature-relations-v1"
    assert payload["configVersion"] == "phase3c-forward-arc-crossing-v3"
    assert payload["egoFootprint"] == {"length_m": 4.8, "width_m": 2.0}
    assert payload["tracks"][0]["trackId"] == "crosswalk:cw1"
    assert payload["tracks"][0]["x"]
    assert [frame["frameIndex"] for frame in payload["frames"]] == [0, 1, 2, 3]
    assert "on" in {
        relation["state"]
        for frame in payload["frames"]
        for relation in frame["crosswalks"]
    }


def test_generator_contains_phase2b_controls_colors_and_overlay_hooks() -> None:
    assert 'id="showRoadFeatureRelations"' in explorer.TAG_CONTROLS_HTML
    assert 'id="roadFeatureContext"' in explorer.TAG_CONTROLS_HTML
    for label in (
        "traversing_crosswalk",
        "on_stopline_crosswalk",
        "stationary_at_crosswalk",
        "stopping_at_crosswalk",
        "accelerating_at_crosswalk",
    ):
        assert f"{label}:" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "roadFeatureRelationTraces()" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "egoRoadFeatureFootprintTrace()" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "roadFeatureAssociationTrace(relations)" in explorer.TAG_SCRIPT_FUNCTIONS


def test_phase3a_object_payload_and_overlay_hooks() -> None:
    canonical = _canonical()
    canonical["frames"][0]["objects"] = [
        {
            "object_id": "p1",
            "class": "pedestrian",
            "subclass": None,
            "annotation_type": "dynamic",
            "position_lcs_m": [5.0, 0.0, 0.0],
            "dimensions_m": {"length": 0.6, "width": 0.6, "height": 1.7},
                    "heading_relative_rad": -math.pi / 2,
            "velocity_lcs_mps": [3.0, 4.0, 0.0],
            "velocity_source": "measured",
        }
    ]
    payload = explorer.build_object_relation_payload(canonical)
    assert payload["schemaVersion"] == "ego-object-relations-v1"
    assert payload["configVersion"] == "phase3c-forward-arc-crossing-v3"
    assert payload["frames"][0]["objects"][0]["category"] == "pedestrian"
    assert payload["frames"][0]["objects"][0]["annotationType"] == "dynamic"
    assert payload["frames"][0]["objects"][0]["speedMps"] == 5.0
    assert payload["frames"][0]["objects"][0]["velocityX"] == 3.0
    assert payload["frames"][0]["objects"][0]["velocityY"] == 4.0
    assert 'id="showObjectRelations"' in explorer.TAG_CONTROLS_HTML
    assert 'id="showDynamicObjectVelocities"' in explorer.TAG_CONTROLS_HTML
    assert 'id="objectRelationContext"' in explorer.TAG_CONTROLS_HTML
    assert "objectRelationTraces()" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "dynamicObjectVelocityTraces()" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "all dynamic-object speeds" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "name: 'ego speed'" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "traj.speed[currentIndex]" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "textposition: 'top center'" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "`${id} ·" not in explorer.TAG_SCRIPT_FUNCTIONS
    assert "item.trackId.replace('object:', '')" not in (
        explorer.TAG_SCRIPT_FUNCTIONS
    )
    for label in (
        "near_high_speed_vehicle",
        "near_long_vehicle",
        "near_multiple_bikes",
        "near_multiple_motorcycle",
        "near_multiple_pedestrians",
        "near_multiple_vehicles",
    ):
        assert f"{label}:" in explorer.TAG_SCRIPT_FUNCTIONS
    for label in (
        "near_pedestrian_on_crosswalk",
        "near_pedestrian_on_crosswalk_with_ego",
    ):
        assert f"{label}:" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "event.evidence.pedestrian_track_ids" in (
        explorer.TAG_SCRIPT_FUNCTIONS
    )


def test_phase3c_path_crossing_payload_controls_and_colors() -> None:
    canonical = _canonical()
    for index, frame in enumerate(canonical["frames"]):
        frame["objects"] = [
            {
                "object_id": "bike1",
                "class": "bicycle",
                "subclass": None,
                "annotation_type": "dynamic",
                "position_lcs_m": [7.5, 4.0 - index * 2.5, 0.0],
                "dimensions_m": {
                    "length": 1.8,
                    "width": 0.6,
                    "height": 1.4,
                },
                "heading_relative_rad": 0.0,
                "velocity_lcs_mps": [0.0, -25.0, 0.0],
                "velocity_source": "measured",
            }
        ]
    payload = explorer.build_object_path_crossing_payload(canonical)
    assert payload["schemaVersion"] == (
        "object-ego-forward-arc-crossing-relations-v3"
    )
    assert payload["configVersion"] == "phase3c-forward-arc-crossing-v3"
    assert payload["arc"]["outer_radius_m"] == 30.0
    assert payload["arc"]["half_angle_deg"] == 30.0
    assert payload["egoPath"]
    assert payload["frames"][0]["objects"][0]["category"] == "bicycle"
    assert 'id="showPathCrossingRelations"' in explorer.TAG_CONTROLS_HTML
    assert 'id="showConfirmedCrossingsOnly"' in explorer.TAG_CONTROLS_HTML
    assert 'id="pathCrossingObjectFilter"' in explorer.TAG_CONTROLS_HTML
    assert 'id="pathCrossingContext"' in explorer.TAG_CONTROLS_HTML
    assert "pathCrossingArcTraces()" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "crossingArcPolygon" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "currentPathCrossingFrame()" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "visibleConfirmedCrossingEvents()" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "crossingRelationObjects()" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "crossingTrajectoryPoints(item)" in explorer.TAG_SCRIPT_FUNCTIONS
    assert "setFrame(event.evidence.arc_entry_frame" in inspect.getsource(
        explorer.scene_html
    )
    for label in (
        "crossed_by_bike",
        "crossed_by_motorcycle",
        "crossed_by_vehicle",
    ):
        assert f"{label}:" in explorer.TAG_SCRIPT_FUNCTIONS
