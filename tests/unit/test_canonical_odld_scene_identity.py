from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest

from ms_odd_tagging.input_generator.canonical_odld import build_recording


RECORDING = "Rec_Drv_GER_TEST_20260414_103936"


def _write_recording(
    root: Path,
    *,
    od_id: str = "scene-id",
    od_name: str = "scene-name",
    ld_id: str = "scene-id",
    ld_name: str = "scene-name",
    ld_frame_count: int = 2,
) -> None:
    recording_dir = root / RECORDING
    recording_dir.mkdir(parents=True)
    od_annotations = {
        "scene": {
            "id": od_id,
            "name": od_name,
            "frameCount": 2,
        },
        "objects": [],
    }
    ld_annotations = {
        "scene": {
            "id": ld_id,
            "name": ld_name,
            "frameCount": ld_frame_count,
        },
        "lanes": {
            "points": [],
            "lines": [],
            "lanes": [],
            "roadBoundaries": [],
            "topologies": [],
        },
        "roadmarks": [],
    }
    (recording_dir / "annotations_OD.json").write_text(
        json.dumps(od_annotations), encoding="utf-8"
    )
    (recording_dir / "annotations_LD.json").write_text(
        json.dumps(ld_annotations), encoding="utf-8"
    )
    (recording_dir / "traj_lcs.txt").write_text(
        "0.0 0.0 0.0 0.0 0.0 0.0 0.0 1.0\n"
        "0.1 0.0 0.0 0.0 0.0 0.0 0.0 1.0\n",
        encoding="utf-8",
    )


def _build(source_root: Path, output_root: Path) -> dict:
    _, result = build_recording(
        source_root,
        output_root,
        RECORDING,
        100.0,
        False,
    )
    return result


def test_matching_scene_identity_has_no_warning(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    _write_recording(source_root)

    with warnings.catch_warnings(record=True) as warnings_seen:
        warnings.simplefilter("always")
        result = _build(source_root, tmp_path / "output")

    assert not warnings_seen
    alignment = result["source"]["alignment"]
    assert alignment["scene_id_match"] is True
    assert alignment["scene_name_match"] is True


@pytest.mark.parametrize(
    ("ld_id", "ld_name", "expected_id_match", "expected_name_match"),
    [
        ("other-id", "scene-name", False, True),
        ("other-id", "other-name", False, False),
        ("scene-id", "other-name", True, False),
    ],
)
def test_scene_identity_mismatch_warns_but_continues(
    tmp_path: Path,
    ld_id: str,
    ld_name: str,
    expected_id_match: bool,
    expected_name_match: bool,
) -> None:
    source_root = tmp_path / "source"
    _write_recording(source_root, ld_id=ld_id, ld_name=ld_name)

    with pytest.warns(RuntimeWarning, match="continuing despite") as warning:
        result = _build(source_root, tmp_path / "output")

    message = str(warning[0].message)
    assert RECORDING in message
    assert "OD id='scene-id', name='scene-name'" in message
    assert f"LD id={ld_id!r}, name={ld_name!r}" in message
    alignment = result["source"]["alignment"]
    assert alignment["scene_id_match"] is expected_id_match
    assert alignment["scene_name_match"] is expected_name_match
    assert message in result["data_quality"]["notes"]


def test_frame_count_mismatch_remains_fatal(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_recording(source_root, ld_frame_count=3)

    with pytest.raises(ValueError, match="OD frames=2, LD frames=3"):
        _build(source_root, tmp_path / "output")
