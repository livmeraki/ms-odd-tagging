from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .manual_gt import evaluate_gt


def _prediction_by_frame(document: Any) -> dict[int, dict[str, Any]]:
    frames = document.get("frames") if isinstance(document, dict) else None
    if not isinstance(frames, list):
        raise ValueError("prediction JSON must contain a top-level frames list")
    result: dict[int, dict[str, Any]] = {}
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        idx = frame.get("frame_index")
        if not isinstance(idx, int):
            continue
        pred = frame.get("simplified_tags")
        if not isinstance(pred, dict):
            required = {"ego_motion", "ego_maneuver", "traffic_relation", "road_context"}
            if required.issubset(frame):
                pred = {
                    key: frame.get(key)
                    for key in (*required, "interaction_tags")
                }
        if isinstance(pred, dict):
            result[idx] = pred
    return result


def combine_gt_and_prediction(gt_doc: Any, prediction_doc: Any) -> dict[str, Any]:
    if not isinstance(gt_doc, dict) or not isinstance(gt_doc.get("frames"), list):
        raise ValueError("GT JSON must contain a top-level frames list")
    predictions = _prediction_by_frame(prediction_doc)
    rows = []
    missing_prediction_frames = []
    for frame in gt_doc["frames"]:
        if not isinstance(frame, dict) or frame.get("reviewed") is not True:
            continue
        idx = frame.get("frame_index")
        gt = frame.get("gt")
        if not isinstance(idx, int) or not isinstance(gt, dict):
            continue
        prediction = predictions.get(idx)
        if prediction is None:
            missing_prediction_frames.append(idx)
            prediction = {}
        rows.append(
            {
                "frame_index": idx,
                "timestamp": frame.get("timestamp"),
                "prediction": prediction,
                "gt": gt,
                "reviewed": True,
            }
        )
    return {
        "recording_id": gt_doc.get("recording_id"),
        "frames": rows,
        "missing_prediction_frames": missing_prediction_frames,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Score autosaved manual GT against simplified per-frame predictions.")
    parser.add_argument("--gt", type=Path, required=True)
    parser.add_argument("--prediction", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    gt_doc = json.loads(args.gt.read_text(encoding="utf-8"))
    prediction_doc = json.loads(args.prediction.read_text(encoding="utf-8"))
    combined = combine_gt_and_prediction(gt_doc, prediction_doc)
    report = evaluate_gt(combined)
    report["recording_id"] = combined.get("recording_id")
    report["missing_prediction_frames"] = combined["missing_prediction_frames"]
    report["matched_prediction_frames"] = report["reviewed_frames"] - len(combined["missing_prediction_frames"])
    text = json.dumps(report, ensure_ascii=False, indent=2)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"F1 report: {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
