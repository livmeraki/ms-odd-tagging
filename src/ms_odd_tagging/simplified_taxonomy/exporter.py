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


def _scenario_labels(frame: dict[str, Any]) -> list[str]:
    """Extract scenario labels from one legacy frame without changing its contents."""
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


def convert_frame_document(document: Any) -> Any:
    """Add ``simplified_tags`` in parallel to an existing frame-level JSON document.

    Supported legacy shapes are deliberately small and non-destructive:
    * a top-level list of frame dictionaries;
    * a dictionary containing ``frames``, ``frame_tags`` or ``results`` as a list;
    * a single frame dictionary.

    Existing fields are preserved byte-for-byte at the value level. Unsupported
    scenario names are retained inside ``simplified_tags.unmapped_scenarios``.
    """
    if isinstance(document, list):
        return [_convert_frame(row) if isinstance(row, dict) else deepcopy(row) for row in document]

    if not isinstance(document, dict):
        raise ValueError("frame JSON must be an object or list")

    for key in FRAME_CONTAINER_KEYS:
        rows = document.get(key)
        if isinstance(rows, list):
            out = deepcopy(document)
            out[key] = [_convert_frame(row) if isinstance(row, dict) else deepcopy(row) for row in rows]
            return out

    return _convert_frame(document)


def default_output_path(input_path: Path) -> Path:
    suffix = input_path.suffix or ".json"
    return input_path.with_name(f"{input_path.stem}_simplified{suffix}")


def export_file(input_path: Path, output_path: Path | None = None) -> Path:
    output_path = output_path or default_output_path(input_path)
    document = json.loads(input_path.read_text(encoding="utf-8"))
    converted = convert_frame_document(document)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(converted, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write a parallel simplified-taxonomy JSON from an existing frame-level tag JSON."
    )
    parser.add_argument("input", type=Path, help="Existing frame-level scenario JSON")
    parser.add_argument("--output", type=Path, default=None, help="Output path; defaults to *_simplified.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = export_file(args.input, args.output)
    print(f"Simplified frame JSON: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
