from __future__ import annotations

import json
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts" / "odld_explorer"
sys.path.insert(0, str(SCRIPT_DIR))

import generate_dataset_explorers as base_explorer  # noqa: E402
import add_gt_authoring_to_tagged_explorers as gt_authoring_explorer  # noqa: E402
import add_bev_lane_poc_overlay_to_explorer as bev_lane_overlay  # noqa: E402
import add_lanelet2_poc_overlay_to_explorer as lanelet2_overlay  # noqa: E402
import generate_odld_dataset_explorers_w_frame_scenario_tag as frame_explorer  # noqa: E402
import generate_odld_dataset_explorers_w_scenario_tag as odld_explorer  # noqa: E402
import odld_explorer_common as explorer_common  # noqa: E402


def minimal_explorer_data() -> dict:
    return {
        "summary": {
            "recording": "rec",
            "frames": 3,
            "durationSec": 0.2,
            "objects": 0,
            "movingTracks": 0,
            "classCounts": {},
        },
        "trajectory": {
            "rel_t": [0.0, 0.1, 0.2],
            "speed": [0.0, 0.0, 0.0],
        },
        "objects": [],
        "ld": {"summary": {}},
        "ldFrames": {},
        "tags": {"scenarios": [], "events": []},
        "roadFeatureRelations": {"frames": [], "tracks": [], "associations": []},
        "objectRelations": {"frames": []},
        "pathCrossingRelations": {"frames": [], "egoPath": []},
    }


def test_specialized_generators_share_index_and_manifest_utilities() -> None:
    shared_names = (
        "index_html",
        "row_from_explorer",
        "explorer_output_name",
        "recording_from_canonical_path",
        "read_manifest_rows",
        "row_from_generated_data",
        "select_canonical_paths",
    )
    for name in shared_names:
        shared = getattr(explorer_common, name)
        assert getattr(odld_explorer, name) is shared
        assert getattr(frame_explorer, name) is shared


def test_shared_recording_selection_is_stable(tmp_path: Path) -> None:
    expected = []
    for recording in ("Rec_B", "Rec_A", "Rec_C"):
        path = tmp_path / f"{recording}_canonical_odld_frames.json"
        path.write_text("{}", encoding="utf-8")
        expected.append(path)

    assert explorer_common.select_canonical_paths(tmp_path) == sorted(expected)
    assert explorer_common.select_canonical_paths(tmp_path, ["Rec_C", "Rec_A"]) == [
        tmp_path / "Rec_A_canonical_odld_frames.json",
        tmp_path / "Rec_C_canonical_odld_frames.json",
    ]


def test_playback_controls_are_in_top_bar_with_faster_speeds() -> None:
    page = base_explorer.scene_html(minimal_explorer_data())

    assert '<div id="animControls" class="topPlayback">' in page
    assert page.index('id="animControls"') < page.index("<main>")
    assert 'value="16">16x' in page
    assert 'value="24">24x' in page
    assert 'value="32">32x' in page
    assert page.count('id="playPause"') == 1
    assert page.count('id="frameSlider"') == 1
    assert page.count('id="playbackSpeed"') == 1


def test_odld_sidebar_controls_do_not_move_into_top_playback_bar() -> None:
    page = odld_explorer.scene_html(minimal_explorer_data())

    assert page.index('id="animControls"') < page.index("<main>")
    assert page.index('id="showLaneLines"') > page.index("<aside>")
    assert page.index('id="showLaneLines"') < page.index('for="classFilter"')
    assert page.index('id="showTags"') > page.index("<aside>")
    assert page.index('id="showTags"') < page.index('for="classFilter"')


