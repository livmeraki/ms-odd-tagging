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


def _uniform_rows(rows: list[Any], count: int) -> list[Any]:
    if count <= 0 or not rows:
        return []
    if len(rows) <= count:
        return list(rows)
    if count == 1:
        return [rows[len(rows) // 2]]
    positions = [round(i * (len(rows) - 1) / (count - 1)) for i in range(count)]
    return [rows[pos] for pos in positions]


def _compact_tracks_reference(value: Any, max_points_per_track: int) -> Any:
    """Downsample neutral pedestrian tracks without adding semantic labels."""
    if not isinstance(value, dict):
        return value
    compact = dict(value)
    tracks = value.get("tracks")
    if isinstance(tracks, dict):
        compact["tracks"] = {
            str(object_id): _uniform_rows(points, max_points_per_track)
            if isinstance(points, list)
            else points
            for object_id, points in tracks.items()
        }
    return compact


def _vlm_candidate_input(
    candidate: CandidateWindow,
    *,
    overflow_compact: bool = False,
) -> dict[str, Any]:
    """Return compact model-facing evidence for one candidate.

    For event-driven waiting-for-pedestrian evaluation, spatial geometry is carried
    primarily by the BEVs: they already contain the future ego corridor, numbered
    candidate pedestrians, and observed pedestrian trails. Structured input keeps
    only the temporal evidence that materially complements those images.

    ``overflow_compact`` is a second-stage context-overflow fallback. It further
    downsamples dense temporal series but never injects semantic truth labels.
    """
    if (
        candidate.scenario == "waiting_for_pedestrian_to_cross"
        and candidate.metadata.get("candidate_strategy") == "event-driven"
    ):
        ego_speed_series = list(candidate.metadata.get("ego_speed_series") or [])
        pedestrian_tracks = candidate.metadata.get("pedestrian_tracks_reference")
        if overflow_compact:
            ego_speed_series = _uniform_rows(ego_speed_series, 12)
            pedestrian_tracks = _compact_tracks_reference(pedestrian_tracks, 10)

        return {
            "recording_id": candidate.recording_id,
            "scenario": candidate.scenario,
            "window_start_frame": candidate.start_frame,
            "window_end_frame": candidate.end_frame,
            "target_pedestrian_ids": list(candidate.primary_object_ids),
            "bev_frame_indices": list(candidate.selected_frame_indices),
            "coordinate_convention": {
                "bev": "ego_centered_heading_up",
                "pedestrian_track": "single_fixed_ego_reference_frame",
                "axes": "longitudinal_positive_ahead_lateral_positive_left",
            },
            "ego_speed_series": ego_speed_series,
            "pedestrian_tracks_reference": pedestrian_tracks,
            "visual_evidence_id": candidate.metadata.get("visual_evidence_id"),
            "evaluation_mode": (
                "compact_overflow_retry_bev_tracks_speed"
                if overflow_compact
                else "compact_bev_tracks_speed"
            ),
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


def _even_image_positions(length: int, count: int) -> list[int]:
    if length <= 0 or count <= 0:
        return []
    if length <= count:
        return list(range(length))
    if count == 1:
        return [length // 2]
    return sorted(set(round(i * (length - 1) / (count - 1)) for i in range(count)))


def _is_context_overflow_http_error(exc: urllib.error.HTTPError, body: str) -> bool:
    if exc.code != 400:
        return False
    text = body.lower()
    return (
        "maximum context length" in text
        or "max context length" in text
        or ("input length" in text and "exceeds" in text)
    )


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

    def _payload(
        self,
        candidate: CandidateWindow,
        *,
        overflow_compact: bool = False,
    ) -> dict[str, Any]:
        system_prompt, scenario_prompt = read_prompt(candidate.scenario)
        model_input = _vlm_candidate_input(candidate, overflow_compact=overflow_compact)
        text = (
            f"{scenario_prompt}\n\n"
            f"{bev_legend_text()}\n\n"
            f"Prompt version: {self.config.prompt_version}\n"
            f"Model input JSON:\n{stable_json(model_input)}"
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]

        paths = list(candidate.bev_paths[: self.config.max_bev_images])
        if overflow_compact and candidate.scenario == "waiting_for_pedestrian_to_cross":
            positions = _even_image_positions(len(paths), min(4, len(paths)))
            paths = [paths[pos] for pos in positions]

        for raw_path in paths:
            image_path = Path(raw_path)
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

    def _send_payload(self, payload: dict[str, Any]) -> tuple[dict[str, Any], float]:
        payload_bytes = json.dumps(payload).encode("utf-8")
        if len(payload_bytes) > self.config.max_request_bytes:
            raise ValueError(
                f"request too large: {len(payload_bytes)} bytes > {self.config.max_request_bytes}"
            )
        headers = {"Content-Type": "application/json"}
        started = time.monotonic()
        request = urllib.request.Request(
            self.config.endpoint,
            data=payload_bytes,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.config.timeout_s) as response:
            text = response.read().decode("utf-8")
        return json.loads(text), round(time.monotonic() - started, 6)

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
        self._persist_request(key, candidate, payload, suffix="full")
        last_error = None
        used_overflow_compaction = False

        for attempt in range(self.config.retries + 1):
            try:
                data, elapsed_s = self._send_payload(payload)
                result = {
                    "cache_key": key,
                    "candidate_id": candidate.candidate_id,
                    "ok": True,
                    "elapsed_s": elapsed_s,
                    "context_overflow_compacted": used_overflow_compaction,
                    "response": data,
                }
                self._persist(cache_path, result)
                return result
            except urllib.error.HTTPError as exc:
                try:
                    body = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    body = ""

                can_compact = (
                    not used_overflow_compaction
                    and candidate.scenario == "waiting_for_pedestrian_to_cross"
                    and candidate.metadata.get("candidate_strategy") == "event-driven"
                    and _is_context_overflow_http_error(exc, body)
                )
                if can_compact:
                    used_overflow_compaction = True
                    payload = self._payload(candidate, overflow_compact=True)
                    self._persist_request(key, candidate, payload, suffix="overflow_compact")
                    # This is a deterministic retry mode, not a normal network retry.
                    try:
                        data, elapsed_s = self._send_payload(payload)
                        result = {
                            "cache_key": key,
                            "candidate_id": candidate.candidate_id,
                            "ok": True,
                            "elapsed_s": elapsed_s,
                            "context_overflow_compacted": True,
                            "response": data,
                        }
                        self._persist(cache_path, result)
                        return result
                    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as compact_exc:
                        last_error = compact_exc
                        if isinstance(compact_exc, urllib.error.HTTPError):
                            try:
                                compact_body = compact_exc.read().decode("utf-8", errors="replace")
                            except Exception:
                                compact_body = ""
                            last_error = RuntimeError(
                                f"HTTP Error {compact_exc.code}: {compact_exc.reason}; body={compact_body[:2000]}"
                            )
                    if attempt < self.config.retries:
                        time.sleep(min(2.0, 0.25 * (attempt + 1)))
                    continue

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
            "context_overflow_compacted": used_overflow_compaction,
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
        *,
        suffix: str = "request",
    ) -> None:
        if self.request_dir is None:
            return
        self.request_dir.mkdir(parents=True, exist_ok=True)
        path = self.request_dir / f"{candidate.candidate_id}_{key}_{suffix}.json"
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
