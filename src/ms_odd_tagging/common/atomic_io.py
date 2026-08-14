"""Small crash-safe filesystem helpers for generated artifacts."""

from __future__ import annotations

import os
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write a text file through a sibling temporary file, then atomically publish it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(text, encoding=encoding)
    os.replace(temp, path)


def recover_staged_directory(final_dir: Path) -> None:
    """Recover a frame directory after interruption during a prior publish."""
    temp_dir = final_dir.with_name(f".{final_dir.name}.tmp")
    backup_dir = final_dir.with_name(f".{final_dir.name}.old")

    if final_dir.exists():
        if backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)
    elif backup_dir.exists():
        os.replace(backup_dir, final_dir)

    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)


@contextmanager
def staged_directory(final_dir: Path) -> Iterator[Path]:
    """Build a directory under a visible temporary name and publish it as one unit.

    Existing completed output remains available while the new version is built. A
    short-lived ``.old`` backup makes the final rename recoverable if the process
    is interrupted during publication.
    """
    recover_staged_directory(final_dir)
    temp_dir = final_dir.with_name(f".{final_dir.name}.tmp")
    backup_dir = final_dir.with_name(f".{final_dir.name}.old")
    temp_dir.mkdir(parents=True, exist_ok=False)

    try:
        yield temp_dir
    except BaseException:
        # Keep the temp directory as an explicit sign of an interrupted/failed
        # generation. The next attempt cleans it after recovering any backup.
        raise

    if backup_dir.exists():
        shutil.rmtree(backup_dir, ignore_errors=True)
    if final_dir.exists():
        os.replace(final_dir, backup_dir)
    try:
        os.replace(temp_dir, final_dir)
    except BaseException:
        if not final_dir.exists() and backup_dir.exists():
            os.replace(backup_dir, final_dir)
        raise
    else:
        if backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)
