"""OpenAI-compatible chat completions client for local vLLM/Qwen."""

from __future__ import annotations

import base64
import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .bev_legend import bev_legend_text
from .config import VlmPocConfig
from .evidence import stable_json
from .models import CandidateWindow


PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


def read_prompt(scenario: str) -> tuple[str, str]:
    system = (PROMPT_DIR / "system.txt").read_text(encoding="utf-8").strip()
    scenario_prompt = (PROMPT_DIR / f"{scenario}.txt").read_text(encoding="utf-8").strip()
    return system, scenario_prompt


def encode_image(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _vlm_candidate_input(candidate: CandidateWindow) -> dict[str, Any]:
    """Return the model-facing candidate payload.

    Event-driven waiting-for-pedestrian evaluation keeps candidate-generation
    heuristics hidden. The model receives BEV ordering plus neutral ego speed and
    timestamp measurements aligned to the same selected frames.
    """
    if (
        candidate.scenario == "waiting_for_pedestrian_to_cross"
        and candidate.metadata.get("candidate_strategy") == "event-driven"
    ):
        return {
            "recording_id": candidate.recording_id,
            "scenario": candidate.scenario,
            "window_start_frame": candidate.start_frame,
            "window_end_frame": candidate.end_frame,
            "candidate_scene_id": candidate.candidate_id,
            "target_pedestrian_ids": list(candidate.primary_object_ids),
            "bev_frame_indices": list(candidate.selected_frame_indices),
            "ego_measurements": list(candidate.metadata.get("ego_measurements") or []),
            "visual_evidence_id": candidate.metadata.get("visual_evidence_id"),
            "bev_images_follow_in_same_order": True,
            "evaluation_mode": "bev_plus_neutral_ego_measurements",
        }
    return candidate.to_dict()


def cache_key(candidate: CandidateWindow, config: VlmPocConfig) -> str:
    image_digests = []
    for raw_path in candidate.bev_paths:
        path = Path(raw_path)
        image_digests.append(
            {
                "path_name": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
            }
        )
    data = {
        "model": config.model,
        "prompt_version": config.prompt_version,
        "scenario": candidate.scenario,
        "model_input": _vlm_candidate_input(candidate),
        "bev_legend": bev_legend_text(),
        "images": image_digests,
        "settings": {
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "response_format_json": config.response_format_json,
            "endpoint": config.endpoint,
            "max_bev_images": config.max_bev_images,
            "window_seconds": config.window_seconds,
        },
    }
    return hashlib.sha256(stable_json(data).encode("utf-8")).hexdigest()


class VlmClient:
    def __init__(
        self,
        config: VlmPocConfig,
        *,
        cache_dir: Path | None = None,
        raw_dir: Path | None = None,
        request_dir: Path | None = None,
    ):
        self.config = config
        self.cache_dir = cache_dir
        self.raw_dir = raw_dir
        self.request_dir = request_dir

    def _payload(self, candidate: CandidateWindow) -> dict[str, Any]:
        system_prompt, scenario_prompt = read_prompt(candidate.scenario)
        model_input = _vlm_candidate_input(candidate)
        text = (
            f"{scenario_prompt}\n\n"
            f"{bev_legend_text()}\n\n"
            f"Prompt version: {self.config.prompt_version}\n"
            f"Model input JSON:\n{stable_json(model_input)}"
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        for path in candidate.bev_paths[: self.config.max_bev_images]:
            image_path = Path(path)
            if not image_path.is_file():
                continue
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{encode_image(image_path)}"
                    },
                }
            )
        return {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            **({"response_format": {"type": "json_object"}} if self.config.response_format_json else {}),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
        }

    def infer(self, candidate: CandidateWindow, *, force_refresh: bool = False) -> dict[str, Any]:
        key = cache_key(candidate, self.config)
        cache_path = self.cache_dir / f"{key}.json" if self.cache_dir else None
        if (
            self.config.cache_enabled
            and not force_refresh
            and cache_path is not None
            and cache_path.is_file()
        ):
            return json.loads(cache_path.read_text(encoding="utf-8"))

        payload = self._payload(candidate)
        self._persist_request(key, candidate, payload)
        payload_bytes = json.dumps(payload).encode("utf-8")
        if len(payload_bytes) > self.config.max_request_bytes:
            raise ValueError(
                f"request too large: {len(payload_bytes)} bytes > {self.config.max_request_bytes}"
            )
        headers = {"Content-Type": "application/json"}
        last_error = None
        for attempt in range(self.config.retries + 1):
            started = time.monotonic()
            try:
                request = urllib.request.Request(
                    self.config.endpoint,
                    data=payload_bytes,
                    headers=headers,
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=self.config.timeout_s) as response:
                    text = response.read().decode("utf-8")
                data = json.loads(text)
                result = {
                    "cache_key": key,
                    "candidate_id": candidate.candidate_id,
                    "ok": True,
                    "elapsed_s": round(time.monotonic() - started, 6),
                    "response": data,
                }
                self._persist(cache_path, result)
                return result
            except urllib.error.HTTPError as exc:
                try:
                    body = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    body = ""
                last_error = RuntimeError(f"HTTP Error {exc.code}: {exc.reason}; body={body[:2000]}")
                if attempt < self.config.retries:
                    time.sleep(min(2.0, 0.25 * (attempt + 1)))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                if attempt < self.config.retries:
                    time.sleep(min(2.0, 0.25 * (attempt + 1)))
        result = {
            "cache_key": key,
            "candidate_id": candidate.candidate_id,
            "ok": False,
            "error": str(last_error),
        }
        self._persist(cache_path, result)
        return result

    def _persist(self, cache_path: Path | None, result: dict[str, Any]) -> None:
        if self.raw_dir is not None:
            self.raw_dir.mkdir(parents=True, exist_ok=True)
            (self.raw_dir / f"{result['candidate_id']}_{result['cache_key']}.json").write_text(
                json.dumps(result, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        if cache_path is not None and self.config.cache_enabled:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(result, indent=2, sort_keys=True),
                encoding="utf-8",
            )

    def _persist_request(
        self,
        key: str,
        candidate: CandidateWindow,
        payload: dict[str, Any],
    ) -> None:
        if self.request_dir is None:
            return
        self.request_dir.mkdir(parents=True, exist_ok=True)
        path = self.request_dir / f"{candidate.candidate_id}_{key}.json"
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def extract_message_text(raw_result: dict[str, Any]) -> str:
    if not raw_result.get("ok"):
        raise ValueError(raw_result.get("error") or "inference failed")
    response = raw_result.get("response") or {}
    choices = response.get("choices") or []
    if not choices:
        raise ValueError("response missing choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(item.get("text") or "") for item in content if isinstance(item, dict))
    raise ValueError("response message content is not text")
