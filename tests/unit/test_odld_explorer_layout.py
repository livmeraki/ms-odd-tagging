from __future__ import annotations

import json
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts" / "odld_explorer"
sys.path.insert(0, str(SCRIPT_DIR))

import generate_dataset_explorers as base_explorer  # noqa: E402
import add_gt_authoring_to_tagged_explorers as gt_authoring_explorer  # noqa: E402
import generate_odld_dataset_explorers_w_scenario_tag as odld_explorer  # noqa: E402


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
