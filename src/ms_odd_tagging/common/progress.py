"""Small terminal progress helper for deterministic generation stages."""

from __future__ import annotations

import time


class ProgressReporter:
    """Print progress only when completed work actually advances."""

    def __init__(
        self,
        label: str,
        total: int,
        unit: str,
        *,
        min_interval_s: float = 0.5,
        steps: int = 20,
        bar_width: int = 20,
    ) -> None:
        self.label = label
        self.total = max(0, int(total))
        self.unit = unit
        self.min_interval_s = min_interval_s
        self.step = max(1, self.total // max(1, steps)) if self.total else 1
        self.bar_width = max(8, int(bar_width))
        self.completed = 0
        self._last_printed = -1
        self._last_time = 0.0

    def start(self) -> None:
        if self.total == 0:
            print(f"[{self.label}] no {self.unit}s to process", flush=True)
            return
        self._print(0, "starting", force=True)

    def advance(self, detail: str | None = None, count: int = 1) -> None:
        self.update(self.completed + count, detail)

    def update(
        self,
        completed: int,
        detail: str | None = None,
        *,
        force: bool = False,
    ) -> None:
        previous = self.completed
        self.completed = min(max(0, int(completed)), self.total)
        if self.total == 0:
            return
        if self.completed <= previous and not force:
            return
        now = time.monotonic()
        should_print = (
            force
            or self.completed == self.total
            or self.completed - self._last_printed >= self.step
            or now - self._last_time >= self.min_interval_s
        )
        if should_print:
            self._print(self.completed, detail, force=True)

    def finish(self, detail: str | None = None) -> None:
        self.update(self.total, detail or "done", force=True)

    def _bar(self, completed: int) -> str:
        if not self.total:
            return "[" + "=" * self.bar_width + "]"
        filled = int(self.bar_width * completed / self.total)
        return "[" + "=" * filled + "." * (self.bar_width - filled) + "]"

    def _print(self, completed: int, detail: str | None, *, force: bool) -> None:
        if not force:
            return
        percent = (completed / self.total * 100.0) if self.total else 100.0
        suffix = f" - {detail}" if detail else ""
        print(
            f"[{self.label}] {self._bar(completed)} "
            f"{completed}/{self.total} {self.unit}s ({percent:5.1f}%){suffix}",
            flush=True,
        )
        self._last_printed = completed
        self._last_time = time.monotonic()
