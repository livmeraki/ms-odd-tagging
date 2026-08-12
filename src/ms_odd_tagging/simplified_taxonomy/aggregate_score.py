from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .manual_gt import evaluate_gt
from .score_prediction import combine_gt_and_prediction


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _prediction_path(prediction_root: Path, recording: str) -> Path:
    return prediction_root / f"{recording}_simplified_prediction.json"


def aggregate_finished_gt(
    gt_root: Path,
    prediction_root: Path,
    *,
    finished_only: bool = True,
) -> dict[str, Any]:
    combined_rows: list[dict[str, Any]] = []
    recordings: list[dict[str, Any]] = []
    skipped_unfinished: list[str] = []
    missing_predictions: list[str] = []
    missing_prediction_frames: dict[str, list[int]] = {}

    gt_files = sorted(gt_root.glob("*_manual_gt.json"))
    for gt_path in gt_files:
        try:
            gt_doc = _load_json(gt_path)
        except (OSError, json.JSONDecodeError) as exc:
            recordings.append({
                "recording_id": gt_path.stem,
                "status": "invalid_gt",
                "error": str(exc),
            })
            continue

        if not isinstance(gt_doc, dict):
            recordings.append({
                "recording_id": gt_path.stem,
                "status": "invalid_gt",
                "error": "GT JSON must be an object",
            })
            continue

        recording = gt_doc.get("recording_id")
        if not isinstance(recording, str) or not recording:
            recording = gt_path.name.removesuffix("_manual_gt.json")

        if finished_only and gt_doc.get("gt_finished") is not True:
            skipped_unfinished.append(recording)
            continue

        prediction_path = _prediction_path(prediction_root, recording)
        if not prediction_path.is_file():
            missing_predictions.append(recording)
            recordings.append({
                "recording_id": recording,
                "status": "missing_prediction",
                "gt_finished": gt_doc.get("gt_finished") is True,
            })
            continue

        try:
            prediction_doc = _load_json(prediction_path)
            combined = combine_gt_and_prediction(gt_doc, prediction_doc)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            recordings.append({
                "recording_id": recording,
                "status": "score_error",
                "error": str(exc),
            })
            continue

        combined_rows.extend(combined["frames"])
        missing = combined["missing_prediction_frames"]
        if missing:
            missing_prediction_frames[recording] = missing
        recordings.append({
            "recording_id": recording,
            "status": "scored",
            "gt_finished": gt_doc.get("gt_finished") is True,
            "reviewed_frames": len(combined["frames"]),
            "missing_prediction_frames": len(missing),
        })

    report = evaluate_gt({"frames": combined_rows})
    scored_recordings = sum(1 for item in recordings if item.get("status") == "scored")
    report.update({
        "aggregation": "all reviewed frames pooled before metric computation",
        "finished_only": finished_only,
        "gt_files_found": len(gt_files),
        "scored_recordings": scored_recordings,
        "skipped_unfinished_count": len(skipped_unfinished),
        "missing_prediction_recordings_count": len(missing_predictions),
        "missing_prediction_frames_count": sum(len(v) for v in missing_prediction_frames.values()),
        "skipped_unfinished": skipped_unfinished,
        "missing_prediction_recordings": missing_predictions,
        "missing_prediction_frames": missing_prediction_frames,
        "recordings": recordings,
    })
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate simplified-taxonomy F1 across manual GT recordings."
    )
    parser.add_argument(
        "--gt-root",
        type=Path,
        default=Path("outputs/06_gt_comparison/gt"),
    )
    parser.add_argument(
        "--prediction-root",
        type=Path,
        default=Path("outputs/06_gt_comparison/predictions"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/06_gt_comparison/aggregate_f1.json"),
    )
    parser.add_argument(
        "--include-unfinished",
        action="store_true",
        help="Also score GT files not explicitly marked gt_finished=true.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.gt_root.is_dir():
        raise SystemExit(f"GT root does not exist: {args.gt_root}")
    if not args.prediction_root.is_dir():
        raise SystemExit(f"Prediction root does not exist: {args.prediction_root}")

    report = aggregate_finished_gt(
        args.gt_root,
        args.prediction_root,
        finished_only=not args.include_unfinished,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    micro = report["micro"]
    print(f"Scored recordings: {report['scored_recordings']}")
    print(f"Reviewed frames: {report['reviewed_frames']}")
    print(f"Micro precision: {micro['precision']:.4f}")
    print(f"Micro recall: {micro['recall']:.4f}")
    print(f"Micro F1: {micro['f1']:.4f}")
    print(f"Macro F1: {report['macro_f1']:.4f}")
    print(f"Missing prediction frames: {report['missing_prediction_frames_count']}")
    print(f"Aggregate F1 report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
