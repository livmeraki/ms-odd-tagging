"""Resume/regenerate policy and fingerprints for per-frame generation."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

GENERATION_FINGERPRINT_VERSION = "frame-generation-v2"
REQUIRED_FRAME_FILES = ("bev.png", "frame.json", "gt_reference.json")

ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_CYAN = "\033[36m"
ANSI_GREEN = "\033[32m"
ANSI_YELLOW = "\033[33m"
ANSI_RED = "\033[31m"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _callable_module_sha256(callable_obj: Callable[..., Any]) -> str | None:
    source = inspect.getsourcefile(callable_obj)
    if not source:
        return None
    path = Path(source)
    if not path.is_file():
        return None
    return _file_sha256(path)


def _explorer_renderer_sha256() -> str | None:
    """Fingerprint the actual renderer even when called through compatibility wrappers."""
    try:
        from . import revised_bev

        path = Path(revised_bev.__file__ or "")
        return _file_sha256(path) if path.is_file() else None
    except (ImportError, OSError):
        return None


def build_generation_signature(
    *,
    canonical_path: Path,
    config: dict[str, Any],
    extent: tuple[float, float, float, float],
    size: tuple[int, int],
    max_objects: int,
    render_callable: Callable[..., Any],
    frame_json_callable: Callable[..., Any],
) -> dict[str, Any]:
    """Build a recording-level signature for outputs that affect frame contents."""
    config_bytes = json.dumps(
        config,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return {
        "version": GENERATION_FINGERPRINT_VERSION,
        "canonical_sha256": _file_sha256(canonical_path),
        "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "extent_m": list(extent),
        "size_px": list(size),
        "max_objects": max_objects,
        "renderer_wrapper_sha256": _callable_module_sha256(render_callable),
        "renderer_implementation_sha256": _explorer_renderer_sha256(),
        "frame_json_module_sha256": _callable_module_sha256(frame_json_callable),
    }


def frame_fingerprint(signature: dict[str, Any], frame_index: int) -> str:
    payload = {"signature": signature, "frame_index": int(frame_index)}
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def completed_frame_matches(frame_dir: Path, expected_fingerprint: str) -> bool:
    """Return True only for a complete frame generated with the expected inputs."""
    if not frame_dir.is_dir():
        return False
    if any(not (frame_dir / name).is_file() for name in REQUIRED_FRAME_FILES):
        return False
    try:
        payload = json.loads((frame_dir / "frame.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    generation = payload.get("generation")
    return isinstance(generation, dict) and generation.get("fingerprint") == expected_fingerprint


def recording_has_existing_outputs(recording_dir: Path) -> bool:
    if not recording_dir.exists():
        return False
    for path in recording_dir.iterdir():
        name = path.name
        if name.startswith("frame_") or (
            name.startswith(".frame_") and (name.endswith(".tmp") or name.endswith(".old"))
        ):
            return True
    return False


def _paint(text: str, color: str, *, enabled: bool, bold: bool = False) -> str:
    if not enabled:
        return text
    prefix = f"{ANSI_BOLD if bold else ''}{color}"
    return f"{prefix}{text}{ANSI_RESET}"


def terminal_color_enabled() -> bool:
    """Use ANSI colors only for an interactive terminal and respect NO_COLOR."""
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def format_existing_output_prompt(*, use_color: bool) -> str:
    """Return a deliberately prominent, line-oriented rerun decision prompt."""
    title = _paint(
        "Existing frame inputs were found.",
        ANSI_CYAN,
        enabled=use_color,
        bold=True,
    )
    resume = (
        f"  {_paint('[R] RESUME', ANSI_GREEN, enabled=use_color, bold=True)}"
        "      Keep matching completed frames; rebuild stale/missing/temp frames."
    )
    regenerate = (
        f"  {_paint('[G] REGENERATE', ANSI_YELLOW, enabled=use_color, bold=True)}"
        "  Generate all selected frames again and replace completed outputs safely."
    )
    cancel = (
        f"  {_paint('[C] CANCEL', ANSI_RED, enabled=use_color, bold=True)}"
        "      Stop without changing frame outputs."
    )
    instruction = _paint(
        "Enter R, G, or C: ",
        ANSI_CYAN,
        enabled=use_color,
        bold=True,
    )
    return f"\n{title}\n\n{resume}\n{regenerate}\n{cancel}\n\n{instruction}"


def choose_existing_output_action(
    requested: str,
    *,
    has_existing: bool,
    input_fn: Callable[[str], str] = input,
    interactive: bool | None = None,
) -> str:
    """Resolve ask/resume/regenerate/cancel without blocking non-interactive jobs."""
    if requested != "ask" or not has_existing:
        return "regenerate" if requested == "ask" else requested

    if interactive is None:
        interactive = sys.stdin.isatty()
    if not interactive:
        raise RuntimeError(
            "existing frame outputs were found, but input is non-interactive; "
            "pass --existing-output resume, regenerate, or cancel"
        )

    prompt = format_existing_output_prompt(use_color=terminal_color_enabled())
    while True:
        answer = input_fn(prompt).strip().lower()
        if answer in {"r", "resume"}:
            return "resume"
        if answer in {"g", "regenerate", "generate"}:
            return "regenerate"
        if answer in {"c", "cancel", "q", "quit"}:
            return "cancel"
        print(
            _paint(
                "Invalid choice. Please enter R, G, or C.",
                ANSI_RED,
                enabled=terminal_color_enabled(),
                bold=True,
            ),
            flush=True,
        )
