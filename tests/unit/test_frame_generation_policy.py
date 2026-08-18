from __future__ import annotations

import json
from pathlib import Path

import pytest

from ms_odd_tagging.frame_inputs.frame_generation_policy import (
    ANSI_GREEN,
    choose_existing_output_action,
    completed_frame_matches,
    format_existing_output_prompt,
    frame_fingerprint,
)


def test_existing_output_prompt_allows_resume() -> None:
    answers = iter(["r"])
    assert (
        choose_existing_output_action(
            "ask",
            has_existing=True,
            input_fn=lambda _: next(answers),
            interactive=True,
        )
        == "resume"
    )


def test_existing_output_prompt_allows_regenerate() -> None:
    answers = iter(["g"])
    assert (
        choose_existing_output_action(
            "ask",
            has_existing=True,
            input_fn=lambda _: next(answers),
            interactive=True,
        )
        == "regenerate"
    )


def test_existing_output_prompt_allows_cancel() -> None:
    answers = iter(["c"])
    assert (
        choose_existing_output_action(
            "ask",
            has_existing=True,
            input_fn=lambda _: next(answers),
            interactive=True,
        )
        == "cancel"
    )


def test_existing_output_prompt_is_multiline_and_explains_each_choice() -> None:
    prompt = format_existing_output_prompt(use_color=False)
    assert "\n\n  [R] RESUME" in prompt
    assert "\n  [G] REGENERATE" in prompt
    assert "\n  [C] CANCEL" in prompt
    assert "stale/missing/temp" in prompt
    assert "replace completed outputs safely" in prompt
    assert "Stop without changing frame outputs" in prompt


def test_existing_output_prompt_can_colorize_actions() -> None:
    prompt = format_existing_output_prompt(use_color=True)
    assert ANSI_GREEN in prompt
    assert "[R] RESUME" in prompt


def test_noninteractive_ask_requires_explicit_policy() -> None:
    with pytest.raises(RuntimeError, match="--existing-output"):
        choose_existing_output_action(
            "ask",
            has_existing=True,
            interactive=False,
        )


def test_resume_requires_all_files_and_matching_fingerprint(tmp_path: Path) -> None:
    signature = {"version": "test", "canonical_sha256": "abc"}
    fingerprint = frame_fingerprint(signature, 12)
    frame_dir = tmp_path / "frame_000012"
    frame_dir.mkdir()
    (frame_dir / "bev.png").write_bytes(b"png")
    (frame_dir / "gt_reference.json").write_text("{}", encoding="utf-8")
    (frame_dir / "frame.json").write_text(
        json.dumps(
            {
                "frame_index": 12,
                "generation": {"fingerprint": fingerprint},
            }
        ),
        encoding="utf-8",
    )
    assert completed_frame_matches(frame_dir, fingerprint)
    assert not completed_frame_matches(frame_dir, "different")

    (frame_dir / "bev.png").unlink()
    assert not completed_frame_matches(frame_dir, fingerprint)
