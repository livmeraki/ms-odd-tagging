from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from .manual_gt import _html

_FRAME_RE = re.compile(r"^frame_(\d+)$")


def _frame_index(frame_dir: Path, frame: dict[str, Any]) -> int | None:
    value = frame.get("frame_index")
    if isinstance(value, int):
        return value
    match = _FRAME_RE.match(frame_dir.name)
    return int(match.group(1)) if match else None


def _timestamp(frame: dict[str, Any]) -> float | None:
    for key in ("timestamp", "timestamp_unix_s", "time_since_start_s"):
        value = frame.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def discover_completed_rows(
    recording_dir: Path,
    *,
    source_hz: float = 10.0,
    sample_hz: float = 1.0,
) -> list[dict[str, Any]]:
    """Snapshot only fully readable input frames without modifying the generator output.

    A frame is considered usable only when both frame.json and bev_revised.png exist
    and frame.json parses successfully. Partially-written/in-progress frame folders are
    silently skipped so this can be run while frame generation continues.
    """
    if source_hz <= 0 or sample_hz <= 0:
        raise ValueError("source_hz and sample_hz must be positive")
    if not recording_dir.is_dir():
        raise ValueError(f"recording directory does not exist: {recording_dir}")

    step = max(1, round(source_hz / sample_hz))
    rows: list[dict[str, Any]] = []
    for frame_dir in sorted(recording_dir.glob("frame_*")):
        if not frame_dir.is_dir():
            continue
        frame_json = frame_dir / "frame.json"
        bev_png = frame_dir / "bev_revised.png"
        if not frame_json.is_file() or not bev_png.is_file():
            continue
        try:
            frame = json.loads(frame_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(frame, dict):
            continue
        idx = _frame_index(frame_dir, frame)
        if idx is None or idx % step != 0:
            continue
        rows.append(
            {
                "frame_index": idx,
                "timestamp": _timestamp(frame),
                "prediction": {},
                "bev_uri": bev_png.resolve().as_uri(),
                "gt": None,
                "reviewed": False,
            }
        )
    rows.sort(key=lambda row: row["frame_index"])
    return rows


def generate_review_from_input_frames(
    recording_dir: Path,
    output_html: Path,
    *,
    source_hz: float = 10.0,
    sample_hz: float = 1.0,
) -> Path:
    rows = discover_completed_rows(
        recording_dir,
        source_hz=source_hz,
        sample_hz=sample_hz,
    )
    if not rows:
        raise ValueError(
            "no completed frames found; expected frame_XXXXXX/frame.json and bev_revised.png"
        )
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(_html(rows, recording_dir.name, sample_hz), encoding="utf-8")
    return output_html


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate manual GT HTML directly from completed frame_inputs_revised folders. "
            "The source recording directory is read-only and incomplete frames are skipped."
        )
    )
    parser.add_argument(
        "recording_dir",
        type=Path,
        help="outputs/02_frame_inputs_revised/<recording>",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/06_gt_comparison/input_frame_manual_gt.html"),
    )
    parser.add_argument("--source-hz", type=float, default=10.0)
    parser.add_argument("--sample-hz", type=float, default=1.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = discover_completed_rows(
        args.recording_dir,
        source_hz=args.source_hz,
        sample_hz=args.sample_hz,
    )
    if not rows:
        raise SystemExit(
            "No completed frames found. Waiting/incomplete frame folders were not touched."
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        _html(rows, args.recording_dir.name, args.sample_hz),
        encoding="utf-8",
    )
    print(f"Completed input frames in snapshot: {len(rows)}")
    print(f"Frame range: {rows[0]['frame_index']}..{rows[-1]['frame_index']}")
    print(f"Manual GT review: {args.output}")
    print("Source recording directory was read-only; incomplete frames were skipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
