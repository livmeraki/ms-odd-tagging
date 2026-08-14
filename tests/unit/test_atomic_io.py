from __future__ import annotations

from pathlib import Path

import pytest

from ms_odd_tagging.common.atomic_io import atomic_write_text, staged_directory


def test_staged_directory_keeps_previous_complete_output_on_failure(tmp_path: Path) -> None:
    final_dir = tmp_path / "frame_000001"
    final_dir.mkdir()
    (final_dir / "bev.png").write_bytes(b"old")

    with pytest.raises(RuntimeError):
        with staged_directory(final_dir) as temp_dir:
            assert temp_dir.name == ".frame_000001.tmp"
            (temp_dir / "bev.png").write_bytes(b"new")
            raise RuntimeError("interrupted")

    assert (final_dir / "bev.png").read_bytes() == b"old"
    assert (tmp_path / ".frame_000001.tmp").exists()


def test_staged_directory_publishes_complete_replacement(tmp_path: Path) -> None:
    final_dir = tmp_path / "frame_000001"
    final_dir.mkdir()
    (final_dir / "bev.png").write_bytes(b"old")

    with staged_directory(final_dir) as temp_dir:
        (temp_dir / "bev.png").write_bytes(b"new")
        (temp_dir / "frame.json").write_text("{}", encoding="utf-8")

    assert (final_dir / "bev.png").read_bytes() == b"new"
    assert (final_dir / "frame.json").read_text(encoding="utf-8") == "{}"
    assert not (tmp_path / ".frame_000001.tmp").exists()
    assert not (tmp_path / ".frame_000001.old").exists()


def test_atomic_write_text_replaces_destination(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text("old", encoding="utf-8")

    atomic_write_text(path, "new")

    assert path.read_text(encoding="utf-8") == "new"
    assert not (tmp_path / ".manifest.json.tmp").exists()
