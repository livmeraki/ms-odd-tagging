from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
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

    Raw detector scenario_tags are intentionally excluded. Both GT and
    detection are converted from the same simplified taxonomy before scoring.
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


def _metric(counts: Counter, *, unit: str = "frames") -> dict[str, Any]:
    tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        f"gt_positive_{unit}": tp + fn,
        f"detected_positive_{unit}": tp + fp,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _scenario_and_frame_review(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Strict frame-level review kept for timing/error inspection."""
    scenario_counts: dict[str, Counter] = {}
    frame_review: list[dict[str, Any]] = []
    exact = overlap = no_overlap = 0

    for row in rows:
        gt = row.get("gt") if isinstance(row.get("gt"), dict) else {}
        pred = row.get("prediction") if isinstance(row.get("prediction"), dict) else {}

        gt_scenarios = _simplified_scenario_set(gt)
        detected_scenarios = _simplified_scenario_set(pred)
        both = gt_scenarios & detected_scenarios
        fp = detected_scenarios - gt_scenarios
        fn = gt_scenarios - detected_scenarios

        for scenario in gt_scenarios | detected_scenarios:
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
        name: _metric(counts, unit="frames")
        for name, counts in sorted(scenario_counts.items())
    }
    summary = {
        "comparison_space": "simplified taxonomy scenarios on both GT and detection",
        "scoring_unit": "frame",
        "frames": len(frame_review),
        "exact_match_frames": exact,
        "frames_with_any_overlap": overlap,
        "frames_with_no_overlap": no_overlap,
        "exact_match_rate": exact / len(frame_review) if frame_review else 0.0,
        "any_overlap_rate": overlap / len(frame_review) if frame_review else 0.0,
    }
    return scenario_report, frame_review, summary


def _episodes_for_recording(
    rows: list[dict[str, Any]],
    source: str,
) -> dict[str, list[dict[str, Any]]]:
    """Build contiguous sampled-frame episodes for each simplified scenario.

    Contiguity is based on adjacent reviewed samples, not numeric frame_index + 1,
    because the GT workspace may use 1 Hz samples from a higher-rate recording.
    """
    ordered = sorted(rows, key=lambda row: row.get("frame_index", -1))
    active: dict[str, dict[str, Any]] = {}
    episodes: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for pos, row in enumerate(ordered):
        tags = row.get(source) if isinstance(row.get(source), dict) else {}
        current = _simplified_scenario_set(tags)

        for scenario in list(active):
            if scenario not in current:
                episodes[scenario].append(active.pop(scenario))

        for scenario in current:
            if scenario not in active:
                active[scenario] = {
                    "start_pos": pos,
                    "end_pos": pos,
                    "start_frame": row.get("frame_index"),
                    "end_frame": row.get("frame_index"),
                    "start_timestamp": row.get("timestamp"),
                    "end_timestamp": row.get("timestamp"),
                    "sample_count": 1,
                }
            else:
                episode = active[scenario]
                episode["end_pos"] = pos
                episode["end_frame"] = row.get("frame_index")
                episode["end_timestamp"] = row.get("timestamp")
                episode["sample_count"] += 1

    for scenario, episode in active.items():
        episodes[scenario].append(episode)

    return dict(episodes)


def _episode_overlap(gt: dict[str, Any], pred: dict[str, Any]) -> tuple[int, float]:
    start = max(gt["start_pos"], pred["start_pos"])
    end = min(gt["end_pos"], pred["end_pos"])
    if end < start:
        return 0, 0.0
    intersection = end - start + 1
    union_start = min(gt["start_pos"], pred["start_pos"])
    union_end = max(gt["end_pos"], pred["end_pos"])
    union = union_end - union_start + 1
    return intersection, intersection / union if union else 0.0


def _range_scenario_review(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Event/range F1 where any temporal overlap counts as a true detection.

    Example: GT lane change at sampled frames 1-5 and detection at 2-6 are
    matched as one TP event. Matching is one-to-one within each recording and
    scenario. When several ranges overlap, pairs with the largest overlap are
    matched first, then by highest IoU.
    """
    by_recording: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        recording = row.get("recording_id")
        if isinstance(recording, str):
            by_recording[recording].append(row)

    counts_by_scenario: dict[str, Counter] = defaultdict(Counter)
    range_review: list[dict[str, Any]] = []
    matched_events = gt_events = detected_events = 0

    for recording, recording_rows in sorted(by_recording.items()):
        gt_episodes = _episodes_for_recording(recording_rows, "gt")
        pred_episodes = _episodes_for_recording(recording_rows, "prediction")
        scenarios = sorted(set(gt_episodes) | set(pred_episodes))

        for scenario in scenarios:
            gt_list = gt_episodes.get(scenario, [])
            pred_list = pred_episodes.get(scenario, [])
            gt_events += len(gt_list)
            detected_events += len(pred_list)

            candidates: list[tuple[int, float, int, int]] = []
            for gi, gt_episode in enumerate(gt_list):
                for pi, pred_episode in enumerate(pred_list):
                    overlap_samples, iou = _episode_overlap(gt_episode, pred_episode)
                    if overlap_samples > 0:
                        candidates.append((overlap_samples, iou, gi, pi))

            # One GT event may match at most one detected event and vice versa.
            candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
            used_gt: set[int] = set()
            used_pred: set[int] = set()
            matched_pairs: list[tuple[int, int, int, float]] = []
            for overlap_samples, iou, gi, pi in candidates:
                if gi in used_gt or pi in used_pred:
                    continue
                used_gt.add(gi)
                used_pred.add(pi)
                matched_pairs.append((gi, pi, overlap_samples, iou))

            counts = counts_by_scenario[scenario]
            counts["tp"] += len(matched_pairs)
            counts["fn"] += len(gt_list) - len(used_gt)
            counts["fp"] += len(pred_list) - len(used_pred)
            matched_events += len(matched_pairs)

            for gi, pi, overlap_samples, iou in matched_pairs:
                gt_episode = gt_list[gi]
                pred_episode = pred_list[pi]
                range_review.append({
                    "recording_id": recording,
                    "scenario": scenario,
                    "result": "TP",
                    "gt_start_frame": gt_episode["start_frame"],
                    "gt_end_frame": gt_episode["end_frame"],
                    "detected_start_frame": pred_episode["start_frame"],
                    "detected_end_frame": pred_episode["end_frame"],
                    "gt_samples": gt_episode["sample_count"],
                    "detected_samples": pred_episode["sample_count"],
                    "overlap_samples": overlap_samples,
                    "range_iou": iou,
                })

            for gi, gt_episode in enumerate(gt_list):
                if gi in used_gt:
                    continue
                range_review.append({
                    "recording_id": recording,
                    "scenario": scenario,
                    "result": "FN",
                    "gt_start_frame": gt_episode["start_frame"],
                    "gt_end_frame": gt_episode["end_frame"],
                    "detected_start_frame": None,
                    "detected_end_frame": None,
                    "gt_samples": gt_episode["sample_count"],
                    "detected_samples": 0,
                    "overlap_samples": 0,
                    "range_iou": 0.0,
                })

            for pi, pred_episode in enumerate(pred_list):
                if pi in used_pred:
                    continue
                range_review.append({
                    "recording_id": recording,
                    "scenario": scenario,
                    "result": "FP",
                    "gt_start_frame": None,
                    "gt_end_frame": None,
                    "detected_start_frame": pred_episode["start_frame"],
                    "detected_end_frame": pred_episode["end_frame"],
                    "gt_samples": 0,
                    "detected_samples": pred_episode["sample_count"],
                    "overlap_samples": 0,
                    "range_iou": 0.0,
                })

    report = {
        scenario: _metric(counts, unit="events")
        for scenario, counts in sorted(counts_by_scenario.items())
    }
    total = Counter()
    for counts in counts_by_scenario.values():
        total.update({key: counts[key] for key in ("tp", "fp", "fn")})
    micro = _metric(total, unit="events")
    macro_f1 = sum(metric["f1"] for metric in report.values()) / len(report) if report else 0.0
    summary = {
        "scoring_unit": "contiguous simplified-scenario event range",
        "match_rule": "one-to-one match; any sampled-frame overlap (>0) counts as TP",
        "gt_events": gt_events,
        "detected_events": detected_events,
        "matched_events": matched_events,
        "micro": micro,
        "macro_f1": macro_f1,
    }
    return report, range_review, summary


def _write_metric_csv(path: Path, report: dict[str, Any], *, unit: str) -> None:
    positive_gt = f"gt_positive_{unit}"
    positive_detected = f"detected_positive_{unit}"
    fields = [
        "scenario", "tp", "fp", "fn", positive_gt, positive_detected,
        "precision", "recall", "f1",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for scenario, metric in report.items():
            writer.writerow({"scenario": scenario, **metric})


def _write_review_csvs(
    review_dir: Path,
    range_scenario_report: dict[str, Any],
    range_review: list[dict[str, Any]],
    frame_scenario_report: dict[str, Any],
    frame_review: list[dict[str, Any]],
) -> None:
    review_dir.mkdir(parents=True, exist_ok=True)

    # Main scenario F1 is range/event based: any temporal overlap is a TP.
    _write_metric_csv(review_dir / "scenario_f1.csv", range_scenario_report, unit="events")
    # Keep strict frame-level scenario F1 for boundary/timing diagnostics.
    _write_metric_csv(review_dir / "frame_scenario_f1.csv", frame_scenario_report, unit="frames")

    range_fields = [
        "recording_id", "scenario", "result", "gt_start_frame", "gt_end_frame",
        "detected_start_frame", "detected_end_frame", "gt_samples", "detected_samples",
        "overlap_samples", "range_iou",
    ]
    with (review_dir / "range_review.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=range_fields)
        writer.writeheader()
        writer.writerows(range_review)

    frame_fields = [
        "recording_id", "frame_index", "timestamp", "gt_simplified_scenarios",
        "detected_simplified_scenarios", "overlap_tp", "detected_only_fp", "gt_only_fn",
        "exact_match", "has_overlap",
    ]
    list_fields = (
        "gt_simplified_scenarios", "detected_simplified_scenarios", "overlap_tp",
        "detected_only_fp", "gt_only_fn",
    )

    def write_frame_rows(path: Path, selected_rows: list[dict[str, Any]]) -> None:
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=frame_fields)
            writer.writeheader()
            for row in selected_rows:
                out = dict(row)
                for key in list_fields:
                    out[key] = " | ".join(out[key])
                writer.writerow(out)

    write_frame_rows(review_dir / "frame_review.csv", frame_review)
    write_frame_rows(
        review_dir / "overlap_frames.csv",
        [row for row in frame_review if row["has_overlap"]],
    )
    write_frame_rows(
        review_dir / "error_frames.csv",
        [row for row in frame_review if not row["exact_match"]],
    )


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

    # Legacy field-wise/frame-wise taxonomy score remains available.
    report = evaluate_gt({"frames": combined_rows})
    frame_scenario_report, frame_review, frame_review_summary = _scenario_and_frame_review(combined_rows)
    range_scenario_report, range_review, range_summary = _range_scenario_review(combined_rows)
    scored_recordings = sum(1 for item in recordings if item.get("status") == "scored")

    report.update({
        "aggregation": "all reviewed frames pooled before metric computation",
        "scenario_comparison_space": "simplified taxonomy on both GT and detection; raw scenario_tags excluded",
        "scenario_scoring": "event/range based; any temporal overlap counts as TP",
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
        "scenario_f1": range_scenario_report,
        "scenario_range_summary": range_summary,
        "range_review": range_review,
        "frame_scenario_f1": frame_scenario_report,
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
        help="Write range/event and strict frame-level simplified-scenario F1 review CSVs.",
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
    _write_review_csvs(
        args.review_dir,
        report["scenario_f1"],
        report["range_review"],
        report["frame_scenario_f1"],
        report["frame_review"],
    )

    legacy_micro = report["micro"]
    frame_review = report["frame_review_summary"]
    range_summary = report["scenario_range_summary"]
    range_micro = range_summary["micro"]

    print(f"Scored recordings: {report['scored_recordings']}")
    print(f"Reviewed frames: {report['reviewed_frames']}")
    print("Scenario F1 comparison: simplified GT vs simplified detection")
    print("Scenario matching: contiguous event ranges; any temporal overlap counts as TP")
    print(f"Range/event micro precision: {range_micro['precision']:.4f}")
    print(f"Range/event micro recall: {range_micro['recall']:.4f}")
    print(f"Range/event micro F1: {range_micro['f1']:.4f}")
    print(f"Range/event macro F1: {range_summary['macro_f1']:.4f}")
    print(f"Matched events: {range_summary['matched_events']}/{range_summary['gt_events']} GT events")
    print(f"Scenario classes: {len(report['scenario_f1'])}")
    print(f"Strict frame micro F1 (legacy taxonomy fields): {legacy_micro['f1']:.4f}")
    print(f"Exact-match frames: {frame_review['exact_match_frames']}/{frame_review['frames']} ({frame_review['exact_match_rate']:.4f})")
    print(f"Frames with detected/GT overlap: {frame_review['frames_with_any_overlap']}/{frame_review['frames']} ({frame_review['any_overlap_rate']:.4f})")
    print(f"Missing prediction frames: {report['missing_prediction_frames_count']}")
    print(f"Aggregate F1 report: {args.output}")
    print(f"F1 review CSVs: {args.review_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
