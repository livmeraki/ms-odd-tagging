#!/usr/bin/env python3
"""Validate frame GT and score implemented dynamic rule-based scenarios."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from ms_odd_tagging.common.config import CANONICAL, DATA_GT, FOLLOWING_LANE, GT_COMPARISON
from ms_odd_tagging.gt_comparison.labels import SPEED_LABELS, TAXONOMY
from ms_odd_tagging.tagger.rule_based.dynamics import classify_speed_band
from ms_odd_tagging.tagger.rule_based.registry import (
    detect_recording_events,
    load_config,
)


RULE_LABELS = [
    *SPEED_LABELS,
    "starting_left_turn",
    "starting_right_turn",
]
FOLLOWING_LABELS = [
    "following_lane_with_lead",
    "following_lane_without_lead",
]
SCORED_LABELS = RULE_LABELS + FOLLOWING_LABELS
UNSCORED_LABELS = [label for label in TAXONOMY if label not in SCORED_LABELS]


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return payload


def validate_gt(
    payload: dict[str, Any],
    recording_id: str,
    canonical_frames: dict[int, dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != "scenario-frame-gt-labels-v1":
        errors.append("schema_version must be scenario-frame-gt-labels-v1")
    if payload.get("recording_id") != recording_id:
        errors.append(f"recording_id must be {recording_id}")
    frames = payload.get("frames")
    if not isinstance(frames, dict) or not frames:
        return errors + ["frames must be a non-empty object"]
    for frame_id, frame in frames.items():
        prefix = f"frames.{frame_id}"
        if not isinstance(frame, dict):
            errors.append(f"{prefix} must be an object")
            continue
        if frame.get("frame_id") != frame_id:
            errors.append(f"{prefix}.frame_id does not match its key")
        frame_index = frame.get("frame_index")
        source = canonical_frames.get(frame_index)
        if source is None:
            errors.append(f"{prefix}.frame_index is absent from canonical data")
        else:
            for field in ("timestamp_unix_s", "time_since_start_s"):
                actual, expected = frame.get(field), source.get(field)
                if not isinstance(actual, (int, float)) or not isinstance(expected, (int, float)):
                    errors.append(f"{prefix}.{field} must be numeric in GT and canonical data")
                elif abs(float(actual) - float(expected)) > 1e-4:
                    errors.append(f"{prefix}.{field} does not match canonical data")
        labels = frame.get("labels")
        if not isinstance(labels, dict):
            errors.append(f"{prefix}.labels must be an object")
            continue
        unknown = sorted(set(labels) - set(TAXONOMY))
        missing = sorted(set(TAXONOMY) - set(labels))
        if unknown:
            errors.append(f"{prefix}.labels has unknown labels: {', '.join(unknown)}")
        if missing:
            errors.append(f"{prefix}.labels is missing labels: {', '.join(missing)}")
        for label in TAXONOMY:
            if labels.get(label) is not None and not isinstance(labels.get(label), bool):
                errors.append(f"{prefix}.labels.{label} must be boolean or null")
        speed_values = [labels.get(label) for label in SPEED_LABELS]
        if all(isinstance(value, bool) for value in speed_values) and sum(speed_values) != 1:
            errors.append(f"{prefix} must have exactly one true speed label")
    return errors


def rule_predictions(
    canonical: dict[str, Any],
) -> tuple[dict[int, dict[str, bool]], list[dict[str, Any]]]:
    events, _quality = detect_recording_events(canonical)
    predictions: dict[int, dict[str, bool]] = {}
    for frame in canonical.get("frames", []):
        frame_index = frame["frame_index"]
        active = {
            event.scenario
            for event in events
            if event.start_frame <= frame_index <= event.end_frame
        }
        predictions[frame_index] = {label: label in active for label in RULE_LABELS}
    return predictions, [event.to_dict() for event in events]


def gt_quality_summary(
    payloads: list[dict[str, Any]],
    canonicals: dict[str, dict[str, Any]],
    minimum_frame_index: int,
) -> dict[str, Any]:
    config = load_config()
    pending_frames = reviewed_frames = null_label_values = speed_formula_mismatches = 0
    mismatch_examples = []
    for payload in payloads:
        recording_id = payload["recording_id"]
        canonical_by_index = {
            frame["frame_index"]: frame for frame in canonicals[recording_id]["frames"]
        }
        for frame_id, frame in payload["frames"].items():
            if frame["frame_index"] < minimum_frame_index:
                continue
            if frame.get("needs_review", True):
                pending_frames += 1
            else:
                reviewed_frames += 1
            labels = frame["labels"]
            null_label_values += sum(value is None for value in labels.values())
            speed = (canonical_by_index[frame["frame_index"]].get("ego") or {}).get("speed_mps")
            expected = classify_speed_band(speed, config)
            selected = [label for label in SPEED_LABELS if labels.get(label) is True]
            if expected is not None and selected != [expected]:
                speed_formula_mismatches += 1
                if len(mismatch_examples) < 10:
                    mismatch_examples.append(
                        {
                            "recording_id": recording_id,
                            "frame_id": frame_id,
                            "frame_index": frame["frame_index"],
                            "speed_mps": speed,
                            "expected_speed_label": expected,
                            "selected_speed_labels": selected,
                        }
                    )
    provisional_reasons = []
    if pending_frames:
        provisional_reasons.append(f"{pending_frames} frames are still marked needs_review")
    if null_label_values:
        provisional_reasons.append(f"{null_label_values} GT label values are null")
    if speed_formula_mismatches:
        provisional_reasons.append(
            f"{speed_formula_mismatches} speed labels disagree with the Phase 1 per-frame classifier"
        )
    return {
        "status": "provisional" if provisional_reasons else "valid",
        "reviewed_frames": reviewed_frames,
        "pending_frames": pending_frames,
        "null_label_values": null_label_values,
        "speed_formula_mismatches": speed_formula_mismatches,
        "provisional_reasons": provisional_reasons,
        "speed_mismatch_examples": mismatch_examples,
    }


def add_following_predictions(
    predictions: dict[int, dict[str, bool]],
    following_payload: dict[str, Any],
) -> None:
    for frame in following_payload.get("frames", []):
        frame_index = frame.get("frame_index")
        if frame_index not in predictions:
            continue
        state = frame.get("state")
        for label in FOLLOWING_LABELS:
            predictions[frame_index][label] = state == label


def metric_row(label: str, counts: dict[str, int]) -> dict[str, Any]:
    tp, tn, fp, fn = (counts[key] for key in ("tp", "tn", "fp", "fn"))
    compared = tp + tn + fp + fn
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    return {
        "label": label,
        "compared": compared,
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "accuracy": (tp + tn) / compared if compared else None,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def evaluate(
    gt_payloads: list[dict[str, Any]],
    canonicals: dict[str, dict[str, Any]],
    following_payloads: dict[str, dict[str, Any]],
    minimum_frame_index: int = 0,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    totals = {label: defaultdict(int) for label in SCORED_LABELS}
    details: list[dict[str, Any]] = []
    recording_summaries = []
    for gt in gt_payloads:
        recording_id = gt["recording_id"]
        predictions, events = rule_predictions(canonicals[recording_id])
        add_following_predictions(predictions, following_payloads[recording_id])
        recording_counts = {label: defaultdict(int) for label in SCORED_LABELS}
        compared_frames: set[str] = set()
        exact_frames: dict[str, bool] = {}
        for frame_id, frame in gt["frames"].items():
            frame_index = frame["frame_index"]
            if frame_index < minimum_frame_index:
                continue
            predicted = predictions[frame_index]
            for label in SCORED_LABELS:
                expected = frame["labels"].get(label)
                if not isinstance(expected, bool):
                    continue
                actual = predicted[label]
                outcome = "tp" if expected and actual else "tn" if not expected and not actual else "fp" if actual else "fn"
                totals[label][outcome] += 1
                recording_counts[label][outcome] += 1
                compared_frames.add(frame_id)
                exact_frames[frame_id] = exact_frames.get(frame_id, True) and expected == actual
                details.append(
                    {
                        "recording_id": recording_id,
                        "frame_id": frame_id,
                        "frame_index": frame_index,
                        "timestamp_unix_s": frame["timestamp_unix_s"],
                        "label": label,
                        "expected": expected,
                        "actual": actual,
                        "outcome": outcome,
                    }
                )
        rows = [metric_row(label, recording_counts[label]) for label in SCORED_LABELS]
        recording_summaries.append(
            {
                "recording_id": recording_id,
                "reviewed_frames_scored": len(compared_frames),
                "exact_match_frames": sum(exact_frames.values()),
                "exact_match_accuracy": sum(exact_frames.values()) / len(exact_frames),
                "phase1_event_count": len(events),
                "label_metrics": rows,
            }
        )
    label_metrics = [metric_row(label, totals[label]) for label in SCORED_LABELS]
    micro_counts = defaultdict(int)
    for counts in totals.values():
        for key in ("tp", "tn", "fp", "fn"):
            micro_counts[key] += counts[key]
    micro = metric_row("micro", micro_counts)
    f1_values = [row["f1"] for row in label_metrics if row["f1"] is not None]
    summary = {
        "schema_version": "rule-based-gt-comparison-v1",
        "scored_labels": SCORED_LABELS,
        "unscored_labels": UNSCORED_LABELS,
        "recording_count": len(gt_payloads),
        "minimum_scored_frame_index": minimum_frame_index,
        "micro_metrics": micro,
        "macro_f1": sum(f1_values) / len(f1_values) if f1_values else None,
        "label_metrics": label_metrics,
        "recordings": recording_summaries,
    }
    return summary, details


def write_reports(output_dir: Path, summary: dict[str, Any], details: list[dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "rule_based_gt_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (output_dir / "rule_based_gt_details.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(details[0]) if details else [])
        if details:
            writer.writeheader()
            writer.writerows(details)
    lines = [
        "# Dynamic rule-based GT comparison",
        "",
        f"- Status: **{summary['gt_quality']['status']}**",
        f"- Recordings: {summary['recording_count']}",
        f"- Frame exclusion: source frame indexes below {summary['minimum_scored_frame_index']} were not evaluated",
        f"- Scored labels: {', '.join(summary['scored_labels'])}",
        f"- Unscored labels: {', '.join(summary['unscored_labels'])}",
        f"- Micro accuracy: {summary['micro_metrics']['accuracy']:.4f}",
        f"- Micro F1: {summary['micro_metrics']['f1']:.4f}",
        f"- Macro F1: {summary['macro_f1']:.4f}",
        "",
    ]
    if summary["gt_quality"]["provisional_reasons"]:
        lines.extend(
            ["## GT quality findings", ""]
            + [f"- {reason}" for reason in summary["gt_quality"]["provisional_reasons"]]
            + [""]
        )
    lines.extend([
        "| Label | Compared | Accuracy | Precision | Recall | F1 | TP | TN | FP | FN |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for row in summary["label_metrics"]:
        value = lambda name: "n/a" if row[name] is None else f"{row[name]:.4f}"
        lines.append(
            f"| {row['label']} | {row['compared']} | {value('accuracy')} | "
            f"{value('precision')} | {value('recall')} | {value('f1')} | "
            f"{row['tp']} | {row['tn']} | {row['fp']} | {row['fn']} |"
        )
    (output_dir / "rule_based_gt_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gt-dir", type=Path, default=DATA_GT)
    parser.add_argument(
        "--recording",
        action="append",
        default=[],
        help="Recording ID to evaluate; repeat for multiple recordings. Defaults to all GT files.",
    )
    parser.add_argument("--canonical-dir", type=Path, default=CANONICAL)
    parser.add_argument(
        "--following-tags-dir",
        type=Path,
        default=FOLLOWING_LANE / "03_tags",
    )
    parser.add_argument("--output-dir", type=Path, default=GT_COMPARISON)
    parser.add_argument(
        "--minimum-frame-index",
        type=int,
        default=5,
        help="Exclude GT samples with a source frame index below this value.",
    )
    args = parser.parse_args(argv)

    gt_paths = sorted(args.gt_dir.glob("*_frame_gt.json"))
    if args.recording:
        selected = set(args.recording)
        gt_paths = [
            path
            for path in gt_paths
            if path.name.removesuffix("_frame_gt.json") in selected
        ]
    if not gt_paths:
        parser.error(f"no matching *_frame_gt.json files found in {args.gt_dir}")
    gt_payloads, canonicals, following_payloads = [], {}, {}
    validation_errors = []
    for gt_path in gt_paths:
        gt = load_json(gt_path)
        recording_id = gt.get("recording_id")
        canonical_path = args.canonical_dir / f"{recording_id}_canonical_odld_frames.json"
        following_path = args.following_tags_dir / f"{recording_id}_following_lane_tags.json"
        if not canonical_path.is_file():
            validation_errors.append(f"{gt_path}: missing {canonical_path}")
            continue
        if not following_path.is_file():
            validation_errors.append(f"{gt_path}: missing {following_path}")
            continue
        canonical = load_json(canonical_path)
        canonical_frames = {frame["frame_index"]: frame for frame in canonical.get("frames", [])}
        validation_errors.extend(
            f"{gt_path}: {error}" for error in validate_gt(gt, str(recording_id), canonical_frames)
        )
        gt_payloads.append(gt)
        canonicals[str(recording_id)] = canonical
        following_payloads[str(recording_id)] = load_json(following_path)
    if validation_errors:
        print("GT validation failed:")
        for error in validation_errors:
            print(f"- {error}")
        return 2
    summary, details = evaluate(
        gt_payloads,
        canonicals,
        following_payloads,
        minimum_frame_index=args.minimum_frame_index,
    )
    summary["gt_quality"] = gt_quality_summary(
        gt_payloads,
        canonicals,
        minimum_frame_index=args.minimum_frame_index,
    )
    write_reports(args.output_dir, summary, details)
    print(f"Validated {len(gt_payloads)} GT files.")
    print(f"GT quality status: {summary['gt_quality']['status']}")
    for reason in summary["gt_quality"]["provisional_reasons"]:
        print(f"WARNING: {reason}")
    print(f"Micro accuracy: {summary['micro_metrics']['accuracy']:.4f}")
    print(f"Micro F1: {summary['micro_metrics']['f1']:.4f}")
    print(f"Macro F1: {summary['macro_f1']:.4f}")
    print(f"Wrote {args.output_dir / 'rule_based_gt_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
