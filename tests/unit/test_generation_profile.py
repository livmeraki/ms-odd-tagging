from __future__ import annotations

import csv
import json
from pathlib import Path

from ms_odd_tagging.input_generator.generation_profile import (
    GenerationProfiler,
    files_size,
    p95,
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def write_bytes(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def test_profile_metric_calculations_and_size_accounting(tmp_path: Path) -> None:
    clock = FakeClock()
    input_file = write_bytes(tmp_path / "input.json", 100)
    rule_file = write_bytes(tmp_path / "out" / "recording_rule_events.json", 10)
    first = write_bytes(tmp_path / "out" / "frame_000000" / "frame.json", 30)
    first_bev = write_bytes(tmp_path / "out" / "frame_000000" / "bev.png", 20)
    second = write_bytes(tmp_path / "out" / "frame_000010" / "frame.json", 40)

    profiler = GenerationProfiler(tmp_path / "out", clock=clock)
    profiler.start_recording("rec", [input_file])
    profiler.add_output_files([rule_file])
    start = profiler.sample_start()
    clock.advance(0.25)
    profiler.record_sample(0, start, [first, first_bev])
    start = profiler.sample_start()
    clock.advance(0.75)
    profiler.record_sample(10, start, [second])
    profiler.finish_recording()

    assert files_size([input_file, first, second]) == 170
    assert profiler.rows[0]["processing_fps"] == 4.0
    assert profiler.rows[0]["cumulative_output_size_bytes"] == 60
    assert profiler.rows[0]["output_size_bytes"] == 50
    assert profiler.rows[1]["processing_fps"] == 2.0
    assert profiler.rows[1]["cumulative_output_size_bytes"] == 100
    assert profiler.rows[1]["output_size_increase_bytes"] == 0
    assert profiler.summary()["storage_expansion_ratio"] == 1.0
    assert profiler.summary()["frame_generation_time_s"]["average"] == 0.5


def test_p95_uses_nearest_rank() -> None:
    assert p95([0.1, 0.2, 0.3, 0.4]) == 0.4


def test_profile_output_files_are_created(tmp_path: Path) -> None:
    clock = FakeClock()
    input_file = write_bytes(tmp_path / "input.json", 100)
    output_file = write_bytes(tmp_path / "out" / "frame_000000" / "frame.json", 25)
    profiler = GenerationProfiler(tmp_path / "out", clock=clock)
    profiler.start_recording("rec", [input_file])
    start = profiler.sample_start()
    clock.advance(0.5)
    profiler.record_sample(0, start, [output_file])

    paths = profiler.save()

    for path in paths.values():
        assert path.is_file()
    assert paths["generation_time_graph"].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    with paths["metrics_csv"].open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["recording_id"] == "rec"
    summary = json.loads(paths["summary_json"].read_text(encoding="utf-8"))
    assert summary["total_processed_frames"] == 1
