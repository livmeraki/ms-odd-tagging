from __future__ import annotations

from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts" / "odld_explorer"
sys.path.insert(0, str(SCRIPT_DIR))

import generate_dataset_explorers as base_explorer  # noqa: E402
import explorer as odld_explorer  # noqa: E402
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
            "x": [0.0, 0.0, 0.0],
            "y": [0.0, 0.0, 0.0],
            "yaw_deg": [0.0, 0.0, 0.0],
            "speed": [0.0, 0.0, 0.0],
            "accel": [0.0, 0.0, 0.0],
            "jerk": [0.0, 0.0, 0.0],
            "yaw_rate": [0.0, 0.0, 0.0],
        },
        "objects": [],
        "ld": {"summary": {}},
        "ldFrames": {},
        "tags": {"scenarios": [], "events": []},
        "roadFeatureRelations": {"frames": [], "tracks": [], "associations": []},
        "objectRelations": {"frames": []},
        "pathCrossingRelations": {"frames": [], "egoPath": []},
        "trafficLightContext": {"frames": []},
        "vlmTrafficLightEpisodes": {"events": []},
    }


def test_explorer_uses_shared_index_and_manifest_utilities() -> None:
    for name in (
        "index_html",
        "row_from_explorer",
        "explorer_output_name",
        "recording_from_canonical_path",
        "read_manifest_rows",
        "row_from_generated_data",
        "select_canonical_paths",
    ):
        assert getattr(odld_explorer, name) is getattr(explorer_common, name)


def test_recording_selection_is_stable(tmp_path: Path) -> None:
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


def test_playback_controls_are_in_top_bar() -> None:
    page = base_explorer.scene_html(minimal_explorer_data())
    assert '<div id="animControls" class="topPlayback">' in page
    assert page.index('id="animControls"') < page.index("<main>")
    assert 'value="16">16x' in page
    assert 'value="24">24x' in page
    assert 'value="32">32x' in page


def test_odld_sidebar_and_plot_traces_are_valid() -> None:
    page = odld_explorer.scene_html(minimal_explorer_data())
    assert page.index('id="showLaneLines"') > page.index("<aside>")
    assert page.index('id="showTags"') > page.index("<aside>")
    assert "const plotTraces = traces.filter(" in page
    assert "Plotly.react('map', plotTraces," in page
