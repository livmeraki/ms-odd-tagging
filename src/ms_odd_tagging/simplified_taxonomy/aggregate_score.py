from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .manual_gt import evaluate_gt
from .score_prediction import combine_gt_and_prediction


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _prediction_path(prediction_root: Path, recording: str) -> Path:
    return prediction_root / f"{recording}_simplified_prediction.json"


def _get(data: dict[str, Any], *parts: str) -> Any:
    cur: Any = data
    for part in parts:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _simplified_scenario_set(tags: dict[str, Any]) -> set[str]:
    """Flatten simplified-taxonomy tags into comparable scenario labels.

    This intentionally accepts only the simplified tag object. Raw detector
    scenario_tags are never used for F1 comparison, so prediction and GT are
    evaluated in the same simplified scenario space.
    """
    if not isinstance(tags, dict):
        return set()

    scenarios: set[str] = set()

    state = _get(tags, "ego_motion", "state")
    if state == "stationary":
        scenarios.add("stationary")
    elif state == "starting":
        scenarios.add("start")
    elif state == "stopping":
        scenarios.add("stop")
    elif state == "moving":
        scenarios.add("moving")

    speed = _get(tags, "ego_motion", "speed_band")
    if speed in {"low", "medium", "high"}:
        scenarios.add(f"{speed}_magnitude_speed")

    maneuver = _get(tags, "ego_maneuver", "type")
    direction = _get(tags, "ego_maneuver", "direction")
    if maneuver == "lane_keeping":
        scenarios.add("lane_keeping")
    elif maneuver == "lane_change":
        suffix = direction if direction in {"left", "right"} else "unknown_direction"
        scenarios.add(f"lane_changing_{suffix}")
    elif maneuver == "turn":
        suffix = direction if direction in {"left", "right"} else "unknown_direction"
        scenarios.add(f"turn_{suffix}")
    elif maneuver == "u_turn":
        scenarios.add("u_turn")

    lead = _get(tags, "traffic_relation", "lead")
    if lead == "present":
        scenarios.add("with_lead")
    elif lead == "absent":
        scenarios.add("without_lead")

    trail = _get(tags, "traffic_relation", "trail")
    if trail == "present":
        scenarios.add("with_trail")
    elif trail == "absent":
        scenarios.add("without_trail")

    road = tags.get("road_context") if isinstance(tags.get("road_context"), dict) else {}
    if road.get("intersection") == "yes":
        scenarios.add("on_intersection")
    if road.get("traffic_light_intersection") == "yes":
        scenarios.add("on_traffic_light_intersection")
    if road.get("traffic_light_relevant") == "yes":
        scenarios.add("on_traffic_light")
    if road.get("on_stopline_crosswalk") == "yes":
        scenarios.add("on_stopline_crosswalk")

    for tag in tags.get("interaction_tags") or []:
        if isinstance(tag, str) and tag:
            scenarios.add(tag)

    return scenarios


