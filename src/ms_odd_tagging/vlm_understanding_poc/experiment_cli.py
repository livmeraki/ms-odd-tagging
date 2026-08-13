"""Controlled presentation experiment for VLM understanding of the custom BEV.

This runner is intentionally separate from the exploratory probe CLI. It takes a
small scene manifest with verified GT, generates a balanced set of controlled
probes, applies legend ablations, runs the existing VLM client, and writes
presentation-ready metrics.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

from .manifest import parse_set_args
from .runner import Probe, run_probe


_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_COLOR_WORDS = ("orange", "green", "blue", "red", "purple", "yellow", "white", "black", "cyan")
_ORIENTATION_MARKERS = (
    "image up",
    "image down",
    "image left",
    "image right",
    "forward direction",
    "ahead relative",
    "behind relative",
    "left relative",
    "right relative",
)
CONDITIONS = ("full_legend", "no_color_legend", "no_orientation_legend", "no_legend")
RELATIONS = ("ahead", "behind", "left", "right", "unknown")


def _substitute(value: Any, variables: dict[str, str]) -> Any:
    if isinstance(value, str):
        def repl(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in variables:
                raise ValueError(f"Undefined experiment variable: {name}")
            return variables[name]
        return _VAR_PATTERN.sub(repl, value)
    if isinstance(value, list):
        return [_substitute(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(item, variables) for key, item in value.items()}
    return value


def _no_color_legend(legend: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(legend, dict):
        return legend
    reduced: dict[str, Any] = {}
    for raw_key, value in legend.items():
        key = str(raw_key)
        lower = key.lower()
        if not any(word in lower for word in _COLOR_WORDS):
            reduced[key] = value
            continue
        if "rectangle" in lower or "triangle" in lower or "nose" in lower:
            stripped = key
            for word in _COLOR_WORDS:
                stripped = stripped.replace(word, "").replace(word.capitalize(), "")
            stripped = " ".join(stripped.split())
            if stripped:
                reduced[stripped] = value
    return reduced or None


def _no_orientation_legend(legend: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(legend, dict):
        return legend
    reduced: dict[str, Any] = {}
    for raw_key, value in legend.items():
        key = str(raw_key)
        combined = f"{key} {value}".lower()
        if any(marker in combined for marker in _ORIENTATION_MARKERS):
            continue
        reduced[key] = value
    return reduced or None


def _legend_for_condition(legend: dict[str, Any] | None, condition: str) -> dict[str, Any] | None:
    if condition == "full_legend":
        return legend
    if condition == "no_color_legend":
        return _no_color_legend(legend)
    if condition == "no_orientation_legend":
        return _no_orientation_legend(legend)
    if condition == "no_legend":
        return None
    raise ValueError(f"Unknown condition: {condition}")


def _load_experiment(path: Path, overrides: dict[str, str]) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    variables = {str(k): str(v) for k, v in (payload.get("variables") or {}).items()}
    variables.update(overrides)
    payload = _substitute(payload, variables)
    payload["_base_dir"] = str(path.parent.resolve())
    return payload


def _resolve_image(base_dir: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _scene_probes(payload: dict[str, Any], *, include_marked: bool) -> list[tuple[str, str, Probe, dict[str, Any]]]:
    """Return (task, condition, probe, scene metadata) tuples."""
    base_dir = Path(payload["_base_dir"])
    legend = payload.get("legend") or {}
    probes: list[tuple[str, str, Probe, dict[str, Any]]] = []

    for raw_scene in payload.get("scenes", []):
        scene_id = str(raw_scene["scene_id"])
        expected = raw_scene.get("expected_relation")
        if expected not in RELATIONS:
            raise ValueError(f"{scene_id}: expected_relation must be one of {RELATIONS}; got {expected!r}")
        bev = _resolve_image(base_dir, str(raw_scene["bev"]))
        marked_value = raw_scene.get("marked_bev")
        marked_bev = _resolve_image(base_dir, str(marked_value)) if marked_value else None
        target_description = str(raw_scene.get("target_description") or "orange pedestrian nearest to the ego vehicle")
        difficulty = str(raw_scene.get("difficulty") or "unspecified")
        scene_meta = {
            "scene_id": scene_id,
            "expected_relation": expected,
            "difficulty": difficulty,
            "frame": raw_scene.get("frame"),
            "recording": raw_scene.get("recording"),
            "notes": raw_scene.get("notes"),
        }

        tasks: list[tuple[str, Path, str]] = [
            (
                "spatial_unmarked",
                bev,
                f"Using ego heading as reference, where is the {target_description}: ahead, behind, left, right, or unknown?",
            )
        ]
        if include_marked and marked_bev is not None:
            tasks.append(
                (
                    "spatial_marked",
                    marked_bev,
                    "The object marked TARGET is the object of interest. Using ego heading as reference, where is TARGET: ahead, behind, left, right, or unknown?",
                )
            )

        for task, image, question in tasks:
            for condition in CONDITIONS:
                condition_legend = _legend_for_condition(legend, condition)
                probe = Probe(
                    probe_id=f"{scene_id}__{task}__{condition}",
                    sample_id=scene_id,
                    category=task,
                    modality=f"bev_only/{condition}",
                    question=question,
                    expected_answer=expected,
                    answer_choices=RELATIONS,
                    images=(image,),
                    structured_evidence=None,
                    legend=condition_legend,
                    notes=(
                        f"Controlled experiment. difficulty={difficulty}; condition={condition}; "
                        f"source_note={raw_scene.get('notes') or ''}"
                    ),
                )
                probes.append((task, condition, probe, scene_meta))
    return probes


def _write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def _ratio(numer: int, denom: int) -> float | str:
    return round(numer / denom, 4) if denom else ""


def _write_metrics(results: list[dict[str, Any]], output_dir: Path) -> None:
    # Per-run flat table.
    run_fields = [
        "scene_id", "task", "condition", "difficulty", "expected", "answer", "correct",
        "confidence", "response_consistent", "elapsed_s", "recording", "frame", "notes",
    ]
    with (output_dir / "scene_results.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=run_fields)
        writer.writeheader()
        for row in results:
            writer.writerow({field: row.get(field) for field in run_fields})

    # Accuracy / unknown rate / mean confidence by task and condition.
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        buckets[(row["task"], row["condition"])].append(row)

    summary_fields = [
        "task", "condition", "n", "correct", "accuracy", "unknown", "unknown_rate",
        "mean_confidence", "response_consistency",
    ]
    with (output_dir / "condition_summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=summary_fields)
        writer.writeheader()
        for (task, condition), rows in sorted(buckets.items()):
            valid = [r for r in rows if r.get("ok")]
            n = len(valid)
            correct = sum(bool(r.get("correct")) for r in valid)
            unknown = sum(r.get("answer") == "unknown" for r in valid)
            confidences = [float(r["confidence"]) for r in valid if isinstance(r.get("confidence"), (int, float))]
            consistent = sum(bool(r.get("response_consistent")) for r in valid)
            writer.writerow({
                "task": task,
                "condition": condition,
                "n": n,
                "correct": correct,
                "accuracy": _ratio(correct, n),
                "unknown": unknown,
                "unknown_rate": _ratio(unknown, n),
                "mean_confidence": round(sum(confidences) / len(confidences), 4) if confidences else "",
                "response_consistency": _ratio(consistent, n),
            })

    # Confusion matrix for spatial labels. One row per task+condition+GT.
    confusion: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
    for row in results:
        if row.get("ok"):
            confusion[(row["task"], row["condition"], str(row["expected"]))][str(row["answer"])] += 1
    confusion_fields = ["task", "condition", "expected", *RELATIONS]
    with (output_dir / "confusion_matrix.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=confusion_fields)
        writer.writeheader()
        for (task, condition, expected), counts in sorted(confusion.items()):
            row = {"task": task, "condition": condition, "expected": expected}
            row.update({label: counts.get(label, 0) for label in RELATIONS})
            writer.writerow(row)

    # Failure taxonomy for presentation debugging.
    failure_fields = ["scene_id", "task", "condition", "difficulty", "expected", "answer", "failure_type", "confidence"]
    with (output_dir / "failure_analysis.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=failure_fields)
        writer.writeheader()
        for row in results:
            if row.get("correct") is True:
                continue
            if not row.get("ok"):
                failure_type = "request_or_parse_error"
            elif row.get("answer") == "unknown":
                failure_type = "unknown"
            elif row.get("response_consistent") is False:
                failure_type = "response_inconsistency"
            else:
                failure_type = "wrong_direction_or_target"
            writer.writerow({
                "scene_id": row["scene_id"],
                "task": row["task"],
                "condition": row["condition"],
                "difficulty": row["difficulty"],
                "expected": row["expected"],
                "answer": row.get("answer"),
                "failure_type": failure_type,
                "confidence": row.get("confidence"),
            })

    # Small markdown table that can be copied into a presentation draft.
    lines = [
        "# VLM BEV Understanding Experiment Summary",
        "",
        "| Task | Condition | N | Accuracy | Unknown rate | Mean confidence |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for (task, condition), rows in sorted(buckets.items()):
        valid = [r for r in rows if r.get("ok")]
        n = len(valid)
        correct = sum(bool(r.get("correct")) for r in valid)
        unknown = sum(r.get("answer") == "unknown" for r in valid)
        confidences = [float(r["confidence"]) for r in valid if isinstance(r.get("confidence"), (int, float))]
        mean_conf = round(sum(confidences) / len(confidences), 3) if confidences else "-"
        lines.append(
            f"| {task} | {condition} | {n} | {_ratio(correct, n)} | {_ratio(unknown, n)} | {mean_conf} |"
        )
    (output_dir / "presentation_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run controlled BEV-understanding experiment for presentation metrics.")
    parser.add_argument("--experiment", required=True, type=Path, help="Experiment scene manifest JSON.")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/vlm_understanding_experiment"))
    parser.add_argument("--endpoint", default="http://127.0.0.1:8001/v1/chat/completions")
    parser.add_argument("--model", default="Qwen/Qwen3-VL-8B-Instruct")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--timeout-s", type=float, default=60.0)
    parser.add_argument("--set", action="append", default=None, metavar="KEY=VALUE")
    parser.add_argument("--scene", action="append", default=None, help="Run only named scene_id; repeatable.")
    parser.add_argument("--no-marked", action="store_true", help="Skip optional marked-target BEV probes.")
    parser.add_argument("--limit", type=int, default=None, help="Limit generated probe runs after expansion.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    overrides = parse_set_args(args.set)
    payload = _load_experiment(args.experiment, overrides)
    generated = _scene_probes(payload, include_marked=not args.no_marked)

    if args.scene:
        wanted = set(args.scene)
        generated = [item for item in generated if item[3]["scene_id"] in wanted]
    if args.limit is not None:
        generated = generated[: args.limit]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Scenes in manifest: {len(payload.get('scenes', []))}")
    print(f"Generated runs: {len(generated)}")
    print("Conditions: " + " / ".join(CONDITIONS))

    detailed: list[dict[str, Any]] = []
    flat: list[dict[str, Any]] = []
    for index, (task, condition, probe, scene_meta) in enumerate(generated, start=1):
        print(f"[{index}/{len(generated)}] {probe.probe_id}")
        result = run_probe(
            probe,
            endpoint=args.endpoint,
            model=args.model,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            timeout_s=args.timeout_s,
        )
        detailed.append({"task": task, "condition": condition, "scene": scene_meta, **result})
        canonical = result.get("canonical_answers") or {}
        output = result.get("model_output") or {}
        flat_row = {
            "scene_id": scene_meta["scene_id"],
            "task": task,
            "condition": condition,
            "difficulty": scene_meta["difficulty"],
            "expected": scene_meta["expected_relation"],
            "answer": canonical.get("answer") if result.get("ok") else None,
            "correct": result.get("correct"),
            "confidence": output.get("confidence"),
            "response_consistent": result.get("response_consistent"),
            "elapsed_s": result.get("elapsed_s"),
            "recording": scene_meta.get("recording"),
            "frame": scene_meta.get("frame"),
            "notes": scene_meta.get("notes"),
            "ok": result.get("ok"),
        }
        flat.append(flat_row)
        print(
            f"  task={task} condition={condition} expected={flat_row['expected']!r} "
            f"answer={flat_row['answer']!r} correct={flat_row['correct']} confidence={flat_row['confidence']}"
        )

    _write_jsonl(detailed, args.output_dir / "experiment_results.jsonl")
    _write_metrics(flat, args.output_dir)
    valid = [row for row in flat if row.get("ok")]
    correct = sum(bool(row.get("correct")) for row in valid)
    print(f"Done. valid={len(valid)} correct={correct} accuracy={_ratio(correct, len(valid))}")
    print(f"Results: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
