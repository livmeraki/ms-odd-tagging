"""Run factual VLM-understanding probes over BEV and structured evidence.

The goal is diagnostic rather than scenario classification: isolate whether the VLM
can read the custom BEV visual language, understand neutral structured evidence,
and combine them consistently.
"""

from __future__ import annotations

import base64
import csv
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SYSTEM_PROMPT = """You are auditing your perception of autonomous-driving diagnostic inputs.
Answer only from the supplied BEV image(s) and/or structured neutral evidence.
Do not infer a motional-scenario label unless the question explicitly asks for one.
Do not assume the meaning of a color, line, or symbol unless a legend is supplied or the visual itself makes it unambiguous.
If the evidence is insufficient, use unknown.

For each probe, produce three explicit stages:
1. perceived_answer: the literal answer supported directly by what you perceive in the input.
2. reasoned_answer: the answer after applying only the conventions/rules stated in the prompt or legend.
3. answer: your final answer to the question.

These three fields should agree unless there is a genuine ambiguity. Never write one answer in your reasoning and a contradictory value in the final answer.
Return valid JSON with exactly these keys:
perceived_answer, reasoned_answer, answer, observations, confidence, used_visual_cues, used_structured_fields, ambiguity.
confidence must be a number from 0 to 1. observations, used_visual_cues, and used_structured_fields must be arrays of strings.
ambiguity must be either an empty string or a short string.
"""


@dataclass(frozen=True)
class Probe:
    probe_id: str
    sample_id: str
    category: str
    modality: str
    question: str
    expected_answer: Any
    images: tuple[Path, ...]
    structured_evidence: Any | None
    legend: Any | None
    notes: str | None = None


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_value(value: Any, base_dir: Path) -> Any:
    if isinstance(value, dict) and set(value) == {"json_file"}:
        return _load_json((base_dir / value["json_file"]).resolve())
    return value


def load_manifest(path: Path) -> list[Probe]:
    payload = _load_json(path)
    base_dir = path.parent
    probes: list[Probe] = []
    for raw in payload.get("probes", []):
        images = tuple((base_dir / item).resolve() for item in raw.get("images", []))
        probes.append(
            Probe(
                probe_id=str(raw["probe_id"]),
                sample_id=str(raw.get("sample_id") or raw["probe_id"]),
                category=str(raw["category"]),
                modality=str(raw["modality"]),
                question=str(raw["question"]),
                expected_answer=raw.get("expected_answer"),
                images=images,
                structured_evidence=_resolve_value(raw.get("structured_evidence"), base_dir),
                legend=_resolve_value(raw.get("legend"), base_dir),
                notes=raw.get("notes"),
            )
        )
    return probes


def _encode_image(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _request_payload(probe: Probe, model: str, temperature: float, max_tokens: int) -> dict[str, Any]:
    user_text = [
        f"Probe category: {probe.category}",
        f"Input modality: {probe.modality}",
        f"Question: {probe.question}",
    ]
    if probe.legend is not None:
        user_text.append("BEV legend:\n" + json.dumps(probe.legend, ensure_ascii=False, sort_keys=True))
    if probe.structured_evidence is not None:
        user_text.append(
            "Structured neutral evidence:\n"
            + json.dumps(probe.structured_evidence, ensure_ascii=False, sort_keys=True)
        )
    user_text.append(
        "Important: report literal observations first internally, then keep perceived_answer, "
        "reasoned_answer, and answer mutually consistent. The expected answer is not provided to you."
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": "\n\n".join(user_text)}]
    for image in probe.images:
        if not image.is_file():
            raise FileNotFoundError(image)
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{_encode_image(image)}"},
            }
        )
    return {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
    }