def _metric(counts: Counter) -> dict[str, Any]:
    tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "gt_positive_frames": tp + fn,
        "detected_positive_frames": tp + fp,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _scenario_and_frame_review(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    scenario_counts: dict[str, Counter] = {}
    frame_review: list[dict[str, Any]] = []
    exact = overlap = no_overlap = 0

    for row in rows:
        gt = row.get("gt") if isinstance(row.get("gt"), dict) else {}
        pred = row.get("prediction") if isinstance(row.get("prediction"), dict) else {}

        # Both sides are flattened from the same simplified taxonomy.
        gt_scenarios = _simplified_scenario_set(gt)
        detected_scenarios = _simplified_scenario_set(pred)
        both = gt_scenarios & detected_scenarios
        fp = detected_scenarios - gt_scenarios
        fn = gt_scenarios - detected_scenarios

        all_scenarios = gt_scenarios | detected_scenarios
        for scenario in all_scenarios:
            counts = scenario_counts.setdefault(scenario, Counter())
            in_gt = scenario in gt_scenarios
            in_pred = scenario in detected_scenarios
            if in_gt and in_pred:
                counts["tp"] += 1
            elif in_pred:
                counts["fp"] += 1
            else:
                counts["fn"] += 1

        exact_match = not fp and not fn
        has_overlap = bool(both)
        if exact_match:
            exact += 1
        if has_overlap:
            overlap += 1
        else:
            no_overlap += 1

        frame_review.append({
            "recording_id": row.get("recording_id"),
            "frame_index": row.get("frame_index"),
            "timestamp": row.get("timestamp"),
            "gt_simplified_scenarios": sorted(gt_scenarios),
            "detected_simplified_scenarios": sorted(detected_scenarios),
            "overlap_tp": sorted(both),
            "detected_only_fp": sorted(fp),
            "gt_only_fn": sorted(fn),
            "exact_match": exact_match,
            "has_overlap": has_overlap,
        })

    scenario_report = {
        name: _metric(counts)
        for name, counts in sorted(scenario_counts.items())
    }
    summary = {
        "comparison_space": "simplified taxonomy scenarios on both GT and detection",
        "frames": len(frame_review),
        "exact_match_frames": exact,
        "frames_with_any_overlap": overlap,
        "frames_with_no_overlap": no_overlap,
        "exact_match_rate": exact / len(frame_review) if frame_review else 0.0,
        "any_overlap_rate": overlap / len(frame_review) if frame_review else 0.0,
    }
    return scenario_report, frame_review, summary


def _write_review_csvs(review_dir: Path, scenario_report: dict[str, Any], frame_review: list[dict[str, Any]]) -> None:
    review_dir.mkdir(parents=True, exist_ok=True)

    with (review_dir / "scenario_f1.csv").open("w", newline="", encoding="utf-8-sig") as f:
        fields = [
            "scenario", "tp", "fp", "fn", "gt_positive_frames", "detected_positive_frames",
            "precision", "recall", "f1",
        ]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for scenario, metric in scenario_report.items():
            writer.writerow({"scenario": scenario, **metric})

    fields = [
        "recording_id", "frame_index", "timestamp", "gt_simplified_scenarios",
        "detected_simplified_scenarios", "overlap_tp", "detected_only_fp", "gt_only_fn",
        "exact_match", "has_overlap",
    ]
    list_fields = (
        "gt_simplified_scenarios", "detected_simplified_scenarios", "overlap_tp",
        "detected_only_fp", "gt_only_fn",
    )

    with (review_dir / "frame_review.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in frame_review:
            out = dict(row)
            for key in list_fields:
                out[key] = " | ".join(out[key])
            writer.writerow(out)

    with (review_dir / "overlap_frames.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in frame_review:
            if not row["has_overlap"]:
                continue
            out = dict(row)
            for key in list_fields:
                out[key] = " | ".join(out[key])
            writer.writerow(out)

    with (review_dir / "error_frames.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in frame_review:
            if row["exact_match"]:
                continue
            out = dict(row)
            for key in list_fields:
                out[key] = " | ".join(out[key])
            writer.writerow(out)


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
            recordings.append({"recording_id": gt_path.stem, "status": "invalid_gt", "error": str(exc)})
            continue

        if not isinstance(gt_doc, dict):
            recordings.append({"recording_id": gt_path.stem, "status": "invalid_gt", "error": "GT JSON must be an object"})
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
            recordings.append({"recording_id": recording, "status": "missing_prediction", "gt_finished": gt_doc.get("gt_finished") is True})
            continue

        try:
            prediction_doc = _load_json(prediction_path)
            combined = combine_gt_and_prediction(gt_doc, prediction_doc)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            recordings.append({"recording_id": recording, "status": "score_error", "error": str(exc)})
            continue

        for row in combined["frames"]:
            combined_rows.append({**row, "recording_id": recording})
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
    scenario_report, frame_review, frame_review_summary = _scenario_and_frame_review(combined_rows)
    scored_recordings = sum(1 for item in recordings if item.get("status") == "scored")
    report.update({
        "aggregation": "all reviewed frames pooled before metric computation",
        "scenario_comparison_space": "simplified taxonomy on both GT and detection; raw scenario_tags excluded",
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
        "scenario_f1": scenario_report,
        "frame_review_summary": frame_review_summary,
        "frame_review": frame_review,
    })
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate simplified-taxonomy F1 across manual GT recordings.")
    parser.add_argument("--gt-root", type=Path, default=Path("outputs/06_gt_comparison/gt"))
    parser.add_argument("--prediction-root", type=Path, default=Path("outputs/06_gt_comparison/predictions"))
    parser.add_argument("--output", type=Path, default=Path("outputs/06_gt_comparison/aggregate_f1.json"))
    parser.add_argument(
        "--review-dir",
        type=Path,
        default=Path("outputs/06_gt_comparison/f1_review"),
        help="Write simplified scenario_f1.csv, frame_review.csv, overlap_frames.csv, and error_frames.csv.",
    )
    parser.add_argument("--include-unfinished", action="store_true", help="Also score GT files not explicitly marked gt_finished=true.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.gt_root.is_dir():
        raise SystemExit(f"GT root does not exist: {args.gt_root}")
    if not args.prediction_root.is_dir():
        raise SystemExit(f"Prediction root does not exist: {args.prediction_root}")

    report = aggregate_finished_gt(args.gt_root, args.prediction_root, finished_only=not args.include_unfinished)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_review_csvs(args.review_dir, report["scenario_f1"], report["frame_review"])

    micro = report["micro"]
    review = report["frame_review_summary"]
    print(f"Scored recordings: {report['scored_recordings']}")
    print(f"Reviewed frames: {report['reviewed_frames']}")
    print(f"Micro precision: {micro['precision']:.4f}")
    print(f"Micro recall: {micro['recall']:.4f}")
    print(f"Micro F1: {micro['f1']:.4f}")
    print(f"Macro F1: {report['macro_f1']:.4f}")
    print(f"Scenario F1 comparison: simplified GT vs simplified detection")
    print(f"Scenario classes: {len(report['scenario_f1'])}")
    print(f"Exact-match frames: {review['exact_match_frames']}/{review['frames']} ({review['exact_match_rate']:.4f})")
    print(f"Frames with detected/GT overlap: {review['frames_with_any_overlap']}/{review['frames']} ({review['any_overlap_rate']:.4f})")
    print(f"Missing prediction frames: {report['missing_prediction_frames_count']}")
    print(f"Aggregate F1 report: {args.output}")
    print(f"F1 review CSVs: {args.review_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
