import json
from pathlib import Path

from ms_odd_tagging.scenarios.following_lane.detector import run_following_lane
from ms_odd_tagging.scenarios.following_lane.pipeline import main, render_html

from test_following_lane import synthetic_recording


def test_standalone_debugger_exposes_all_lane_decisions(tmp_path: Path):
    recording = synthetic_recording()
    output = tmp_path / "lane_debugger.html"

    render_html(recording, run_following_lane(recording), output)

    page = output.read_text(encoding="utf-8")
    assert "Left lane decision" in page
    assert "Ego lane decision" in page
    assert "Right lane decision" in page
    assert "Complete current-frame detector output" in page
    assert 'id="frameNumber"' in page
    assert "frameIndexToPosition" in page
    assert '"candidates"' in page
    assert "physical lane " not in page
    assert "LD line " not in page


def test_cli_generates_standalone_debugger_without_base_explorer(
    tmp_path: Path,
):
    canonical_dir = tmp_path / "canonical"
    canonical_dir.mkdir()
    canonical_path = canonical_dir / "synthetic_canonical_odld_frames.json"
    canonical_path.write_text(
        json.dumps(synthetic_recording()),
        encoding="utf-8",
    )
    output_root = tmp_path / "following_lane"

    assert main(
        [
            "synthetic",
            "--canonical-dir",
            str(canonical_dir),
            "--output-root",
            str(output_root),
        ]
    ) == 0

    debugger = (
        output_root
        / "04_visualization"
        / "synthetic_following_lane_explorer.html"
    )
    assert debugger.is_file()
    assert "following-lane debugger" in debugger.read_text(encoding="utf-8")
