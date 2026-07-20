#!/usr/bin/env python3
"""Run a local OpenAI-compatible vLLM eval on refined model inputs."""

from __future__ import annotations

import argparse
import base64
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_MODEL = "local-vllm"
REPO_ROOT = Path(__file__).resolve().parents[4]
SYSTEM_PROMPT_PATH = REPO_ROOT / "prompts" / "system_prompt.md"
USER_PROMPT_PATHS = {
    "json_only": REPO_ROOT / "prompts" / "json_only_user_prompt.md",
    "json_bev": REPO_ROOT / "prompts" / "json_bev_user_prompt.md",
}
TAXONOMY = [
    "stationary",
    "high_magnitude_speed",
    "low_magnitude_speed",
    "medium_magnitude_speed",
    "following_lane_with_lead",
    "following_lane_without_lead",
    "starting_left_turn",
    "starting_right_turn",
    "stopping_with_lead",
    "stopping_without_lead",
    "near_multiple_pedestrians",
    "near_multiple_motorcycle",
]
REPORT_COLUMNS = [
    "Run",
    "Recording",
    "Window",
    "Model",
    "Mode",
    "Prompt_Profile",
    "Images",
    "Max_Tokens",
    "Prompt_Tokens",
    "Completion_Tokens",
    "Total_Tokens",
    "HTTP_Status",
    "Valid_JSON",
    "Validation_OK",
    "Label_Count",
    "GT_Compared",
    "GT_Correct",
    "GT_Mismatches",
    "Latency_s",
    "Major_Issue",
]
SYSTEM_PROMPT = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def find_refined_files(root: Path, recording: str, limit: int | None) -> list[Path]:
    recording_root = root / recording
    if not recording_root.exists():
        raise FileNotFoundError(f"Recording model-input folder not found: {recording_root}")
    files = sorted(recording_root.rglob("refined.json"))
    if limit is not None:
        files = files[:limit]
    if not files:
        raise FileNotFoundError(f"No refined.json files found under {recording_root}")
    return files


def image_data_url(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"


def sampled_rows(rows: list, keyframes: set[int], step: int = 5) -> list:
    result = []
    for index, row in enumerate(rows):
        frame_index = row.get("frame_index") if isinstance(row, dict) else None
        if index % step == 0 or frame_index in keyframes:
            result.append(row)
    return result


def minimal_object_track(obj: dict, keyframes: set[int]) -> dict:
    samples = obj.get("samples") or []
    return {
        key: obj.get(key)
        for key in (
            "object_id",
            "class",
            "subclass",
            "annotation_type",
            "geometry_source",
            "observed_frame_count",
            "first_frame",
            "last_frame",
            "minimum_distance_m",
            "dimensions_m",
        )
        if key in obj
    } | {
        "samples": sampled_rows(samples, keyframes, step=5)[:8],
    }


def refined_for_prompt(refined: dict, profile: str) -> dict:
    """Keep the model input faithful while controlling prompt size."""
    keyframes = {
        info.get("frame_index")
        for info in (refined.get("bev_keyframes") or {}).values()
        if isinstance(info, dict) and isinstance(info.get("frame_index"), int)
    }
    if profile == "full":
        return refined

    keep = {
        key: refined.get(key)
        for key in (
            "schema_version",
            "recording_id",
            "source_window_id",
            "time_window",
            "taxonomy",
            "ego_summary",
            "ego_series_sampled",
            "ld_summary",
            "ld_series_sampled",
            "data_quality",
            "data_notes",
        )
        if key in refined
    }
    keep["bev_keyframes"] = refined.get("bev_keyframes")
    keep["per_frame_counts"] = sampled_rows(
        refined.get("per_frame_counts") or [],
        keyframes,
        step=1 if profile == "compact" else 5,
    )
    objects = refined.get("relevant_objects") or []
    if profile == "compact":
        keep["relevant_objects"] = objects
    else:
        keep["relevant_objects"] = [
            minimal_object_track(obj, keyframes)
            for obj in objects[:12]
            if isinstance(obj, dict)
        ]
    return keep


def render_user_prompt(mode: str, payload: dict) -> str:
    template = USER_PROMPT_PATHS[mode].read_text(encoding="utf-8").strip()
    return (
        template.replace("{{TAXONOMY_JSON}}", json.dumps(TAXONOMY, ensure_ascii=False))
        .replace("{{MODE}}", mode)
        .replace("{{REFINED_JSON}}", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    )


def build_user_content(
    refined_path: Path,
    mode: str,
    prompt_profile: str,
    image_keyframes: list[str],
) -> list[dict]:
    refined = load_json(refined_path)
    payload = refined_for_prompt(refined, prompt_profile)
    text = render_user_prompt(mode, payload)
    content: list[dict] = [{"type": "text", "text": text}]
    if mode == "json_bev":
        for label in image_keyframes:
            info = refined.get("bev_keyframes", {}).get(label)
            if not isinstance(info, dict):
                continue
            image_path = refined_path.parent / info.get("path", "")
            if image_path.exists():
                content.append({"type": "text", "text": f"BEV keyframe: {label}"})
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": image_data_url(image_path)},
                    }
                )
    return content