def test_gt_authoring_index_uses_odld_card_filter_layout(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    recording = "Rec_Test"
    source = source_dir / f"{recording}_animated_odld_explorer.html"
    source.write_text("<html></html>", encoding="utf-8")
    manifest_row = {
        "recording": recording,
        "file": source.name,
        "frames": 3,
        "duration": 0.2,
        "objects": 0,
        "lines": 1,
        "boundaries": 2,
        "roadmarks": 3,
        "tagScenarios": 1,
        "tagEvents": 2,
        "tagScenarioList": ["stationary"],
        "topClasses": "none",
        "thumbnail": "<svg></svg>",
    }
    (source_dir / "manifest.json").write_text(
        json.dumps({"recordings": [manifest_row]}),
        encoding="utf-8",
    )

    rows = gt_authoring_explorer.source_manifest_rows(source_dir)
    row = gt_authoring_explorer.index_row_for_authoring(
        source,
        f"{recording}_animated_odld_explorer_w_gt_authoring.html",
        rows,
    )
    page = odld_explorer.index_html([row])

    assert "const INDEX_ROWS =" in page
    assert 'id="scenarioFilter"' in page
    assert 'class="card"' in page
    assert f"{recording}_animated_odld_explorer_w_gt_authoring.html" in page


def test_gt_authoring_selective_regeneration_keeps_full_existing_index(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    frame_root = tmp_path / "frames"
    gt_dir = tmp_path / "gt"
    source_dir.mkdir()
    output_dir.mkdir()
    frame_root.mkdir()
    gt_dir.mkdir()
    recordings = ["Rec_A", "Rec_B", "Rec_C"]
    rows = []
    for index, recording in enumerate(recordings):
        source = source_dir / f"{recording}_animated_odld_explorer.html"
        source.write_text("<html></html>", encoding="utf-8")
        output = output_dir / f"{recording}_animated_odld_explorer_w_gt_authoring.html"
        output.write_text(f"old {recording}", encoding="utf-8")
        rows.append(
            {
                "recording": recording,
                "file": source.name,
                "frames": 3,
                "duration": 0.2,
                "objects": 0,
                "lines": index,
                "boundaries": index,
                "roadmarks": index,
                "tagScenarios": 1,
                "tagEvents": 1,
                "tagScenarioList": ["stationary"],
                "topClasses": "none",
                "thumbnail": "<svg></svg>",
            }
        )
    (source_dir / "manifest.json").write_text(
        json.dumps({"recordings": rows}),
        encoding="utf-8",
    )
    orphan = "Rec_Orphan"
    orphan_output = output_dir / f"{orphan}_animated_odld_explorer_w_gt_authoring.html"
    orphan_payload = minimal_explorer_data()
    orphan_payload["summary"]["recording"] = orphan
    orphan_payload["ld"]["summary"] = {
        "laneLines": 1,
        "roadBoundaries": 2,
        "roadmarks": 3,
    }
    orphan_output.write_text(
        f"<html><script>const DATA = {json.dumps(orphan_payload)}; const GT_AUTHORING = {{}};</script></html>",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        gt_authoring_explorer,
        "build_review_payload",
        lambda *_args, **_kwargs: {"review_frames": [1, 2]},
    )
    monkeypatch.setattr(
        gt_authoring_explorer,
        "inject_authoring",
        lambda page, recording, payload, source_dir_arg: f"new {recording}",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "add_gt_authoring_to_tagged_explorers.py",
            "--source-dir",
            str(source_dir),
            "--output-dir",
            str(output_dir),
            "--frame-input-root",
            str(frame_root),
            "--gt-dir",
            str(gt_dir),
            "--regenerate-existing",
            "Rec_B",
        ],
    )

    assert gt_authoring_explorer.main() == 0

    index = (output_dir / "index.html").read_text(encoding="utf-8")
    assert all(
        f"{recording}_animated_odld_explorer_w_gt_authoring.html" in index
        for recording in [*recordings, orphan]
    )
    assert (output_dir / "Rec_B_animated_odld_explorer_w_gt_authoring.html").read_text(
        encoding="utf-8"
    ) == "new Rec_B"
    assert (output_dir / "Rec_A_animated_odld_explorer_w_gt_authoring.html").read_text(
        encoding="utf-8"
    ) == "old Rec_A"


def test_lanelet2_poc_overlay_duplicates_odld_explorer_controls_and_traces() -> None:
    page = base_explorer.scene_html(minimal_explorer_data())
    result = {
        "recording_id": "rec",
        "coordinate_system": "LCS",
        "lanelet2_available": True,
        "frames": [
            {
                "frame_index": 0,
                "status": "matched",
                "ego_lane": {
                    "exists": True,
                    "lane_id": "ego",
                    "polygon_lcs_m": [[0, 1], [1, 1], [1, -1], [0, -1]],
                    "confidence": 0.9,
                },
                "left_adjacent": {
                    "exists": True,
                    "lane_id": "left",
                    "polygon_lcs_m": [[0, 3], [1, 3], [1, 1], [0, 1]],
                    "confidence": 0.8,
                },
                "right_adjacent": {
                    "exists": False,
                    "lane_id": None,
                    "polygon_lcs_m": [],
                    "confidence": 0.0,
                },
                "candidate_lanelets": [],
                "routing": {
                    "backend": "lanelet2",
                    "queries": {
                        "left": "left",
                        "right": None,
                        "adjacentLeft": None,
                        "adjacentRight": None,
                    },
                    "error": None,
                },
            }
        ],
    }

    lcs_payload = {
        "frames": {
            "0": [
                {
                    "boundary_id": "merged_1",
                    "source_kind": "lane_line",
                    "points_lcs_m": [[0, 1], [1, 1]],
                    "attributes": {"merged_from_boundary_ids": ["line_1"]},
                }
            ]
        },
    }

    injected = lanelet2_overlay.inject_overlay(page, result, lcs_payload)

    assert "const LANELET2_POC =" in injected
    assert "const LANELET2_LCS =" in injected
    assert 'id="showLanelet2LcsLocal"' in injected
    assert 'id="showLanelet2Poc"' in injected
    assert 'id="showLanelet2Candidates"' in injected
    assert "Local LCS boundaries used by Lanelet2 POC" in injected
    assert 'id="showLanelet2LcsRaw"' not in injected
    assert "Raw LCS LD boundaries" not in injected
    assert "function addLanelet2PocTraces(traces)" in injected
    assert "addLanelet2PocTraces(traces);" in injected
    assert "Lanelet2 ego lane" in injected
    assert injected.count("const DATA =") == 1


def test_bev_lane_poc_overlay_duplicates_odld_explorer_controls_and_traces() -> None:
    page = base_explorer.scene_html(minimal_explorer_data())
    result = {
        "recording_id": "rec",
        "coordinate_system": "BEV_EGO_METERS",
        "frames": [
            {
                "frame_index": 0,
                "status": "matched",
                "ego_lane": {
                    "exists": True,
                    "lane_id": "ego",
                    "polygon_lcs_m": [[0, 1], [1, 1], [1, -1], [0, -1]],
                    "confidence": 0.9,
                },
                "left_adjacent": {
                    "exists": True,
                    "lane_id": "left",
                    "polygon_lcs_m": [[0, 3], [1, 3], [1, 1], [0, 1]],
                    "confidence": 0.8,
                },
                "right_adjacent": {
                    "exists": False,
                    "lane_id": None,
                    "polygon_lcs_m": [],
                    "confidence": 0.0,
                },
                "candidate_lanes": [],
                "matching_source": "extended_boundaries",
                "lane_extension": {
                    "boundaries": [{"extended": True}],
                },
                "rejections": {"duplicates": []},
            }
        ],
    }

    injected = bev_lane_overlay.inject_overlay(page, result)

    assert "const BEV_LANE_POC =" in injected
    assert 'id="showBevLanePoc"' in injected
    assert 'id="showBevLaneCandidates"' in injected
    assert "function addBevLanePocTraces(traces)" in injected
    assert "addBevLanePocTraces(traces);" in injected
    assert "matching_source" in injected
    assert "extended=" in injected
    assert "BEV ego lane" in injected
    assert "BEV lane candidates" in injected
    assert injected.count("const DATA =") == 1