def _extract_text(response: dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if not choices:
        raise ValueError("response missing choices")
    content = (choices[0].get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(item.get("text") or "") for item in content if isinstance(item, dict))
    raise ValueError("response message content is not text")


def _normalize(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True).strip().lower()
    return str(value).strip().lower()


def _score(expected: Any, answer: Any) -> bool | None:
    if expected is None:
        return None
    if isinstance(expected, list):
        answer_norm = _normalize(answer)
        return any(_normalize(item) == answer_norm for item in expected)
    return _normalize(expected) == _normalize(answer)


def _consistent(*values: Any) -> bool:
    normalized = [_normalize(value) for value in values if value is not None]
    return bool(normalized) and len(set(normalized)) == 1


def run_probe(
    probe: Probe,
    *,
    endpoint: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout_s: float,
) -> dict[str, Any]:
    payload = _request_payload(probe, model, temperature, max_tokens)
    started = time.monotonic()
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            raw_response = json.loads(response.read().decode("utf-8"))
        text = _extract_text(raw_response)
        parsed = json.loads(text)
        perceived = parsed.get("perceived_answer")
        reasoned = parsed.get("reasoned_answer")
        final_answer = parsed.get("answer")
        perception_correct = _score(probe.expected_answer, perceived)
        reasoning_correct = _score(probe.expected_answer, reasoned)
        final_answer_correct = _score(probe.expected_answer, final_answer)
        response_consistent = _consistent(perceived, reasoned, final_answer)
        return {
            "probe_id": probe.probe_id,
            "sample_id": probe.sample_id,
            "category": probe.category,
            "modality": probe.modality,
            "question": probe.question,
            "expected_answer": probe.expected_answer,
            "images": [str(path) for path in probe.images],
            "notes": probe.notes,
            "ok": True,
            "elapsed_s": round(time.monotonic() - started, 4),
            "perception_correct": perception_correct,
            "reasoning_correct": reasoning_correct,
            "final_answer_correct": final_answer_correct,
            "response_consistent": response_consistent,
            # Backward-compatible alias. Summary now uses final_answer_correct.
            "correct": final_answer_correct,
            "model_output": parsed,
        }
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return {
            "probe_id": probe.probe_id,
            "sample_id": probe.sample_id,
            "category": probe.category,
            "modality": probe.modality,
            "question": probe.question,
            "expected_answer": probe.expected_answer,
            "images": [str(path) for path in probe.images],
            "notes": probe.notes,
            "ok": False,
            "elapsed_s": round(time.monotonic() - started, 4),
            "perception_correct": None,
            "reasoning_correct": None,
            "final_answer_correct": None,
            "response_consistent": None,
            "correct": None,
            "error": str(exc),
        }


def write_outputs(results: list[dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / "probe_results.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as stream:
        for result in results:
            stream.write(json.dumps(result, ensure_ascii=False) + "\n")

    rows = []
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for result in results:
        key = (str(result["category"]), str(result["modality"]))
        if result.get("final_answer_correct") is not None:
            buckets.setdefault(key, []).append(result)
    for (category, modality), values in sorted(buckets.items()):
        n = len(values)
        perception = [bool(v["perception_correct"]) for v in values]
        reasoning = [bool(v["reasoning_correct"]) for v in values]
        final = [bool(v["final_answer_correct"]) for v in values]
        consistent = [bool(v["response_consistent"]) for v in values]
        rows.append(
            {
                "category": category,
                "modality": modality,
                "scored_probes": n,
                "perception_accuracy": round(sum(perception) / n, 4),
                "reasoning_accuracy": round(sum(reasoning) / n, 4),
                "final_answer_accuracy": round(sum(final) / n, 4),
                "response_consistency": round(sum(consistent) / n, 4),
            }
        )
    summary_fields = [
        "category",
        "modality",
        "scored_probes",
        "perception_accuracy",
        "reasoning_accuracy",
        "final_answer_accuracy",
        "response_consistency",
    ]
    with (output_dir / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=summary_fields)
        writer.writeheader()
        writer.writerows(rows)

    with (output_dir / "review.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "probe_id",
                "sample_id",
                "category",
                "modality",
                "question",
                "expected_answer",
                "perceived_answer",
                "reasoned_answer",
                "final_answer",
                "perception_correct",
                "reasoning_correct",
                "final_answer_correct",
                "response_consistent",
                "confidence",
                "ambiguity",
                "elapsed_s",
            ],
        )
        writer.writeheader()
        for result in results:
            output = result.get("model_output") or {}
            writer.writerow(
                {
                    "probe_id": result["probe_id"],
                    "sample_id": result["sample_id"],
                    "category": result["category"],
                    "modality": result["modality"],
                    "question": result["question"],
                    "expected_answer": json.dumps(result.get("expected_answer"), ensure_ascii=False),
                    "perceived_answer": json.dumps(output.get("perceived_answer"), ensure_ascii=False),
                    "reasoned_answer": json.dumps(output.get("reasoned_answer"), ensure_ascii=False),
                    "final_answer": json.dumps(output.get("answer"), ensure_ascii=False),
                    "perception_correct": result.get("perception_correct"),
                    "reasoning_correct": result.get("reasoning_correct"),
                    "final_answer_correct": result.get("final_answer_correct"),
                    "response_consistent": result.get("response_consistent"),
                    "confidence": output.get("confidence"),
                    "ambiguity": output.get("ambiguity"),
                    "elapsed_s": result.get("elapsed_s"),
                }
            )
