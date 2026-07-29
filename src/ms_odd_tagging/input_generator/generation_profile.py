"""Optional generation-time and storage profiling for frame input generation."""

from __future__ import annotations

import csv
import json
import math
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Any

Clock = Callable[[], float]


def finalize_profile(profiler: "GenerationProfiler | None") -> None:
    if profiler is None:
        return
    try:
        paths = profiler.save()
        print(profiler.terminal_summary())
        print(f"Profiling artifacts: {paths['summary_json'].parent}")
    except Exception as exc:  # pragma: no cover - defensive by design.
        print(f"Warning: generation profiling failed and was skipped: {exc}")


def file_size(path: Path) -> int:
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def files_size(paths: Iterable[Path]) -> int:
    return sum(file_size(path) for path in paths)


def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def mb(value: int | float) -> float:
    return float(value) / (1024.0 * 1024.0)


def pct(numerator: int | float, denominator: int | float) -> float | None:
    return (float(numerator) / float(denominator) * 100.0) if denominator else None


@dataclass
class RecordingProfile:
    recording_id: str
    input_size_bytes: int
    start_time_s: float
    output_size_bytes: int = 0
    processed_frames: int = 0


@dataclass
class GenerationProfiler:
    output_dir: Path
    clock: Clock = time.perf_counter
    rows: list[dict[str, Any]] = field(default_factory=list)
    recordings: list[dict[str, Any]] = field(default_factory=list)
    start_time_s: float = field(init=False)
    current: RecordingProfile | None = None

    def __post_init__(self) -> None:
        self.start_time_s = self.clock()

    def start_recording(self, recording_id: str, input_paths: Iterable[Path]) -> None:
        self.current = RecordingProfile(
            recording_id=recording_id,
            input_size_bytes=files_size(input_paths),
            start_time_s=self.clock(),
        )

    def add_output_files(self, paths: Iterable[Path]) -> None:
        if self.current is None:
            return
        self.current.output_size_bytes += files_size(paths)

    def sample_start(self) -> float:
        return self.clock()

    def record_sample(self, frame_index: int, sample_start_s: float, output_paths: Iterable[Path]) -> None:
        if self.current is None:
            return
        now = self.clock()
        output_size = files_size(output_paths)
        self.current.output_size_bytes += output_size
        self.current.processed_frames += 1
        elapsed = max(now - self.current.start_time_s, 0.0)
        frame_time = max(now - sample_start_s, 0.0)
        processing_fps = self.current.processed_frames / elapsed if elapsed > 0 else 0.0
        increase = self.current.output_size_bytes - self.current.input_size_bytes
        self.rows.append(
            {
                "recording_id": self.current.recording_id,
                "sample_index": self.current.processed_frames - 1,
                "frame_index": frame_index,
                "elapsed_generation_time_s": elapsed,
                "frame_generation_time_s": frame_time,
                "processing_fps": processing_fps,
                "cumulative_output_size_bytes": self.current.output_size_bytes,
                "cumulative_output_size_mb": mb(self.current.output_size_bytes),
                "input_size_bytes": self.current.input_size_bytes,
                "input_size_mb": mb(self.current.input_size_bytes),
                "output_size_bytes": output_size,
                "output_size_mb": mb(output_size),
                "output_size_increase_bytes": increase,
                "output_size_increase_mb": mb(increase),
                "output_size_increase_percent": pct(increase, self.current.input_size_bytes),
            }
        )

    def finish_recording(self) -> None:
        if self.current is None:
            return
        elapsed = max(self.clock() - self.current.start_time_s, 0.0)
        self.recordings.append(
            {
                "recording_id": self.current.recording_id,
                "input_size_bytes": self.current.input_size_bytes,
                "generated_output_size_bytes": self.current.output_size_bytes,
                "processed_frames": self.current.processed_frames,
                "elapsed_time_s": elapsed,
                "processing_fps": self.current.processed_frames / elapsed if elapsed > 0 else 0.0,
                "storage_expansion_ratio": (
                    self.current.output_size_bytes / self.current.input_size_bytes
                    if self.current.input_size_bytes
                    else None
                ),
            }
        )
        self.current = None

    def summary(self) -> dict[str, Any]:
        frame_times = [float(row["frame_generation_time_s"]) for row in self.rows]
        total_execution_time = max(self.clock() - self.start_time_s, 0.0)
        total_processed = len(self.rows)
        total_input = sum(int(item["input_size_bytes"]) for item in self.recordings)
        total_output = sum(int(item["generated_output_size_bytes"]) for item in self.recordings)
        return {
            "schema_version": "generation-profile-summary-v1",
            "total_execution_time_s": total_execution_time,
            "total_processed_frames": total_processed,
            "frame_generation_time_s": {
                "average": statistics.fmean(frame_times) if frame_times else 0.0,
                "median": statistics.median(frame_times) if frame_times else 0.0,
                "minimum": min(frame_times) if frame_times else 0.0,
                "maximum": max(frame_times) if frame_times else 0.0,
                "p95": p95(frame_times),
            },
            "average_processing_fps": total_processed / total_execution_time if total_execution_time > 0 else 0.0,
            "total_input_size_bytes": total_input,
            "total_input_size_mb": mb(total_input),
            "total_generated_output_size_bytes": total_output,
            "total_generated_output_size_mb": mb(total_output),
            "storage_expansion_ratio": total_output / total_input if total_input else None,
            "recordings": self.recordings,
        }

    def save(self) -> dict[str, Path]:
        self.finish_recording()
        profiling_dir = self.output_dir / "profiling"
        profiling_dir.mkdir(parents=True, exist_ok=True)
        csv_path = profiling_dir / "generation_metrics.csv"
        summary_path = profiling_dir / "generation_summary.json"
        graph_time = profiling_dir / "generation_time_graph.png"
        graph_fps = profiling_dir / "processing_fps_graph.png"
        graph_size = profiling_dir / "cumulative_output_size_graph.png"
        self._write_csv(csv_path)
        summary = self.summary()
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        self._write_graph(graph_time, "Generation time per frame/sample", "frame_generation_time_s")
        self._write_graph(graph_fps, "Processing FPS over generation", "processing_fps")
        self._write_graph(graph_size, "Cumulative output size (MB)", "cumulative_output_size_mb")
        return {
            "metrics_csv": csv_path,
            "summary_json": summary_path,
            "generation_time_graph": graph_time,
            "processing_fps_graph": graph_fps,
            "cumulative_output_size_graph": graph_size,
        }

    def terminal_summary(self) -> str:
        summary = self.summary()
        frame_times = summary["frame_generation_time_s"]
        ratio = summary["storage_expansion_ratio"]
        ratio_text = f"{ratio:.2f}x" if isinstance(ratio, (int, float)) else "n/a"
        return (
            "Generation profile: "
            f"{summary['total_processed_frames']} frames, "
            f"{summary['total_execution_time_s']:.3f}s total, "
            f"avg frame {frame_times['average']:.4f}s, "
            f"p95 {frame_times['p95']:.4f}s, "
            f"avg {summary['average_processing_fps']:.2f} FPS, "
            f"output {summary['total_generated_output_size_mb']:.2f} MB, "
            f"expansion {ratio_text}"
        )

    def _write_csv(self, path: Path) -> None:
        fields = [
            "recording_id",
            "sample_index",
            "frame_index",
            "elapsed_generation_time_s",
            "frame_generation_time_s",
            "processing_fps",
            "cumulative_output_size_bytes",
            "cumulative_output_size_mb",
            "input_size_bytes",
            "input_size_mb",
            "output_size_bytes",
            "output_size_mb",
            "output_size_increase_bytes",
            "output_size_increase_mb",
            "output_size_increase_percent",
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in self.rows:
                writer.writerow(row)

    def _write_graph(self, path: Path, title: str, field: str) -> None:
        from PIL import Image, ImageDraw

        width, height = 900, 420
        margin_left, margin_top, margin_right, margin_bottom = 64, 42, 24, 54
        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)
        plot_left, plot_top = margin_left, margin_top
        plot_right, plot_bottom = width - margin_right, height - margin_bottom
        draw.rectangle((plot_left, plot_top, plot_right, plot_bottom), outline=(203, 213, 225))
        draw.text((margin_left, 14), title, fill=(15, 23, 42))
        values = [float(row[field]) for row in self.rows]
        if not values:
            draw.text((plot_left + 12, plot_top + 12), "no samples", fill=(100, 116, 139))
            image.save(path)
            return
        minimum, maximum = min(values), max(values)
        if math.isclose(minimum, maximum):
            minimum = 0.0 if maximum >= 0 else minimum - 1.0
            maximum = maximum + 1.0
        x_span = max(len(values) - 1, 1)
        y_span = maximum - minimum

        def point(index: int, value: float) -> tuple[float, float]:
            x = plot_left + (plot_right - plot_left) * index / x_span
            y = plot_bottom - (plot_bottom - plot_top) * (value - minimum) / y_span
            return x, y

        points = [point(index, value) for index, value in enumerate(values)]
        if len(points) == 1:
            x, y = points[0]
            draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=(37, 99, 235))
        else:
            draw.line(points, fill=(37, 99, 235), width=3)
        draw.text((plot_left, plot_bottom + 18), "frame/sample index", fill=(71, 85, 105))
        draw.text((plot_left, plot_top - 18), f"min {minimum:.4g}  max {maximum:.4g}", fill=(71, 85, 105))
        image.save(path)
