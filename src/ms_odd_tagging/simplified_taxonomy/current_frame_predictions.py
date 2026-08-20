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


def load_current_frame_predictions(recording_dir: Path) -> dict[int, dict[str, Any]]:
    """Map current pipeline 1-FPS frame tags into the simplified taxonomy.

    The cleanup pipeline writes one JSON per sampled frame under
    ``recording_frame_tags_1fps``.  This is the canonical prediction source for
    the simplified manual-GT workspace; no duplicate *_simplified_prediction.json
    export is required.
    """
    directory = frame_tag_dir(recording_dir)
    if not directory.is_dir():
        return {}

    predictions: dict[int, dict[str, Any]] = {}
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
        labels = _active_scenarios(document)
        predictions[value] = map_scenario_labels(labels).to_dict()
    return predictions


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
) -> int:
    """Attach current predictions to editor rows and optionally prefill GT.

    Existing reviewed GT always wins.  Prediction-prefilled rows remain
    ``reviewed=False`` until the annotator explicitly saves/reviews them.
    Returns the number of rows with an exact frame-index prediction match.
    """
    predictions = load_current_frame_predictions(recording_dir)
    matched = 0
    for row in rows:
        prediction = predictions.get(row.get("frame_index"))
        if not isinstance(prediction, dict):
            continue
        matched += 1
        row["prediction"] = prediction
        if prefill_unreviewed and row.get("reviewed") is not True:
            row["gt"] = deepcopy(prediction)
    return matched
