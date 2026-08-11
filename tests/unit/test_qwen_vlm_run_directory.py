from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ms_odd_tagging.qwen_vlm_poc.cli import _run_directory


def test_run_directory_uses_unique_datetime_folder():
    base = Path("/tmp/qwen_vlm_poc/event_driven")
    generated_at = datetime(2026, 8, 11, 13, 38, 7, 123456)

    path = _run_directory(base, generated_at)

    assert path == base / "20260811_133807_123456"
