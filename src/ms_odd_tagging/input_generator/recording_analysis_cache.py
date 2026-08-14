"""Cache expensive recording-wide analysis used by per-frame input generation."""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Any, Callable

from ms_odd_tagging.common.atomic_io import atomic_write_text
from ms_odd_tagging.tagger.rule_based.scenario_event import ScenarioEvent

CACHE_SCHEMA_VERSION = "recording-analysis-cache-v1"


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_stamp(callable_obj: Callable[..., Any]) -> dict[str, Any]:
    path_text = inspect.getsourcefile(callable_obj)
    if not path_text:
        return {"path": None, "mtime_ns": None, "size": None}
    path = Path(path_text)
    try:
        stat = path.stat()
    except OSError:
        return {"path": str(path), "mtime_ns": None, "size": None}
    return {
        "path": path.name,
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_stamp(canonical_path: Path) -> dict[str, Any]:
    stat = canonical_path.stat()
    return {
        "name": canonical_path.name,
        "size": stat.st_size,
        "sha256": _file_sha256(canonical_path),
    }


def analysis_signature(
    canonical_path: Path,
    config: dict[str, Any],
    detect_recording_events: Callable[..., Any],
    run_following_lane: Callable[..., Any],
) -> dict[str, Any]:
    """Return a signature that invalidates when data, config, or analysis code change."""
    return {
        "schema_version": CACHE_SCHEMA_VERSION,
        "canonical": _canonical_stamp(canonical_path),
        "config_sha256": _stable_hash(config),
        "rule_source": _source_stamp(detect_recording_events),
        "lane_source": _source_stamp(run_following_lane),
    }


def load_cached_analysis(
    cache_path: Path,
    signature: dict[str, Any],
) -> tuple[list[ScenarioEvent], dict[str, Any], dict[str, Any]] | None:
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("signature") != signature:
        return None
    event_rows = payload.get("rule_events")
    quality = payload.get("quality")
    lane_result = payload.get("following_lane")
    if not isinstance(event_rows, list) or not isinstance(quality, dict) or not isinstance(lane_result, dict):
        return None
    try:
        events = [ScenarioEvent(**row) for row in event_rows if isinstance(row, dict)]
    except TypeError:
        return None
    return events, quality, lane_result


def write_cached_analysis(
    cache_path: Path,
    signature: dict[str, Any],
    events: list[ScenarioEvent],
    quality: dict[str, Any],
    lane_result: dict[str, Any],
) -> None:
    payload = {
        "signature": signature,
        "rule_events": [event.to_dict() for event in events],
        "quality": quality,
        "following_lane": lane_result,
    }
    atomic_write_text(
        cache_path,
        json.dumps(payload, ensure_ascii=False, indent=2),
    )


def get_recording_analysis(
    *,
    canonical_path: Path,
    recording: dict[str, Any],
    recording_dir: Path,
    config: dict[str, Any],
    detect_recording_events: Callable[..., Any],
    run_following_lane: Callable[..., Any],
    refresh: bool = False,
) -> tuple[list[ScenarioEvent], dict[str, Any], dict[str, Any], bool]:
    """Load cached recording analysis or compute and persist it.

    Returns ``(events, quality, lane_result, cache_hit)``.
    """
    signature = analysis_signature(
        canonical_path,
        config,
        detect_recording_events,
        run_following_lane,
    )
    cache_path = recording_dir / ".cache" / "recording_analysis.json"
    if not refresh:
        cached = load_cached_analysis(cache_path, signature)
        if cached is not None:
            events, quality, lane_result = cached
            return events, quality, lane_result, True

    events, quality = detect_recording_events(recording, config)
    lane_result = run_following_lane(recording)
    write_cached_analysis(cache_path, signature, events, quality, lane_result)
    return events, quality, lane_result, False