def post_chat_completion(
    endpoint: str,
    model: str,
    messages: list[dict],
    max_tokens: int,
    temperature: float,
    timeout_s: float,
) -> dict:
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return json.loads(response.read().decode("utf-8"))


def chat_completion_payload(
    model: str,
    messages: list[dict],
    max_tokens: int,
    temperature: float,
) -> dict:
    return {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "chat_template_kwargs": {
            "enable_thinking": False
        }
    }


def post_chat_completion_payload(
    endpoint: str,
    payload: dict,
    timeout_s: float,
) -> dict:
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return json.loads(response.read().decode("utf-8"))


def http_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def extract_text(response: dict) -> str:
    choices = response.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return ""


def parse_model_output(text: str) -> tuple[dict | None, str | None]:
    if not text:
        return None, "empty model response text"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"model response text is not valid JSON: {exc}"
    if not isinstance(parsed, dict):
        return None, "model response JSON must be an object"
    return parsed, None


def normalize_output_labels(output: dict | None) -> dict[str, dict]:
    if not isinstance(output, dict):
        return {}
    labels = output.get("labels")
    if isinstance(labels, dict):
        return {str(key): value for key, value in labels.items() if isinstance(value, dict)}
    if isinstance(labels, list):
        normalized = {}
        for item in labels:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if name is not None:
                normalized[str(name)] = item
        return normalized
    return {}


def output_label_values(output: dict | None) -> dict[str, bool | None]:
    values = {}
    for label, item in normalize_output_labels(output).items():
        value = item.get("value")
        values[label] = value if isinstance(value, bool) else None
    return values


def load_gt_file(path: Path) -> dict:
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"GT file must be a JSON object: {path}")
    return payload


def gt_windows(payload: dict) -> dict[str, dict]:
    windows = payload.get("windows")
    if isinstance(windows, dict):
        return {str(key): value for key, value in windows.items() if isinstance(value, dict)}
    if isinstance(windows, list):
        result = {}
        for item in windows:
            if not isinstance(item, dict):
                continue
            window_id = item.get("window_id")
            if window_id is not None:
                result[str(window_id)] = item
        return result
    return {}


def output_window_ids(recording: str, window_name: str) -> set[str]:
    if ":" in window_name:
        suffix = window_name.split(":", 1)[1]
        return {window_name, f"{recording}_{suffix}"}
    prefix = f"{recording}_"
    if window_name.startswith(prefix):
        suffix = window_name[len(prefix) :]
        return {window_name, f"{recording}:{suffix}"}
    return {window_name}


def gt_labels_for_window(payload: dict, recording: str, window_id: str) -> dict[str, bool] | None:
    if payload.get("recording_id") not in (None, recording):
        raise ValueError(f"GT recording_id should be {recording}")
    windows = gt_windows(payload)
    window = None
    for candidate_id in output_window_ids(recording, window_id):
        if candidate_id in windows:
            window = windows[candidate_id]
            break
    if window is None:
        return None
    labels = window.get("labels")
    if not isinstance(labels, dict):
        raise ValueError(f"GT window {window_id} has no labels object")
    result = {}
    for label in TAXONOMY:
        value = labels.get(label)
        if isinstance(value, bool):
            result[label] = value
        elif value is not None:
            raise ValueError(f"GT label {window_id}.{label} must be true, false, or null")
    return result


