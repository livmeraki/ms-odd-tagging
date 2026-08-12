from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .score_prediction import combine_gt_and_prediction

# F1 policy: score only dimensions that have actually been manually GT'd.
# Explicitly excluded for now:
# - traffic_relation.trail
# - road_context.intersection
# - road_context.traffic_light_relevant
# - road_context.on_stopline_crosswalk
# - all interaction_tags
# traffic_light_intersection remains active because it is a separately reviewed field.
SCALAR_FIELDS = {
    "ego_motion.state": ["stationary", "moving", "starting", "stopping", "unknown"],
    "ego_motion.speed_band": ["low", "medium", "high", "unknown"],
    "ego_maneuver.type": ["lane_keeping", "lane_change", "turn", "u_turn", "unknown"],
    "ego_maneuver.direction": ["left", "right", "straight", None],
    "traffic_relation.lead": ["present", "absent", "unknown"],
    "road_context.traffic_light_intersection": ["yes", "no", "unknown"],
}

EXCLUDED_F1_FIELDS = [
    "traffic_relation.trail",
    "road_context.intersection",
    "road_context.traffic_light_relevant",
    "road_context.on_stopline_crosswalk",
    "interaction_tags.*",
]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _prediction_path(prediction_root: Path, recording: str) -> Path:
    return prediction_root / f"{recording}_simplified_prediction.json"


def _get_path(data: dict[str, Any], path: str) -> Any:
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _metric(counts: Counter) -> dict[str, Any]:
    tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def _field_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scalar_counts = {path: Counter() for path in SCALAR_FIELDS}

    for row in rows:
        gt = row.get("gt") if isinstance(row.get("gt"), dict) else {}
        pred = row.get("prediction") if isinstance(row.get("prediction"), dict) else {}
        for path in SCALAR_FIELDS:
            g = _get_path(gt, path)
            p = _get_path(pred, path)
            if g in ("unknown", None):
                continue
            if p == g:
                scalar_counts[path]["tp"] += 1
            else:
                scalar_counts[path]["fp"] += 1
                scalar_counts[path]["fn"] += 1

    scalar = {name: _metric(counts) for name, counts in scalar_counts.items()}
    all_metrics = list(scalar.values())
    total = Counter()
    for counts in scalar_counts.values():
        total["tp"] += counts["tp"]
        total["fp"] += counts["fp"]
        total["fn"] += counts["fn"]

    return {
        "reviewed_frames": len(rows),
        "scalar_fields": scalar,
        "interaction_tags": {},
        "macro_f1": sum(m["f1"] for m in all_metrics) / len(all_metrics) if all_metrics else 0.0,
        "micro": _metric(total),
    }


def _simplified_scenario_set(tags: dict[str, Any]) -> set[str]:
    """Flatten only GT-reviewed simplified dimensions into scenario labels."""
    if not isinstance(tags, dict):
        return set()

    scenarios: set[str] = set()

    state = _get_path(tags, "ego_motion.state")
    if state == "stationary":
        scenarios.add("stationary")
    elif state == "starting":
        scenarios.add("start")
    elif state == "stopping":
        scenarios.add("stop")
    elif state == "moving":
        scenarios.add("moving")

    speed = _get_path(tags, "ego_motion.speed_band")
    if speed in {"low", "medium", "high"}:
        scenarios.add(f"{speed}_magnitude_speed")

    maneuver = _get_path(tags, "ego_maneuver.type")
    direction = _get_path(tags, "ego_maneuver.direction")
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

    lead = _get_path(tags, "traffic_relation.lead")
    if lead == "present":
        scenarios.add("with_lead")
    elif lead == "absent":
        scenarios.add("without_lead")

    if _get_path(tags, "road_context.traffic_light_intersection") == "yes":
        scenarios.add("on_traffic_light_intersection")

    return scenarios


