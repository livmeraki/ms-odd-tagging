"""Small terminal progress helper for deterministic generation stages."""

from __future__ import annotations

import threading
import time


class ProgressReporter:
    """Print coarse percentage progress without adding external dependencies.

    Long single-item stages can otherwise appear frozen at ``0/N`` until the
    current item completes. A lightweight daemon heartbeat keeps the terminal
    visibly alive and reports elapsed time while preserving the real completed
    count and percentage.
    """

    def __init__(
        self,
        label: str,
        total: int,
        unit: str,
        *,
        min_interval_s: float = 0.5,
        steps: int = 20,
        heartbeat_interval_s: float = 10.0,
        bar_width: int = 20,
    ) -> None:
        self.label = label
        self.total = max(0, int(total))
        self.unit = unit
        self.min_interval_s = min_interval_s
        self.step = max(1, self.total // max(1, steps)) if self.total else 1
        self.heartbeat_interval_s = max(0.0, float(heartbeat_interval_s))
        self.bar_width = max(8, int(bar_width))
        self.completed = 0
        self._last_printed = -1
        self._last_time = 0.0
        self._started_at = 0.0
        self._last_detail: str | None = None
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

    def start(self) -> None:
        if self.total == 0:
            print(f"[{self.label}] no {self.unit}s to process", flush=True)
            return
        self._started_at = time.monotonic()
        self._last_detail = "starting"
        self._print(0, "starting", force=True)
        if self.heartbeat_interval_s > 0:
            self._heartbeat_stop.clear()
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop,
                name=f"progress-{self.label}",
                daemon=True,
            )
            self._heartbeat_thread.start()

    def advance(self, detail: str | None = None, count: int = 1) -> None:
        self.update(self.completed + count, detail)

    def update(
        self,
        completed: int,
        detail: str | None = None,
        *,
        force: bool = False,
    ) -> None:
        self.completed = min(max(0, int(completed)), self.total)
        if detail is not None:
            self._last_detail = detail
        if self.total == 0:
            return
        now = time.monotonic()
        should_print = (
            force
            or self.completed == self.total
            or self.completed == 0
            or self.completed - self._last_printed >= self.step
            or now - self._last_time >= self.min_interval_s
        )
        if should_print:
            self._print(self.completed, detail, force=True)
        if self.completed >= self.total:
            self._heartbeat_stop.set()

    def finish(self, detail: str | None = None) -> None:
        self.update(self.total, detail or "done", force=True)
        self._heartbeat_stop.set()

    def _heartbeat_loop(self) -> None:
        while not self._heartbeat_stop.wait(self.heartbeat_interval_s):
            if self.total == 0 or self.completed >= self.total:
                return
            elapsed = time.monotonic() - self._started_at
            detail = self._last_detail or "working"
            self._print(
                self.completed,
                f"{detail}; working {elapsed:.1f}s",
                force=True,
                heartbeat=True,
            )

    def _bar(self, completed: int, *, heartbeat: bool = False) -> str:
        if not self.total:
            return "[" + "=" * self.bar_width + "]"
        filled = int(self.bar_width * completed / self.total)
        if heartbeat and completed < self.total:
            # Indeterminate marker: it shows activity without pretending that
            # an unfinished recording has measurable percentage completion.
            span = max(1, self.bar_width - 1)
            tick = int((time.monotonic() - self._started_at) / max(0.5, self.heartbeat_interval_s))
            position = tick % span
            chars = ["."] * self.bar_width
            chars[position] = ">"
            return "[" + "".join(chars) + "]"
        return "[" + "=" * filled + "." * (self.bar_width - filled) + "]"

    def _print(
        self,
        completed: int,
        detail: str | None,
        *,
        force: bool,
        heartbeat: bool = False,
    ) -> None:
        if not force:
            return
        percent = (completed / self.total * 100.0) if self.total else 100.0
        suffix = f" - {detail}" if detail else ""
        print(
            f"[{self.label}] {self._bar(completed, heartbeat=heartbeat)} "
            f"{completed}/{self.total} {self.unit}s ({percent:5.1f}%){suffix}",
            flush=True,
        )
        self._last_printed = completed
        self._last_time = time.monotonic()