def load_gt_labels(path: Path, recording: str, window_id: str) -> dict[str, bool] | None:
    return gt_labels_for_window(load_gt_file(path), recording, window_id)


def validate_against_gt(output: dict | None, gt_labels: dict[str, bool] | None) -> dict:
    if gt_labels is None:
        return {
            "available": False,
            "compared": 0,
            "correct": None,
            "mismatches": [],
            "missing_gt_labels": [],
            "missing_output_labels": [],
        }
    output_values = output_label_values(output)
    mismatches = []
    missing_output = []
    for label, expected in gt_labels.items():
        actual = output_values.get(label)
        if actual is None:
            missing_output.append(label)
        elif actual != expected:
            mismatches.append({"label": label, "expected": expected, "actual": actual})
    missing_gt = [label for label in TAXONOMY if label not in gt_labels]
    return {
        "available": True,
        "status": "passed" if not mismatches and not missing_output else "failed",
        "compared": len(gt_labels),
        "correct": not mismatches and not missing_output,
        "mismatches": mismatches,
        "missing_gt_labels": missing_gt,
        "missing_output_labels": missing_output,
    }


def retry_prompt(errors: list[str]) -> str:
    return (
        "The previous response failed validation. Return only corrected JSON. "
        "Shorten arrays: evidence_frames array must have at most 3 items and "
        "object_ids array must have at most 2 items. For false labels, set "
        "evidence_frames=[] and object_ids=[]. For ego-only labels, do not use "
        "object IDs. Do not use default object IDs. For speed-band labels, set "
        "evidence_frames=[] and object_ids=[]. Errors: "
        + "; ".join(errors)
    )


def validate_output(
    output: dict | None,
    recording: str,
    window_name: str,
    mode: str,
    refined: dict,
) -> list[str]:
    validation = validate_model_output(output, refined | {"recording_id": recording}, mode)
    errors = list(validation["errors"])
    labels = normalize_output_labels(output)
    speed_labels = {"low_magnitude_speed", "medium_magnitude_speed", "high_magnitude_speed"}
    ego_only_labels = speed_labels | {"stationary", "starting_left_turn", "starting_right_turn"}
    for label, item in labels.items():
        evidence_frames = item.get("evidence_frames") or []
        object_ids = item.get("object_ids") or []
        value = item.get("value")
        if len(evidence_frames) > 3:
            errors.append(f"labels.{label}.evidence_frames must contain at most 3 items")
        if len(object_ids) > 2:
            errors.append(f"labels.{label}.object_ids must contain at most 2 items")
        if label in speed_labels and evidence_frames:
            errors.append(f"labels.{label}.evidence_frames must be empty for speed-band labels")
        if label in speed_labels and object_ids:
            errors.append(f"labels.{label}.object_ids must be empty for speed-band labels")
        if value is False and evidence_frames:
            errors.append(f"labels.{label}.evidence_frames must be empty for false labels")
        if value is False and object_ids:
            errors.append(f"labels.{label}.object_ids must be empty for false labels")
        if label in ego_only_labels and label not in speed_labels and object_ids:
            errors.append(f"labels.{label}.object_ids must be empty for ego-only labels")
    return errors


def gt_mismatch_summary(gt_validation: dict) -> str:
    if not gt_validation.get("available"):
        return "n/a"
    parts = [
        f"{item['label']} expected={item['expected']} actual={item['actual']}"
        for item in gt_validation.get("mismatches", [])
    ]
    parts.extend(
        f"missing_output={label}"
        for label in gt_validation.get("missing_output_labels", [])
    )
    return "; ".join(parts) if parts else "none"