def _frame_review(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    counts: dict[str, Counter] = defaultdict(Counter)
    review_rows: list[dict[str, Any]] = []
    exact = overlap = 0

    for row in rows:
        gt = row.get("gt") if isinstance(row.get("gt"), dict) else {}
        pred = row.get("prediction") if isinstance(row.get("prediction"), dict) else {}
        gt_s = _simplified_scenario_set(gt)
        pred_s = _simplified_scenario_set(pred)
        both = gt_s & pred_s
        fp = pred_s - gt_s
        fn = gt_s - pred_s

        for scenario in gt_s | pred_s:
            if scenario in gt_s and scenario in pred_s:
                counts[scenario]["tp"] += 1
            elif scenario in pred_s:
                counts[scenario]["fp"] += 1
            else:
                counts[scenario]["fn"] += 1

        exact_match = not fp and not fn
        exact += int(exact_match)
        overlap += int(bool(both))
        review_rows.append({
            "recording_id": row.get("recording_id"),
            "frame_index": row.get("frame_index"),
            "timestamp": row.get("timestamp"),
            "gt_simplified_scenarios": sorted(gt_s),
            "detected_simplified_scenarios": sorted(pred_s),
            "overlap_tp": sorted(both),
            "detected_only_fp": sorted(fp),
            "gt_only_fn": sorted(fn),
            "exact_match": exact_match,
            "has_overlap": bool(both),
        })

    report = {}
    for scenario, c in sorted(counts.items()):
        report[scenario] = {
            **_metric(c),
            "gt_positive_frames": c["tp"] + c["fn"],
            "detected_positive_frames": c["tp"] + c["fp"],
        }

    total = len(review_rows)
    summary = {
        "comparison_space": "GT-reviewed simplified taxonomy only",
        "excluded_f1_fields": EXCLUDED_F1_FIELDS,
        "frames": total,
        "exact_match_frames": exact,
        "frames_with_any_overlap": overlap,
        "frames_with_no_overlap": total - overlap,
        "exact_match_rate": exact / total if total else 0.0,
        "any_overlap_rate": overlap / total if total else 0.0,
    }
    return report, review_rows, summary


def _build_ranges(rows: list[dict[str, Any]], side: str) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("recording_id"))].append(row)

    ranges: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for recording, rec_rows in grouped.items():
        rec_rows.sort(key=lambda r: (r.get("timestamp") is None, r.get("timestamp"), r.get("frame_index")))
        active: dict[str, dict[str, Any]] = {}

        for position, row in enumerate(rec_rows):
            tags = row.get(side) if isinstance(row.get(side), dict) else {}
            scenarios = _simplified_scenario_set(tags)
            for scenario in list(active):
                if scenario not in scenarios:
                    ranges[(recording, scenario)].append(active.pop(scenario))
            for scenario in scenarios:
                event = active.get(scenario)
                if event is None:
                    active[scenario] = {
                        "recording_id": recording,
                        "scenario": scenario,
                        "start_frame": row.get("frame_index"),
                        "end_frame": row.get("frame_index"),
                        "start_timestamp": row.get("timestamp"),
                        "end_timestamp": row.get("timestamp"),
                        "sample_positions": {position},
                    }
                else:
                    event["end_frame"] = row.get("frame_index")
                    event["end_timestamp"] = row.get("timestamp")
                    event["sample_positions"].add(position)
        for scenario, event in active.items():
            ranges[(recording, scenario)].append(event)
    return ranges


