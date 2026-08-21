#!/usr/bin/env python
"""Compare original vs side attempt-1-style BEVs against user-provided GT."""

from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ms_odd_tagging.qwen_vlm_poc.attempt1_style_bev import render_candidate_bevs_attempt1_style
from ms_odd_tagging.qwen_vlm_poc.client import VlmClient, extract_message_text
from ms_odd_tagging.qwen_vlm_poc.config import load_config
from ms_odd_tagging.qwen_vlm_poc.evidence import load_candidate_bundle, render_candidate_bevs
from ms_odd_tagging.qwen_vlm_poc.loader import canonical_path, load_recording
from ms_odd_tagging.qwen_vlm_poc.validation import parse_and_validate_response


STYLES = ("original", "attempt1_style")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a GT-scored BEV-style VLM experiment for saved candidate bundles."
    )
    parser.add_argument("--candidate-bundle", action="append", type=Path, required=True)
    parser.add_argument("--gt", type=Path, required=True, help="CSV with candidate_id,expected_decision.")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--style", action="append", choices=STYLES, help="Default: both styles.")
    parser.add_argument("--input-dir", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--timeout-s", type=float, default=None)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--force-cache-refresh", action="store_true")
    parser.add_argument(
        "--compact-vlm-input",
        action="store_true",
        help="Send compact candidate JSON to vLLM while preserving rendered BEVs and GT scoring.",
    )
    parser.add_argument(
        "--write-gt-template",
        action="store_true",
        help="Write a GT CSV template for the candidate bundles and exit.",
    )
    return parser.parse_args()


def _bool_text(value: Any) -> bool | None:
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _load_gt(path: Path) -> dict[str, dict[str, str]]:
    rows = {}
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            candidate_id = (row.get("candidate_id") or "").strip()
            if candidate_id:
                rows[candidate_id] = row
    return rows