def validate_model_output(
    parsed_output: dict | None,
    refined: dict,
    mode: str,
    parse_error: str | None = None,
) -> dict:
    errors = []
    warnings = []
    if parse_error:
        errors.append(parse_error)
    if parsed_output is None:
        return {"ok": False, "errors": errors or ["missing parsed model output"], "warnings": warnings}

    recording_id = refined.get("recording_id")
    window_id = refined.get("source_window_id")
    output_window_id = parsed_output.get("window_id")
    if parsed_output.get("recording_id") not in (None, recording_id):
        errors.append(f"recording_id should be {recording_id}")
    if output_window_id not in (window_id, None):
        errors.append(f"window_id should be {window_id}")
    if parsed_output.get("model_mode") not in (None, mode):
        errors.append(f"model_mode should be {mode}")

    labels = normalize_output_labels(parsed_output)
    if not labels:
        errors.append("labels must be a non-empty object or list")
    unknown = sorted(set(labels) - set(TAXONOMY))
    if unknown:
        errors.append(f"unknown labels: {unknown}")
    missing = sorted(set(TAXONOMY) - set(labels))
    if missing:
        warnings.append(f"missing taxonomy labels: {missing}")
    for label, item in labels.items():
        confidence = item.get("confidence")
        if confidence is not None and (
            not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1
        ):
            errors.append(f"labels.{label}.confidence must be in [0,1]")
        if "evidence" not in item and "evidence_summary" not in item:
            warnings.append(f"labels.{label} has no evidence/evidence_summary")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "label_count": len(labels),
        "labels_present": sorted(labels),
    }


