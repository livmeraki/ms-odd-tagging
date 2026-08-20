from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .mapper import map_scenario_labels

FRAME_TAG_DIRNAME = "recording_frame_tags_1fps"


def frame_tag_dir(recording_dir: Path) -> Path:
    return recording_dir / FRAME_TAG_DIRNAME


def _active_scenarios(document: dict[str, Any]) -> list[str]:
    motional = ((document.get("tags") or {}).get("motional_scenarios") or {})
    if not isinstance(motional, dict):
        return []
    return sorted(str(name) for name, active in motional.items() if active is True)


def _frame_tag_records(recording_dir: Path) -> list[dict[str, Any]]:
    """Load current 1-FPS frame tags with frame index, timestamp and mapped tags."""
    directory = frame_tag_dir(recording_dir)
    if not directory.is_dir():
        return []

    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("frame_*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(document, dict):
            continue
        value = document.get("frame", document.get("frame_index"))
        if not isinstance(value, int):
            continue
        timestamp = document.get("timestamp_s")
        if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool):
            timestamp = None
        labels = _active_scenarios(document)
        records.append(
            {
                "frame_index": value,
                "timestamp": float(timestamp) if timestamp is not None else None,
                "prediction": map_scenario_labels(labels).to_dict(),
            }
        )
    return records


def load_current_frame_predictions(recording_dir: Path) -> dict[int, dict[str, Any]]:
    """Return current mapped predictions keyed by their source frame index."""
    return {
        int(record["frame_index"]): record["prediction"]
        for record in _frame_tag_records(recording_dir)
    }


def current_prediction_tags(recording_dir: Path) -> list[str]:
    """Return active source-scenario names present anywhere in current frame tags."""
    directory = frame_tag_dir(recording_dir)
    if not directory.is_dir():
        return []
    tags: set[str] = set()
    for path in sorted(directory.glob("frame_*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(document, dict):
            tags.update(_active_scenarios(document))
    return sorted(tags)


def apply_current_predictions(
    rows: list[dict[str, Any]],
    recording_dir: Path,
    *,
    prefill_unreviewed: bool = True,
    sample_hz: float = 1.0,
) -> int:
    """Attach current frame-tag predictions to GT editor rows.

    The frame-input generator and the frame-tag exporter use different 1-FPS
    sampling policies. Therefore their sampled source frame indices can differ
    even when they represent the same instant (for example frame 11 vs frame 10).

    Matching policy:
    1. exact source-frame index when available;
    2. otherwise nearest timestamp within half of one requested sample period.

    Existing reviewed GT always wins. Prediction-prefilled rows remain
    ``reviewed=False`` until the annotator explicitly saves/reviews them.
    Returns the number of rows that received a prediction.
    """
    records = _frame_tag_records(recording_dir)
    if not records:
        return 0

    by_index = {int(record["frame_index"]): record for record in records}
    timed = [record for record in records if isinstance(record.get("timestamp"), float)]
    tolerance_s = 0.5 / sample_hz if sample_hz > 0 else 0.5

    matched = 0
    for row in rows:
        row_index = row.get("frame_index")
        record = by_index.get(row_index) if isinstance(row_index, int) else None

        if record is None:
            row_timestamp = row.get("timestamp")
            if isinstance(row_timestamp, (int, float)) and not isinstance(row_timestamp, bool) and timed:
                candidate = min(
                    timed,
                    key=lambda item: abs(float(item["timestamp"]) - float(row_timestamp)),
                )
                delta = abs(float(candidate["timestamp"]) - float(row_timestamp))
                if delta <= tolerance_s + 1e-9:
                    record = candidate

        if record is None:
            continue

        prediction = record.get("prediction")
        if not isinstance(prediction, dict):
            continue
        matched += 1
        row["prediction"] = prediction
        row["prediction_source_frame_index"] = record["frame_index"]
        row["prediction_source_timestamp"] = record.get("timestamp")
        if prefill_unreviewed and row.get("reviewed") is not True:
            row["gt"] = deepcopy(prediction)

    return matched