def _write_gt_template(bundle_paths: list[Path], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as stream:
        fields = ["candidate_id", "scenario", "recording_id", "start_frame", "end_frame", "expected_decision", "notes"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for bundle_path in bundle_paths:
            candidate = load_candidate_bundle(bundle_path)
            writer.writerow(
                {
                    "candidate_id": candidate.candidate_id,
                    "scenario": candidate.scenario,
                    "recording_id": candidate.recording_id,
                    "start_frame": candidate.start_frame,
                    "end_frame": candidate.end_frame,
                    "expected_decision": "",
                    "notes": "",
                }
            )


def _render(style: str, recording: dict[str, Any], candidate, output_root: Path, config):
    style_root = output_root / style
    if style == "original":
        rendered = render_candidate_bevs(recording, candidate, style_root, config)
        return replace(rendered, metadata={**rendered.metadata, "bev_renderer": "original-revised-bev"})
    return render_candidate_bevs_attempt1_style(recording, candidate, style_root, config)


def _compact_candidate_for_vlm(candidate):
    compact_evidence = [
        replace(item, data={})
        for item in candidate.evidence
    ]
    return replace(
        candidate,
        evidence=compact_evidence,
        metadata={
            "compact_vlm_input": True,
            "source_metadata": candidate.metadata,
        },
    )


def _run_one(
    style: str,
    recording: dict[str, Any],
    candidate,
    output_root: Path,
    config,
    force_refresh: bool,
    compact_vlm_input: bool,
) -> dict[str, Any]:
    rendered = _render(style, recording, candidate, output_root, config)
    request_candidate = _compact_candidate_for_vlm(rendered) if compact_vlm_input else rendered
    client = VlmClient(
        replace(config, output_root=output_root / style),
        cache_dir=output_root / style / "cache",
        raw_dir=output_root / style / "raw_responses" / candidate.scenario,
        request_dir=output_root / style / "request_payloads" / candidate.scenario,
    )
    raw = client.infer(request_candidate, force_refresh=force_refresh)
    raw_text = ""
    validation = None
    error = ""
    try:
        raw_text = extract_message_text(raw)
        validation = parse_and_validate_response(raw_text, rendered, config)
    except Exception as exc:
        error = str(exc)
        validation = parse_and_validate_response("{}", rendered, config)
    decision = validation.decision
    return {
        "style": style,
        "candidate": rendered,
        "raw": raw,
        "raw_text": raw_text,
        "validation": validation,
        "decision": decision,
        "error": error,
    }


def _rel(path: str | Path, base: Path) -> str:
    try:
        return Path(path).resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return str(path)


def _write_outputs(rows: list[dict[str, Any]], output_root: Path) -> None:
    fields = [
        "style",
        "candidate_id",
        "scenario",
        "recording_id",
        "frame_range",
        "expected_decision",
        "model_decision",
        "correct_vs_gt",
        "confidence",
        "accepted_by_validator",
        "review_required",
        "validation_reasons",
        "elapsed_s",
        "error",
    ]
    with (output_root / "scene_results.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fields})

    summary = {}
    for row in rows:
        key = row["style"]
        bucket = summary.setdefault(key, {"style": key, "n": 0, "correct": 0, "errors": 0})
        bucket["n"] += 1
        bucket["correct"] += int(row["correct_vs_gt"] == "True")
        bucket["errors"] += int(bool(row["error"]))
    with (output_root / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = ["style", "n", "correct", "accuracy", "errors"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for item in summary.values():
            writer.writerow(
                {
                    **item,
                    "accuracy": round(item["correct"] / item["n"], 4) if item["n"] else "",
                }
            )


def _html_report(rows: list[dict[str, Any]], output_root: Path) -> str:
    def escaped(value: object) -> str:
        return html.escape(str(value))
    cards = []
    for row in rows:
        imgs = "".join(
            f'<img src="{escaped(_rel(path, output_root))}" alt="BEV">'
            for path in row.get("bev_paths", [])[:6]
        )
        klass = "ok" if row["correct_vs_gt"] == "True" else "bad"
        cards.append(
            f"""
            <article>
              <h2>{escaped(row['style'])} · {escaped(row['candidate_id'])}</h2>
              <div class="strip">{imgs}</div>
              <table>
                <tr><th>GT</th><td>{escaped(row['expected_decision'])}</td></tr>
                <tr><th>Model</th><td class="{klass}">{escaped(row['model_decision'])}</td></tr>
                <tr><th>Confidence</th><td>{escaped(row['confidence'])}</td></tr>
                <tr><th>Validation</th><td>{escaped(row['validation_reasons'])}</td></tr>
                <tr><th>Error</th><td>{escaped(row['error'])}</td></tr>
              </table>
            </article>
            """
        )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>BEV Style GT Experiment</title>
<style>
body {{ margin:0; background:#f5f7fa; color:#1f2937; font:14px/1.45 system-ui,sans-serif; }}
header,main {{ padding:24px 32px; }}
article {{ background:white; border:1px solid #d7e0ea; margin:0 0 18px; padding:14px; }}
h1 {{ margin:0; font-size:24px; }} h2 {{ margin:0 0 10px; font-size:16px; }}
.strip {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:8px; margin-bottom:10px; }}
img {{ width:100%; aspect-ratio:1/1; object-fit:contain; background:#111827; }}
table {{ width:100%; border-collapse:collapse; }} th,td {{ border:1px solid #d7e0ea; padding:6px 8px; text-align:left; }}
.ok {{ color:#137a3a; font-weight:700; }} .bad {{ color:#b42318; font-weight:700; }}
</style></head><body><header><h1>BEV Style GT Experiment</h1></header><main>{''.join(cards)}</main></body></html>"""


def main() -> int:
    args = parse_args()
    if args.write_gt_template:
        _write_gt_template(args.candidate_bundle, args.gt)
        print(f"Wrote GT template: {args.gt}")
        return 0

    styles = tuple(args.style or STYLES)
    config = load_config(
        args.config,
        overrides={
            "input_dir": args.input_dir,
            "output_root": args.output_root,
            "endpoint": args.endpoint,
            "model": args.model,
            "timeout_s": args.timeout_s,
            "cache_enabled": False if args.no_cache else None,
        },
    )
    gt = _load_gt(args.gt)
    args.output_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for bundle_path in args.candidate_bundle:
        candidate = load_candidate_bundle(bundle_path)
        if candidate.candidate_id not in gt:
            raise SystemExit(f"GT missing candidate_id={candidate.candidate_id}")
        expected = _bool_text(gt[candidate.candidate_id].get("expected_decision"))
        if expected is None:
            raise SystemExit(f"GT expected_decision must be true/false for {candidate.candidate_id}")
        recording = load_recording(canonical_path(config.input_dir, candidate.recording_id))
        for style in styles:
            result = _run_one(
                style,
                recording,
                candidate,
                args.output_root,
                config,
                args.force_cache_refresh,
                args.compact_vlm_input,
            )
            decision = result["decision"]
            model_decision = decision.decision if decision is not None else None
            correct = model_decision is expected
            raw = result["raw"]
            rows.append(
                {
                    "style": style,
                    "candidate_id": candidate.candidate_id,
                    "scenario": candidate.scenario,
                    "recording_id": candidate.recording_id,
                    "frame_range": f"{candidate.start_frame}-{candidate.end_frame}",
                    "expected_decision": str(expected),
                    "model_decision": str(model_decision),
                    "correct_vs_gt": str(correct),
                    "confidence": decision.confidence if decision is not None else "",
                    "accepted_by_validator": result["validation"].accepted,
                    "review_required": result["validation"].review_required,
                    "validation_reasons": ";".join(result["validation"].reasons),
                    "elapsed_s": raw.get("elapsed_s", ""),
                    "error": result["error"] or raw.get("error", ""),
                    "bev_paths": result["candidate"].bev_paths,
                }
            )
    _write_outputs(rows, args.output_root)
    html_text = _html_report(rows, args.output_root)
    (args.output_root / "report.html").write_text(html_text, encoding="utf-8")
    (args.output_root / "gallery.html").write_text(html_text, encoding="utf-8")
    print(f"Wrote: {args.output_root / 'scene_results.csv'}")
    print(f"Wrote: {args.output_root / 'summary.csv'}")
    print(f"Wrote: {args.output_root / 'gallery.html'}")
    print(f"Wrote: {args.output_root / 'report.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