def clear_generated_files(output_dir: Path) -> None:
    for name in (
        "request.json",
        "raw_response.json",
        "model_output.json",
        "validation.json",
    ):
        path = output_dir / name
        if path.exists():
            path.unlink()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_outputs(
    output_dir: Path,
    request_payload: dict,
    raw_response: dict,
    model_output: dict | None,
    validation: dict,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    clear_generated_files(output_dir)
    write_json(output_dir / "request.json", request_payload)
    write_json(output_dir / "raw_response.json", raw_response)
    if model_output is not None:
        write_json(output_dir / "model_output.json", model_output)
    write_json(output_dir / "validation.json", validation)


def next_run_id(output_root: Path) -> str:
    report_tsv = output_root / "run_report.tsv"
    max_seen = 0
    if report_tsv.exists():
        with report_tsv.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                run_id = row.get("Run", "")
                if run_id.startswith("R") and run_id[1:].isdigit():
                    max_seen = max(max_seen, int(run_id[1:]))
    runs_dir = output_root / "runs"
    if runs_dir.exists():
        for path in runs_dir.iterdir():
            if path.is_dir() and path.name.startswith("R") and path.name[1:].isdigit():
                max_seen = max(max_seen, int(path.name[1:]))
    return f"R{max_seen + 1:03d}"


def response_usage(raw_response: dict) -> dict:
    return raw_response.get("usage", {}) if isinstance(raw_response, dict) else {}


def report_row(
    run_id: str,
    recording: str,
    window_id: str,
    model: str,
    mode: str,
    prompt_profile: str,
    image_keyframes: list[str],
    max_tokens: int,
    raw_response: dict,
    model_output: dict | None,
    validation: dict,
    gt_validation: dict,
    latency_s: float,
) -> dict[str, str]:
    usage = response_usage(raw_response)
    errors = validation.get("errors") or []
    warnings = validation.get("warnings") or []
    major_issue = "none"
    if errors:
        major_issue = "; ".join(str(error) for error in errors[:2])
    elif warnings:
        major_issue = "; ".join(str(warning) for warning in warnings[:2])
    return {
        "Run": run_id,
        "Recording": recording,
        "Window": window_id,
        "Model": model,
        "Mode": mode,
        "Prompt_Profile": prompt_profile,
        "Images": ",".join(image_keyframes) if mode == "json_bev" else "n/a",
        "Max_Tokens": str(max_tokens),
        "Prompt_Tokens": str(usage.get("prompt_tokens", "")),
        "Completion_Tokens": str(usage.get("completion_tokens", "")),
        "Total_Tokens": str(usage.get("total_tokens", "")),
        "HTTP_Status": str(raw_response.get("http_status", "") if isinstance(raw_response, dict) else ""),
        "Valid_JSON": "yes" if model_output is not None else "no",
        "Validation_OK": "yes" if validation.get("ok") else "no",
        "Label_Count": str(validation.get("label_count", "")),
        "GT_Compared": str(gt_validation.get("compared", "n/a"))
        if gt_validation.get("available")
        else "n/a",
        "GT_Correct": "yes" if gt_validation.get("correct") is True else "no"
        if gt_validation.get("correct") is False
        else "n/a",
        "GT_Mismatches": gt_mismatch_summary(gt_validation),
        "Latency_s": f"{latency_s:.3f}",
        "Major_Issue": major_issue,
    }


def write_report_files(output_root: Path, new_rows: list[dict[str, str]]) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    report_tsv = output_root / "run_report.tsv"
    report_md = output_root / "run_report.md"
    rows: list[dict[str, str]] = []
    if report_tsv.exists():
        with report_tsv.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
    rows.extend(new_rows)
    with report_tsv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=REPORT_COLUMNS,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "| " + " | ".join(REPORT_COLUMNS) + " |",
        "| " + " | ".join("---" for _ in REPORT_COLUMNS) + " |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(str(row.get(col, "")).replace("|", "\\|") for col in REPORT_COLUMNS)
            + " |"
        )
    report_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def safe_name(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in text).strip("_")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a local vLLM eval over refined model-input windows."
    )
    parser.add_argument("--recording", required=True)
    parser.add_argument(
        "--mode",
        choices=("json_only", "json_bev"),
        default="json_bev",
    )
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--model-input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--max-tokens", type=int, default=1800)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--prompt-profile",
        choices=("minimal", "compact", "full"),
        default="minimal",
        help="Prompt detail level. minimal is recommended for 16k local VLM context.",
    )
    parser.add_argument(
        "--image-keyframes",
        default="start,middle,end",
        help="Comma-separated BEV keyframes to send in json_bev mode.",
    )
    parser.add_argument(
        "--gt-labels",
        type=Path,
        default=None,
        help="Optional GT JSON file. When supplied, compare model label values and report GT columns.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        refined_files = find_refined_files(
            args.model_input_root, args.recording, args.limit
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    output_dir = args.output_root / args.recording / args.mode
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = next_run_id(args.output_root)
    run_root = args.output_root / "runs" / run_id
    manifest = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "recording": args.recording,
        "mode": args.mode,
        "prompt_profile": args.prompt_profile,
        "image_keyframes": [
            item.strip() for item in args.image_keyframes.split(",") if item.strip()
        ],
        "endpoint": args.endpoint,
        "model": args.model,
        "window_count": len(refined_files),
        "outputs": [],
    }
    report_rows = []
    gt_payload = None
    if args.gt_labels is not None:
        try:
            gt_payload = load_gt_file(args.gt_labels)
            if gt_payload.get("recording_id") not in (None, args.recording):
                raise ValueError(f"GT recording_id should be {args.recording}")
        except Exception as exc:
            print(f"ERROR: failed to load GT labels: {exc}", file=sys.stderr)
            return 2

    for index, refined_path in enumerate(refined_files, 1):
        refined = load_json(refined_path)
        window_id = refined.get("source_window_id") or refined_path.parent.name
        safe_window_id = safe_name(window_id)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_user_content(
                    refined_path,
                    args.mode,
                    args.prompt_profile,
                    manifest["image_keyframes"],
                ),
            },
        ]
        request_payload = chat_completion_payload(
            args.model,
            messages,
            args.max_tokens,
            args.temperature,
        )
        request_payload["_metadata"] = {
            "run_id": run_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "endpoint": args.endpoint,
            "recording_id": args.recording,
            "window_id": window_id,
            "refined_json": str(refined_path),
            "mode": args.mode,
            "prompt_profile": args.prompt_profile,
            "image_keyframes": manifest["image_keyframes"],
        }
        started = time.time()
        latest_window_dir = output_dir / safe_window_id
        run_window_dir = run_root / safe_window_id
        raw_response: dict
        model_output: dict | None = None
        try:
            raw_response = post_chat_completion_payload(
                args.endpoint,
                request_payload,
                args.timeout_s,
            )
            response_text = extract_text(raw_response)
            model_output, parse_error = parse_model_output(response_text)
            validation = validate_model_output(
                model_output,
                refined,
                args.mode,
                parse_error=parse_error,
            )
            gt_labels = None
            if gt_payload is not None:
                gt_labels = gt_labels_for_window(gt_payload, args.recording, window_id)
            gt_validation = validate_against_gt(model_output, gt_labels)
            validation["gt_validation"] = gt_validation
            result = {
                "recording_id": args.recording,
                "window_id": window_id,
                "mode": args.mode,
                "refined_json": str(refined_path),
                "latency_s": round(time.time() - started, 3),
                "validation_ok": validation["ok"],
            }
            print(
                f"[{index}/{len(refined_files)}] "
                f"{'OK' if validation['ok'] else 'VALIDATION_FAIL'} {window_id}"
            )
        except urllib.error.HTTPError as exc:
            body = http_error_body(exc)
            raw_response = {
                "ok": False,
                "http_status": exc.code,
                "error": str(exc),
                "response_body": body,
            }
            validation = {
                "ok": False,
                "errors": [f"HTTP {exc.code}: {body or exc}"],
                "warnings": [],
                "label_count": 0,
                "labels_present": [],
            }
            gt_labels = None
            if gt_payload is not None:
                gt_labels = gt_labels_for_window(gt_payload, args.recording, window_id)
            gt_validation = validate_against_gt(None, gt_labels)
            validation["gt_validation"] = gt_validation
            result = {
                "recording_id": args.recording,
                "window_id": window_id,
                "mode": args.mode,
                "prompt_profile": args.prompt_profile,
                "refined_json": str(refined_path),
                "latency_s": round(time.time() - started, 3),
                "validation_ok": False,
            }
            print(f"[{index}/{len(refined_files)}] HTTP {exc.code} {window_id}: {body[:500] or exc}")
        except (urllib.error.URLError, TimeoutError, Exception) as exc:
            raw_response = {"ok": False, "error": str(exc)}
            validation = {
                "ok": False,
                "errors": [str(exc)],
                "warnings": [],
                "label_count": 0,
                "labels_present": [],
            }
            gt_labels = None
            if gt_payload is not None:
                try:
                    gt_labels = gt_labels_for_window(gt_payload, args.recording, window_id)
                except Exception:
                    gt_labels = None
            gt_validation = validate_against_gt(None, gt_labels)
            validation["gt_validation"] = gt_validation
            result = {
                "recording_id": args.recording,
                "window_id": window_id,
                "mode": args.mode,
                "prompt_profile": args.prompt_profile,
                "refined_json": str(refined_path),
                "latency_s": round(time.time() - started, 3),
                "validation_ok": False,
            }
            print(f"[{index}/{len(refined_files)}] ERROR {window_id}: {exc}")
        latency_s = result["latency_s"]
        write_outputs(
            run_window_dir,
            request_payload,
            raw_response,
            model_output,
            validation,
        )
        write_outputs(
            latest_window_dir,
            request_payload,
            raw_response,
            model_output,
            validation,
        )
        row = report_row(
            run_id,
            args.recording,
            window_id,
            args.model,
            args.mode,
            args.prompt_profile,
            manifest["image_keyframes"],
            args.max_tokens,
            raw_response,
            model_output,
            validation,
            gt_validation,
            latency_s,
        )
        report_rows.append(row)
        manifest["outputs"].append(
            {
                "window_id": window_id,
                "run_directory": str(run_window_dir),
                "latest_directory": str(latest_window_dir),
                "ok": validation["ok"],
            }
        )

    write_report_files(args.output_root, report_rows)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {manifest_path}")
    print(f"Wrote {args.output_root / 'run_report.tsv'}")
    print(f"Wrote {args.output_root / 'run_report.md'}")
    return 0 if all(item["ok"] for item in manifest["outputs"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
