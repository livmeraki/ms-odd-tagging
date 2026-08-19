"""Balanced pedestrian-understanding experiment using controlled pseudo BEVs."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .experiment_cli import CONDITIONS, _legend_for_condition
from .runner import Probe, run_probe


TASKS = (
    "pedestrian_presence",
    "spatial_relation",
    "path_interaction",
    "waiting_direct",
    "waiting_evidence_gated",
)
TASK_CHOICES = {
    "pedestrian_presence": ("yes", "no", "unknown"),
    "spatial_relation": ("ahead", "behind", "left", "right", "not_applicable", "unknown"),
    "path_interaction": ("yes", "no", "unknown"),
    "waiting_direct": ("yes", "no", "unknown"),
    "waiting_evidence_gated": ("yes", "no", "unknown"),
}
QUESTIONS = {
    "pedestrian_presence": "Is at least one orange pedestrian present in the BEV?",
    "spatial_relation": (
        "Where is the orange pedestrian nearest to ego: ahead, behind, left, right, "
        "not_applicable, or unknown? Answer not_applicable when no pedestrian exists."
    ),
    "path_interaction": (
        "Does any pedestrian occupy or move toward the highlighted ego path? "
        "Pedestrians confined to a sidewalk or a different lane do not count."
    ),
    "waiting_direct": "Is the ego vehicle waiting for a pedestrian to cross?",
    "waiting_evidence_gated": (
        "Apply this gate in order: (1) confirm a pedestrian exists; (2) confirm that pedestrian "
        "occupies or approaches the highlighted ego path; (3) confirm ego is stopped. "
        "Answer yes only when all three are supported. Otherwise answer no; use unknown only when "
        "the image is genuinely unreadable. Is ego waiting for a pedestrian to cross?"
    ),
}
EXPECTED_FIELD = {
    "pedestrian_presence": "expected_presence",
    "spatial_relation": "expected_relation",
    "path_interaction": "expected_path_interaction",
    "waiting_direct": "expected_waiting",
    "waiting_evidence_gated": "expected_waiting",
}


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("scenes"), list) or not payload["scenes"]:
        raise ValueError(f"{path} must contain a non-empty top-level 'scenes' array")
    return payload


def _validate_scene(scene: dict[str, Any], image: Path) -> None:
    missing = [field for field in ("scene_id", "expected_presence", "expected_relation", "expected_path_interaction", "expected_waiting") if field not in scene]
    if missing:
        raise ValueError(f"Scene is missing required fields: {missing}")
    if scene["expected_presence"] == "no":
        expected = (scene["expected_relation"], scene["expected_path_interaction"], scene["expected_waiting"])
        if expected != ("not_applicable", "no", "no"):
            raise ValueError(f"{scene['scene_id']}: absent pedestrian requires not_applicable/no/no GT")
    if not image.is_file():
        raise FileNotFoundError(image)


def _write_outputs(rows: list[dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    fields = ["scene_id", "task", "condition", "difficulty", "expected", "answer", "correct", "confidence", "elapsed_s", "ok", "error"]
    with (output_dir / "pedestrian_scene_results.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({field: row.get(field) for field in fields} for row in rows)

    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[(row["task"], row["condition"])].append(row)
    with (output_dir / "pedestrian_condition_summary.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = ["task", "condition", "n", "correct", "accuracy", "false_positive", "false_positive_rate"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for (task, condition), values in sorted(buckets.items()):
            valid = [row for row in values if row.get("ok")]
            negatives = [row for row in valid if row["expected"] in ("no", "not_applicable")]
            false_positive = sum(row["answer"] not in ("no", "not_applicable", "unknown") for row in negatives)
            writer.writerow({
                "task": task,
                "condition": condition,
                "n": len(valid),
                "correct": sum(bool(row.get("correct")) for row in valid),
                "accuracy": round(sum(bool(row.get("correct")) for row in valid) / len(valid), 4) if valid else "",
                "false_positive": false_positive,
                "false_positive_rate": round(false_positive / len(negatives), 4) if negatives else "",
            })


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the balanced pedestrian pseudo-BEV audit.")
    parser.add_argument("--experiment", type=Path, default=Path("examples/vlm_understanding_pedestrian_experiment.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/vlm_understanding_pedestrian_experiment"))
    parser.add_argument("--endpoint", default="http://127.0.0.1:8001/v1/chat/completions")
    parser.add_argument("--model", default="Qwen/Qwen3-VL-8B-Instruct")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--timeout-s", type=float, default=60.0)
    parser.add_argument("--task", action="append", choices=TASKS, help="Repeat to select tasks.")
    parser.add_argument("--condition", action="append", choices=CONDITIONS, help="Repeat to select legend conditions.")
    parser.add_argument("--scene", action="append", help="Repeat to select scene IDs.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true", help="Validate fixtures and print run count without calling the VLM.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    payload = _load(args.experiment)
    base_dir = args.experiment.parent
    tasks = tuple(args.task or TASKS)
    conditions = tuple(args.condition or CONDITIONS)
    wanted_scenes = set(args.scene or ())
    generated: list[tuple[dict[str, Any], str, str, Probe]] = []

    for scene in payload["scenes"]:
        if wanted_scenes and scene["scene_id"] not in wanted_scenes:
            continue
        image = (base_dir / scene["bev"]).resolve()
        _validate_scene(scene, image)
        for task in tasks:
            for condition in conditions:
                expected = scene[EXPECTED_FIELD[task]]
                probe = Probe(
                    probe_id=f"{scene['scene_id']}__{task}__{condition}",
                    sample_id=str(scene["scene_id"]),
                    category=task,
                    modality=f"bev_only/{condition}",
                    question=QUESTIONS[task],
                    expected_answer=expected,
                    answer_choices=TASK_CHOICES[task],
                    images=(image,),
                    structured_evidence=None,
                    legend=_legend_for_condition(payload.get("legend"), condition),
                    notes=str(scene.get("notes") or ""),
                )
                generated.append((scene, task, condition, probe))

    if args.limit is not None:
        generated = generated[: args.limit]
    print(f"Scenes selected: {len({item[0]['scene_id'] for item in generated})}")
    print(f"Generated runs: {len(generated)}")
    print("Tasks: " + " / ".join(tasks))
    print("Conditions: " + " / ".join(conditions))
    if args.dry_run:
        print("Dry run passed: manifest and all selected images are valid.")
        return

    rows = []
    for index, (scene, task, condition, probe) in enumerate(generated, start=1):
        print(f"[{index}/{len(generated)}] {probe.probe_id}")
        result = run_probe(probe, endpoint=args.endpoint, model=args.model, temperature=args.temperature, max_tokens=args.max_tokens, timeout_s=args.timeout_s)
        answer = (result.get("canonical_answers") or {}).get("answer")
        output = result.get("model_output") or {}
        row = {
            "scene_id": scene["scene_id"], "task": task, "condition": condition,
            "difficulty": scene.get("difficulty"), "expected": scene[EXPECTED_FIELD[task]],
            "answer": answer, "correct": result.get("correct"), "confidence": output.get("confidence"),
            "elapsed_s": result.get("elapsed_s"), "ok": result.get("ok"), "error": result.get("error"),
        }
        rows.append(row)
        print(f"  expected={row['expected']!r} answer={answer!r} correct={row['correct']}")

    _write_outputs(rows, args.output_dir)
    valid = [row for row in rows if row["ok"]]
    correct = sum(bool(row["correct"]) for row in valid)
    print(f"Done. valid={len(valid)} correct={correct} accuracy={correct / len(valid):.3f}" if valid else "Done. No valid VLM responses.")
    print(f"Results: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