def _range_review(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    gt_ranges = _build_ranges(rows, "gt")
    pred_ranges = _build_ranges(rows, "prediction")
    keys = sorted(set(gt_ranges) | set(pred_ranges))
    scenario_counts: dict[str, Counter] = defaultdict(Counter)
    review: list[dict[str, Any]] = []

    for recording, scenario in keys:
        gt_events = gt_ranges.get((recording, scenario), [])
        pred_events = pred_ranges.get((recording, scenario), [])
        candidates: list[tuple[int, float, int, int]] = []
        for gi, gt_event in enumerate(gt_events):
            for pi, pred_event in enumerate(pred_events):
                overlap = len(gt_event["sample_positions"] & pred_event["sample_positions"])
                if overlap:
                    union = len(gt_event["sample_positions"] | pred_event["sample_positions"])
                    candidates.append((overlap, overlap / union if union else 0.0, gi, pi))

        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        matched_gt: set[int] = set()
        matched_pred: set[int] = set()
        for overlap, iou, gi, pi in candidates:
            if gi in matched_gt or pi in matched_pred:
                continue
            matched_gt.add(gi)
            matched_pred.add(pi)
            scenario_counts[scenario]["tp"] += 1
            g, p = gt_events[gi], pred_events[pi]
            review.append({
                "recording_id": recording, "scenario": scenario, "result": "TP",
                "gt_start_frame": g["start_frame"], "gt_end_frame": g["end_frame"],
                "detected_start_frame": p["start_frame"], "detected_end_frame": p["end_frame"],
                "overlap_sampled_frames": overlap, "range_iou": iou,
            })

        for gi, g in enumerate(gt_events):
            if gi not in matched_gt:
                scenario_counts[scenario]["fn"] += 1
                review.append({
                    "recording_id": recording, "scenario": scenario, "result": "FN",
                    "gt_start_frame": g["start_frame"], "gt_end_frame": g["end_frame"],
                    "detected_start_frame": None, "detected_end_frame": None,
                    "overlap_sampled_frames": 0, "range_iou": 0.0,
                })
        for pi, p in enumerate(pred_events):
            if pi not in matched_pred:
                scenario_counts[scenario]["fp"] += 1
                review.append({
                    "recording_id": recording, "scenario": scenario, "result": "FP",
                    "gt_start_frame": None, "gt_end_frame": None,
                    "detected_start_frame": p["start_frame"], "detected_end_frame": p["end_frame"],
                    "overlap_sampled_frames": 0, "range_iou": 0.0,
                })

    report = {}
    for scenario, counts in sorted(scenario_counts.items()):
        report[scenario] = {
            **_metric(counts),
            "gt_events": counts["tp"] + counts["fn"],
            "detected_events": counts["tp"] + counts["fp"],
        }
    return report, review


def _csv_list(value: list[str]) -> str:
    return " | ".join(value)


def _write_review_csvs(
    review_dir: Path,
    scenario_report: dict[str, Any],
    frame_report: dict[str, Any],
    frame_rows: list[dict[str, Any]],
    range_rows: list[dict[str, Any]],
) -> None:
    review_dir.mkdir(parents=True, exist_ok=True)
    with (review_dir / "scenario_f1.csv").open("w", newline="", encoding="utf-8-sig") as f:
        fields = ["scenario", "tp", "fp", "fn", "gt_events", "detected_events", "precision", "recall", "f1"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for scenario, metric in scenario_report.items():
            writer.writerow({"scenario": scenario, **metric})

    with (review_dir / "frame_scenario_f1.csv").open("w", newline="", encoding="utf-8-sig") as f:
        fields = ["scenario", "tp", "fp", "fn", "gt_positive_frames", "detected_positive_frames", "precision", "recall", "f1"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for scenario, metric in frame_report.items():
            writer.writerow({"scenario": scenario, **metric})

    frame_fields = [
        "recording_id", "frame_index", "timestamp", "gt_simplified_scenarios",
        "detected_simplified_scenarios", "overlap_tp", "detected_only_fp", "gt_only_fn",
        "exact_match", "has_overlap",
    ]
    for filename, predicate in (
        ("frame_review.csv", lambda row: True),
        ("overlap_frames.csv", lambda row: row["has_overlap"]),
        ("error_frames.csv", lambda row: not row["exact_match"]),
    ):
        with (review_dir / filename).open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=frame_fields)
            writer.writeheader()
            for row in frame_rows:
                if not predicate(row):
                    continue
                out = dict(row)
                for key in ("gt_simplified_scenarios", "detected_simplified_scenarios", "overlap_tp", "detected_only_fp", "gt_only_fn"):
                    out[key] = _csv_list(out[key])
                writer.writerow(out)

    range_fields = [
        "recording_id", "scenario", "result", "gt_start_frame", "gt_end_frame",
        "detected_start_frame", "detected_end_frame", "overlap_sampled_frames", "range_iou",
    ]
    with (review_dir / "range_review.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=range_fields)
        writer.writeheader()
        writer.writerows(range_rows)


def aggregate_finished_gt(gt_root: Path, prediction_root: Path, *, finished_only: bool = True) -> dict[str, Any]:
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
            recordings.append({"recording_id": recording, "status": "missing_prediction"})
            continue
        try:
            combined = combine_gt_and_prediction(gt_doc, _load_json(prediction_path))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            recordings.append({"recording_id": recording, "status": "score_error", "error": str(exc)})
            continue

        for row in combined["frames"]:
            combined_rows.append({**row, "recording_id": recording})
        missing = combined["missing_prediction_frames"]
        if missing:
            missing_prediction_frames[recording] = missing
        recordings.append({
            "recording_id": recording, "status": "scored",
            "gt_finished": gt_doc.get("gt_finished") is True,
            "reviewed_frames": len(combined["frames"]),
            "missing_prediction_frames": len(missing),
        })

    report = _field_metrics(combined_rows)
    frame_scenario_f1, frame_review, frame_summary = _frame_review(combined_rows)
    scenario_f1, range_review = _range_review(combined_rows)
    report.update({
        "aggregation": "all reviewed frames pooled before field metric computation",
        "f1_policy": "only manually GT-reviewed simplified dimensions are scored",
        "active_f1_fields": list(SCALAR_FIELDS),
        "excluded_f1_fields": EXCLUDED_F1_FIELDS,
        "scenario_metric": "one-to-one overlapping simplified scenario ranges; any sampled-frame overlap is a TP event",
        "scenario_comparison_space": "GT-reviewed simplified taxonomy on GT and detection",
        "finished_only": finished_only,
        "gt_files_found": len(gt_files),
        "scored_recordings": sum(1 for item in recordings if item.get("status") == "scored"),
        "skipped_unfinished_count": len(skipped_unfinished),
        "missing_prediction_recordings_count": len(missing_predictions),
        "missing_prediction_frames_count": sum(len(v) for v in missing_prediction_frames.values()),
        "skipped_unfinished": skipped_unfinished,
        "missing_prediction_recordings": missing_predictions,
        "missing_prediction_frames": missing_prediction_frames,
        "recordings": recordings,
        "scenario_f1": scenario_f1,
        "frame_scenario_f1": frame_scenario_f1,
        "frame_review_summary": frame_summary,
        "frame_review": frame_review,
        "range_review": range_review,
    })
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate simplified-taxonomy F1 across manual GT recordings.")
    parser.add_argument("--gt-root", type=Path, default=Path("outputs/06_gt_comparison/gt"))
    parser.add_argument("--prediction-root", type=Path, default=Path("outputs/06_gt_comparison/predictions"))
    parser.add_argument("--output", type=Path, default=Path("outputs/06_gt_comparison/aggregate_f1.json"))
    parser.add_argument("--review-dir", type=Path, default=Path("outputs/06_gt_comparison/f1_review"))
    parser.add_argument("--include-unfinished", action="store_true")
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
    _write_review_csvs(args.review_dir, report["scenario_f1"], report["frame_scenario_f1"], report["frame_review"], report["range_review"])

    micro = report["micro"]
    review = report["frame_review_summary"]
    print(f"Scored recordings: {report['scored_recordings']}")
    print(f"Reviewed frames: {report['reviewed_frames']}")
    print("Active F1 fields: " + ", ".join(report["active_f1_fields"]))
    print("Excluded from F1: " + ", ".join(report["excluded_f1_fields"]))
    print(f"Micro precision: {micro['precision']:.4f}")
    print(f"Micro recall: {micro['recall']:.4f}")
    print(f"Micro F1: {micro['f1']:.4f}")
    print(f"Macro F1: {report['macro_f1']:.4f}")
    print("Scenario F1: simplified GT vs simplified detection, overlap-matched by range")
    print(f"Scenario classes: {len(report['scenario_f1'])}")
    print(f"Exact-match frames: {review['exact_match_frames']}/{review['frames']} ({review['exact_match_rate']:.4f})")
    print(f"Frames with detected/GT overlap: {review['frames_with_any_overlap']}/{review['frames']} ({review['any_overlap_rate']:.4f})")
    print(f"Missing prediction frames: {report['missing_prediction_frames_count']}")
    print(f"Aggregate F1 report: {args.output}")
    print(f"F1 review CSVs: {args.review_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
