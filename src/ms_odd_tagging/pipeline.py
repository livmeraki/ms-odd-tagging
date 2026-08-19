"""Run the deterministic input-generation stages in order."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from ms_odd_tagging.common.config import DATA_RAW, OUTPUT_ROOT


SRC_ROOT = Path(__file__).resolve().parents[1]


def format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remaining = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m {remaining:.1f}s"
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours)}h {int(minutes)}m {remaining:.1f}s"


def run_stage(index: int, total: int, module: str, arguments: list[str]) -> float:
    command = [sys.executable, "-m", module, *arguments]
    print(f"\n==> Stage {index}/{total}: {module}", flush=True)
    print(f"    {' '.join(command)}", flush=True)
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(SRC_ROOT)
        if not existing_pythonpath
        else f"{SRC_ROOT}{os.pathsep}{existing_pythonpath}"
    )
    start = time.monotonic()
    subprocess.run(command, check=True, env=env)
    elapsed = time.monotonic() - start
    print(
        f"<== Stage {index}/{total} complete in {format_elapsed(elapsed)}",
        flush=True,
    )
    return elapsed


def write_runtime_report(
    output_root: Path,
    recordings: list[str],
    stage_timings: list[dict[str, object]],
    total_elapsed: float,
) -> Path:
    runtime_dir = output_root / "runtime_logs"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone()
    report_path = runtime_dir / f"pipeline_{timestamp.strftime('%Y%m%d_%H%M%S')}.json"
    payload = {
        "started_at": timestamp.isoformat(timespec="seconds"),
        "recordings": recordings,
        "stages": stage_timings,
        "total_elapsed_seconds": round(total_elapsed, 3),
    }
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report_path


def print_runtime_summary(
    stage_timings: list[dict[str, object]], total_elapsed: float, report_path: Path
) -> None:
    print("\n=== Runtime Summary ===", flush=True)
    for stage in stage_timings:
        elapsed = float(stage["elapsed_seconds"])
        print(
            f"- Stage {stage['stage']}: {stage['name']} -> {format_elapsed(elapsed)}",
            flush=True,
        )
    print(f"- Total pipeline -> {format_elapsed(total_elapsed)}", flush=True)
    print(f"- Runtime log -> {report_path}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run canonicalization -> explorer-aligned per-frame inputs and BEVs."
    )
    parser.add_argument("recordings", nargs="+", help="Recording IDs to process.")
    parser.add_argument("--source-root", type=Path, default=DATA_RAW)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--ld-radius-m", type=float, default=100.0)
    parser.add_argument("--frame-limit", type=int, default=None)
    sampling = parser.add_mutually_exclusive_group()
    sampling.add_argument(
        "--frames-per-second",
        type=float,
        default=1.0,
        help="BEV/model-input sampling rate (default: 1.0).",
    )
    sampling.add_argument(
        "--all-frames",
        action="store_true",
        help="Generate a BEV and model input for every canonical frame.",
    )
    parser.add_argument(
        "--existing-output",
        choices=("ask", "resume", "regenerate", "cancel"),
        default="ask",
        help=(
            "What to do if 02_frame_inputs already contains frame outputs. "
            "Default ask prompts; batch jobs should choose explicitly."
        ),
    )
    parser.add_argument(
        "--refresh-analysis",
        action="store_true",
        help="Ignore cached recording-wide rule/lane analysis and recompute it.",
    )
    parser.add_argument(
        "--stop-after", choices=("canonical", "frame-inputs"), default="frame-inputs"
    )
    parser.add_argument(
        "--profile-generation",
        action="store_true",
        help="Write optional frame-generation profiling artifacts.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pipeline_start = time.monotonic()
    stage_timings: list[dict[str, object]] = []

    canonical_root = args.output_root / "01_canonical"
    frame_input_root = args.output_root / "02_frame_inputs"
    canonical_args = [
        "--source-root", str(args.source_root),
        "--output-root", str(canonical_root),
        "--ld-radius-m", str(args.ld_radius_m),
    ]
    canonical_args.extend(args.recordings)
    stage_total = 1 if args.stop_after == "canonical" else 2

    canonical_elapsed = run_stage(
        1,
        stage_total,
        "ms_odd_tagging.canonical.builder",
        canonical_args,
    )
    stage_timings.append(
        {
            "stage": 1,
            "name": "canonicalization",
            "module": "ms_odd_tagging.canonical.builder",
            "elapsed_seconds": round(canonical_elapsed, 3),
        }
    )

    if args.stop_after == "canonical":
        total_elapsed = time.monotonic() - pipeline_start
        report_path = write_runtime_report(
            args.output_root, args.recordings, stage_timings, total_elapsed
        )
        print_runtime_summary(stage_timings, total_elapsed, report_path)
        return 0

    model_args = [
        "--input-dir", str(canonical_root),
        "--output-dir", str(frame_input_root),
        "--existing-output", args.existing_output,
    ]
    for recording in args.recordings:
        model_args.extend(["--recording", recording])
    if args.frame_limit is not None:
        model_args.extend(["--frame-limit", str(args.frame_limit)])
    if args.all_frames:
        model_args.append("--all-frames")
    else:
        model_args.extend(["--frames-per-second", str(args.frames_per_second)])
    if args.refresh_analysis:
        model_args.append("--refresh-analysis")
    if args.profile_generation:
        model_args.append("--profile-generation")

    frame_input_elapsed = run_stage(
        2,
        stage_total,
        "ms_odd_tagging.frame_inputs.builder",
        model_args,
    )
    stage_timings.append(
        {
            "stage": 2,
            "name": "frame_input_bev_generation",
            "module": "ms_odd_tagging.frame_inputs.builder",
            "elapsed_seconds": round(frame_input_elapsed, 3),
        }
    )

    total_elapsed = time.monotonic() - pipeline_start
    report_path = write_runtime_report(
        args.output_root, args.recordings, stage_timings, total_elapsed
    )
    print_runtime_summary(stage_timings, total_elapsed, report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
