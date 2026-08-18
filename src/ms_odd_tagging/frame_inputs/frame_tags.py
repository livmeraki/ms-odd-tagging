"""Convert recording-level scenario events into sampled per-frame tag files."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from ms_odd_tagging.tagger.rule_based.registry import RULE_BASED_SCENARIOS


SCHEMA_VERSION = "motional-scenario-frame-tags-1fps-v1"
DEFAULT_SAMPLE_RATE_HZ = 1.0


def _event_dict(event: Any) -> dict[str, Any]:
    return event.to_dict() if hasattr(event, "to_dict") else dict(event)


def _frame_index(frame: dict[str, Any]) -> int:
    if "frame_index" in frame:
        return int(frame["frame_index"])
    return int(frame["frame"])


def _timestamp_s(frame: dict[str, Any]) -> float:
    value = frame.get("time_since_start_s", frame.get("timestamp_s"))
    return float(value) if isinstance(value, (int, float)) else 0.0


def scenario_key_set(
    *,
    event_payload: dict[str, Any] | None = None,
    events: list[Any] | None = None,
    configured_scenarios: list[str] | tuple[str, ...] | set[str] | None = None,
) -> list[str]:
    """Return all currently available motional scenario keys for export."""
    keys = set(RULE_BASED_SCENARIOS)
    if configured_scenarios:
        keys.update(str(scenario) for scenario in configured_scenarios)
    if event_payload:
        keys.update(str(scenario) for scenario in event_payload.get("scenario_taxonomy") or [])
        events = [*(events or []), *(event_payload.get("rule_based_events") or [])]
    for event in events or []:
        item = _event_dict(event)
        if item.get("scenario") is not None:
            keys.add(str(item["scenario"]))
    return sorted(keys)


def sample_frames_nearest_1fps(
    frames: list[dict[str, Any]],
    *,
    sample_rate_hz: float = DEFAULT_SAMPLE_RATE_HZ,
) -> list[dict[str, Any]]:
    """Select original frames nearest to 0s, 1s, 2s, ... without duplicates."""
    if not isinstance(sample_rate_hz, (int, float)) or not math.isfinite(sample_rate_hz):
        raise ValueError("sample_rate_hz must be a positive finite number")
    if sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be a positive finite number")
    ordered = sorted(frames, key=lambda frame: (_timestamp_s(frame), _frame_index(frame)))
    if not ordered:
        return []
    step_s = 1.0 / float(sample_rate_hz)
    duration_s = max(_timestamp_s(frame) for frame in ordered)
    sampled = []
    used: set[int] = set()
    target = 0.0
    epsilon = step_s / 1_000_000.0
    while target <= duration_s + epsilon:
        nearest = min(
            ordered,
            key=lambda frame: (
                abs(_timestamp_s(frame) - target),
                _timestamp_s(frame),
                _frame_index(frame),
            ),
        )
        index = _frame_index(nearest)
        if index not in used:
            sampled.append(nearest)
            used.add(index)
        target += step_s
    return sampled


def active_scenarios_from_events(events: list[Any], frame: int) -> list[str]:
    return sorted(
        {
            str(item["scenario"])
            for item in (_event_dict(event) for event in events)
            if item.get("scenario") is not None
            and int(item["start_frame"]) <= frame <= int(item["end_frame"])
        }
    )


def frame_tag_payload(
    *,
    recording_id: str,
    frame: dict[str, Any],
    events: list[Any],
    scenarios: list[str],
    rule_config_version: str | None = None,
    source_event_json: str | None = None,
) -> dict[str, Any]:
    index = _frame_index(frame)
    active = set(active_scenarios_from_events(events, index))
    return {
        "schema_version": SCHEMA_VERSION,
        "recording_id": recording_id,
        "frame": index,
        "timestamp_s": _timestamp_s(frame),
        "source_event_json": source_event_json,
        "rule_config_version": rule_config_version,
        "sample_rate_hz": DEFAULT_SAMPLE_RATE_HZ,
        "sampling": "nearest_original_frame_to_integer_second",
        "tags": {
            "motional_scenarios": {
                scenario: scenario in active
                for scenario in scenarios
            }
        },
    }


def export_frame_tag_files(
    *,
    recording_id: str,
    frames: list[dict[str, Any]],
    events: list[Any],
    output_dir: Path,
    scenarios: list[str],
    rule_config_version: str | None = None,
    source_event_json: str | None = None,
    sample_rate_hz: float = DEFAULT_SAMPLE_RATE_HZ,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    sampled = sample_frames_nearest_1fps(frames, sample_rate_hz=sample_rate_hz)
    rows = []
    for frame in sampled:
        payload = frame_tag_payload(
            recording_id=recording_id,
            frame=frame,
            events=events,
            scenarios=scenarios,
            rule_config_version=rule_config_version,
            source_event_json=source_event_json,
        )
        path = output_dir / f"frame_{payload['frame']:06d}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        rows.append(
            {
                "frame": payload["frame"],
                "timestamp_s": payload["timestamp_s"],
                "path": path.name,
            }
        )
    manifest = {
        "schema_version": "motional-scenario-frame-tags-1fps-manifest-v1",
        "recording_id": recording_id,
        "source_event_json": source_event_json,
        "rule_config_version": rule_config_version,
        "sample_rate_hz": sample_rate_hz,
        "sampling": "nearest_original_frame_to_integer_second",
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
        "frame_count": len(rows),
        "frames": rows,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def export_frame_tags_from_event_json(
    *,
    canonical_path: Path,
    event_json_path: Path,
    output_dir: Path,
    sample_rate_hz: float = DEFAULT_SAMPLE_RATE_HZ,
) -> dict[str, Any]:
    canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
    event_payload = json.loads(event_json_path.read_text(encoding="utf-8"))
    events = event_payload.get("rule_based_events") or []
    return export_frame_tag_files(
        recording_id=event_payload.get("recording_id") or canonical["recording_id"],
        frames=canonical.get("frames", []),
        events=events,
        output_dir=output_dir,
        scenarios=scenario_key_set(
            event_payload=event_payload,
            events=events,
            configured_scenarios=canonical.get("scenario_taxonomy") or [],
        ),
        rule_config_version=event_payload.get("rule_config_version"),
        source_event_json=str(event_json_path),
        sample_rate_hz=sample_rate_hz,
    )


def active_scenarios_from_event_json(event_payload: dict[str, Any], frame: int) -> list[str]:
    return active_scenarios_from_events(event_payload.get("rule_based_events") or [], frame)


def active_scenarios_from_frame_json(frame_payload: dict[str, Any]) -> list[str]:
    tags = ((frame_payload.get("tags") or {}).get("motional_scenarios") or {})
    return sorted(str(scenario) for scenario, active in tags.items() if active is True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export 1 FPS frame scenario-tag JSON files from an existing event JSON."
    )
    parser.add_argument("--canonical-json", type=Path, required=True)
    parser.add_argument("--event-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sample-rate-hz", type=float, default=DEFAULT_SAMPLE_RATE_HZ)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = export_frame_tags_from_event_json(
        canonical_path=args.canonical_json,
        event_json_path=args.event_json,
        output_dir=args.output_dir,
        sample_rate_hz=args.sample_rate_hz,
    )
    print(
        f"Wrote {manifest['frame_count']} frame tag files with "
        f"{manifest['scenario_count']} scenarios to {args.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
