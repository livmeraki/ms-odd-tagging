"""Lightweight wall-clock profiling for the Qwen VLM POC pipeline."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


@dataclass
class TimingSample:
    stage: str
    elapsed_s: float
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "elapsed_s": round(self.elapsed_s, 6),
            **self.context,
        }


class RunProfiler:
    """Collect detailed and aggregate wall-clock timings with minimal overhead."""

    def __init__(self) -> None:
        self.started_at_utc = datetime.now(timezone.utc).isoformat()
        self._started = time.perf_counter()
        self.samples: list[TimingSample] = []

    @contextmanager
    def measure(self, stage: str, **context: Any) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.record(stage, time.perf_counter() - started, **context)

    def record(self, stage: str, elapsed_s: float, **context: Any) -> None:
        self.samples.append(TimingSample(stage=stage, elapsed_s=float(elapsed_s), context=dict(context)))

    def summary(self) -> dict[str, dict[str, float | int]]:
        grouped: dict[str, list[float]] = {}
        for sample in self.samples:
            grouped.setdefault(sample.stage, []).append(sample.elapsed_s)
        return {
            stage: {
                "count": len(values),
                "total_s": round(sum(values), 6),
                "avg_s": round(sum(values) / len(values), 6),
                "min_s": round(min(values), 6),
                "max_s": round(max(values), 6),
            }
            for stage, values in sorted(grouped.items())
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "qwen-vlm-poc-timing-v1",
            "started_at_utc": self.started_at_utc,
            "total_elapsed_s": round(time.perf_counter() - self._started, 6),
            "summary": self.summary(),
            "samples": [sample.to_dict() for sample in self.samples],
        }

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        return path

    def console_lines(self) -> list[str]:
        lines = ["Timing summary:"]
        for stage, values in self.summary().items():
            lines.append(
                f"  {stage}: total={values['total_s']:.3f}s "
                f"avg={values['avg_s']:.3f}s count={values['count']} max={values['max_s']:.3f}s"
            )
        return lines
