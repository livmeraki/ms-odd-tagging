from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .mapper import map_scenario_labels

SCENARIO_KEYS = (
    "scenarios",
    "scenario_tags",
    "tags",
    "scenario_labels",
    "tagged_scenarios",
)
FRAME_CONTAINER_KEYS = ("frames", "frame_tags", "results")
EVENT_CONTAINER_KEYS = ("rule_based_events", "events")


def _scenario_labels(frame: dict[str, Any]) -> list[str]:
    """Extract active scenario labels from one frame-level tagging record."""
    for key in SCENARIO_KEYS:
        value = frame.get(key)
        if isinstance(value, list):
            labels: list[str] = []
            for item in value:
                if isinstance(item, str):
                    labels.append(item)
                elif isinstance(item, dict):
                    label = item.get("scenario") or item.get("name") or item.get("label")
                    if isinstance(label, str):
                        labels.append(label)
            return labels
    return []


def _convert_frame(frame: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(frame)
    labels = _scenario_labels(frame)
    out["simplified_tags"] = map_scenario_labels(labels).to_dict()
    return out


def _event_bounds(event: dict[str, Any]) -> tuple[int, int] | None:
    start = event.get("start_frame")
    end = event.get("end_frame")
    if not isinstance(start, int) or not isinstance(end, int):
        return None
    if end < start:
        start, end = end, start
    return start, end


def _following_lane_events(canonical: dict[str, Any]) -> list[dict[str, Any]]:
    """Run the existing following-lane detector and adapt its intervals.

    The main rule-event registry currently uses following-lane output as lane
    context but does not serialize its following_lane_with_lead/without_lead
    intervals. The simplified exporter can include them when canonical input is
    supplied, so lane_keeping is based on real lane-follow evidence rather than
    a motion fallback.
    """
    from ms_odd_tagging.scenarios.following_lane.detector import run_following_lane

    result = run_following_lane(canonical)
    adapted: list[dict[str, Any]] = []
    for interval in result.get("intervals", []):
        if not isinstance(interval, dict):
            continue
        scenario = interval.get("scenario")
        start = interval.get("start_frame_index")
        end = interval.get("end_frame_index")
        if (
            scenario not in {"following_lane_with_lead", "following_lane_without_lead"}
            or not isinstance(start, int)
            or not isinstance(end, int)
        ):
            continue
        adapted.append(
            {
                "scenario": scenario,
                "start_frame": start,
                "end_frame": end,
                "source": "following_lane_detector",
            }
        )
    return adapted


def _convert_event_document(document: dict[str, Any], events: list[Any]) -> dict[str, Any]:
    """Expand interval scenario events into per-frame simplified predictions."""
    valid_events: list[dict[str, Any]] = []
    max_end = -1
    for item in events:
        if not isinstance(item, dict):
            continue
        label = item.get("scenario")
        bounds = _event_bounds(item)
        if not isinstance(label, str) or bounds is None:
            continue
        start, end = bounds
        valid_events.append(item)
        max_end = max(max_end, end)

    if max_end < 0:
        raise ValueError(
            "Event JSON contains no usable scenario intervals. Expected scenario, start_frame and end_frame."
        )

    active: list[list[str]] = [[] for _ in range(max_end + 1)]
    for event in valid_events:
        label = event["scenario"]
        bounds = _event_bounds(event)
        if bounds is None:
            continue
        start, end = bounds
        for frame_index in range(start, end + 1):
            active[frame_index].append(label)

    frames: list[dict[str, Any]] = []
    for frame_index, labels in enumerate(active):
        unique_labels = list(dict.fromkeys(labels))
        frames.append(
            {
                "frame_index": frame_index,
                "scenario_tags": unique_labels,
                "simplified_tags": map_scenario_labels(unique_labels).to_dict(),
            }
        )

    return {
        "schema_version": "simplified-frame-taxonomy-v1",
        "recording_id": document.get("recording_id"),
        "source_schema_version": document.get("schema_version"),
        "source_rule_config_version": document.get("rule_config_version"),
        "source_kind": "scenario_events_expanded_to_frames",
        "frame_count": len(frames),
        "frames": frames,
    }


def convert_frame_document(document: Any, *, extra_events: list[dict[str, Any]] | None = None) -> Any:
    """Convert supported tagging JSON shapes to include simplified per-frame tags."""
    if isinstance(document, list):
        return [_convert_frame(row) if isinstance(row, dict) else deepcopy(row) for row in document]

    if not isinstance(document, dict):
        raise ValueError("tagging JSON must be an object or list")

    for key in FRAME_CONTAINER_KEYS:
        rows = document.get(key)
        if isinstance(rows, list):
            out = deepcopy(document)
            out[key] = [_convert_frame(row) if isinstance(row, dict) else deepcopy(row) for row in rows]
            return out

    for key in EVENT_CONTAINER_KEYS:
        events = document.get(key)
        if isinstance(events, list):
            merged_events = list(events)
            if extra_events:
                merged_events.extend(extra_events)
            return _convert_event_document(document, merged_events)

    if any(isinstance(document.get(key), list) for key in SCENARIO_KEYS):
        return _convert_frame(document)

    if isinstance(document.get("taxonomy"), list):
        raise ValueError(
            "This looks like a frame-input/model-input JSON: 'taxonomy' lists possible labels, not active predictions. "
            "Use a tagging result such as rule_based_scenario_events.json instead."
        )

    raise ValueError(
        "No active scenario labels found. Expected a frame tagging list or a rule_based_events/event interval list."
    )


def default_output_path(input_path: Path) -> Path:
    suffix = input_path.suffix or ".json"
    return input_path.with_name(f"{input_path.stem}_simplified{suffix}")


def export_file(
    input_path: Path,
    output_path: Path | None = None,
    *,
    canonical_path: Path | None = None,
) -> Path:
    output_path = output_path or default_output_path(input_path)
    document = json.loads(input_path.read_text(encoding="utf-8"))
    extra_events: list[dict[str, Any]] = []
    if canonical_path is not None:
        canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
        extra_events = _following_lane_events(canonical)
    converted = convert_frame_document(document, extra_events=extra_events)
    if isinstance(converted, dict) and canonical_path is not None:
        converted["following_lane_events_included"] = len(extra_events)
        converted["following_lane_source"] = str(canonical_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(converted, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write simplified frame-level taxonomy JSON from frame tags or scenario-event intervals."
    )
    parser.add_argument("input", type=Path, help="Existing tagging-result JSON")
    parser.add_argument("--output", type=Path, default=None, help="Output path; defaults to *_simplified.json")
    parser.add_argument(
        "--canonical",
        type=Path,
        default=None,
        help="Optional canonical ODLD JSON. When supplied, run the existing following-lane detector and include its intervals so lane_keeping is generated from lane-follow evidence.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = export_file(args.input, args.output, canonical_path=args.canonical)
    print(f"Simplified frame JSON: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
