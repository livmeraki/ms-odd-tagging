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
REQUIRED_RAW_FILES = (
    "annotations_OD.json",
    "annotations_LD.json",
    "traj_lcs.txt",
)


def format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remaining = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m {remaining:.1f}s"
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours)}h {int(minutes)}m {remaining:.1f}s"


def red(text: str) -> str:
    if sys.stdout.isatty() and not os.environ.get("NO_COLOR"):
        return f"\033[91m{text}\033[0m"
    return text


def run_command(module: str, arguments: list[str]) -> float:
    command = [sys.executable, "-m", module, *arguments]
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
    return time.monotonic() - start


def missing_required_files(source_root: Path, recording: str) -> list[str]:
    recording_root = source_root / recording
    return [
        name for name in REQUIRED_RAW_FILES if not (recording_root / name).is_file()
    ]


def average_success_elapsed(recordings: list[dict[str, object]]) -> float | None:
    values = [
        float(item["elapsed_seconds"])
        for item in recordings
        if item.get("status") == "succeeded"
    ]
    if not values:
        return None
    return sum(values) / len(values)


def average_pipeline_elapsed_per_recording(
    stage_timings: list[dict[str, object]],
) -> tuple[float | None, int]:
    per_recording: dict[str, float] = {}
    successful_sets: list[set[str]] = []

    for stage in stage_timings:
        stage_successes: set[str] = set()
        for item in stage.get("recordings", []):
            if item.get("status") != "succeeded":
                continue
            recording = str(item["recording"])
            stage_successes.add(recording)
            per_recording[recording] = per_recording.get(recording, 0.0) + float(
                item["elapsed_seconds"]
            )
        successful_sets.append(stage_successes)

    if not successful_sets:
        return None, 0

    fully_successful = set.intersection(*successful_sets)
    if not fully_successful:
        return None, 0

    values = [per_recording[recording] for recording in fully_successful]
    return sum(values) / len(values), len(values)


def write_runtime_report(
    output_root: Path,
    recordings: list[str],
    stage_timings: list[dict[str, object]],
    failures: list[dict[str, object]],
    total_elapsed: float,
) -> Path:
    runtime_dir = output_root / "runtime_logs"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    recorded_at = datetime.now().astimezone()
    report_path = runtime_dir / f"pipeline_{recorded_at.strftime('%Y%m%d_%H%M%S')}.json"
    average_pipeline_elapsed, average_recording_count = (
        average_pipeline_elapsed_per_recording(stage_timings)
    )
    payload = {
        "recorded_at": recorded_at.isoformat(timespec="seconds"),
        "recordings": recordings,
        "stages": stage_timings,
        "failures": failures,
        "total_elapsed_seconds": round(total_elapsed, 3),
        "average_pipeline_elapsed_seconds_per_successful_recording": (
            round(average_pipeline_elapsed, 3)
            if average_pipeline_elapsed is not None
            else None
        ),
        "average_pipeline_recording_count": average_recording_count,
    }
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report_path


def print_runtime_summary(
    stage_timings: list[dict[str, object]],
    failures: list[dict[str, object]],
    total_elapsed: float,
    report_path: Path,
) -> None:
    print("\n=== Runtime Summary ===", flush=True)
    for stage in stage_timings:
        elapsed = float(stage["elapsed_seconds"])
        succeeded = int(stage.get("succeeded", 0))
        failed = int(stage.get("failed", 0))
        average_elapsed = stage.get("average_elapsed_seconds_per_successful_recording")
        print(
            f"- Stage {stage['stage']}: {stage['name']} -> "
            f"{format_elapsed(elapsed)} ({succeeded} succeeded, {failed} failed)",
            flush=True,
        )
        if average_elapsed is not None:
            print(
                f"  Average per successful recording -> "
                f"{format_elapsed(float(average_elapsed))}",
                flush=True,
            )

    average_pipeline_elapsed, average_recording_count = (
        average_pipeline_elapsed_per_recording(stage_timings)
    )
    print(f"- Total pipeline -> {format_elapsed(total_elapsed)}", flush=True)
    if average_pipeline_elapsed is not None:
        print(
            f"- Average pipeline per successful recording -> "
            f"{format_elapsed(average_pipeline_elapsed)} "
            f"({average_recording_count} recordings)",
            flush=True,
        )
    print(f"- Runtime log -> {report_path}", flush=True)

    if failures:
        print(red("\n=== Failed Recordings ==="), flush=True)
        for failure in failures:
            recording = failure["recording"]
            stage = failure["stage"]
            reason = failure["reason"]
            print(red(f"- {recording} [{stage}] {reason}"), flush=True)


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
    failures: list[dict[str, object]] = []

    canonical_root = args.output_root / "01_canonical"
    frame_input_root = args.output_root / "02_frame_inputs"
    stage_total = 1 if args.stop_after == "canonical" else 2

    print(
        f"\n==> Stage 1/{stage_total}: canonicalization "
        f"({len(args.recordings)} recordings)",
        flush=True,
    )
    canonical_stage_start = time.monotonic()
    canonical_successes: list[str] = []
    canonical_per_recording: list[dict[str, object]] = []

    for index, recording in enumerate(args.recordings, start=1):
        print(f"\n[canonical {index}/{len(args.recordings)}] {recording}", flush=True)
        missing = missing_required_files(args.source_root, recording)
        if missing:
            reason = f"missing required file(s): {', '.join(missing)}"
            failures.append(
                {
                    "recording": recording,
                    "stage": "canonicalization",
                    "reason": reason,
                }
            )
            canonical_per_recording.append(
                {
                    "recording": recording,
                    "status": "failed",
                    "elapsed_seconds": 0.0,
                    "reason": reason,
                }
            )
            print(f"Skipping {recording}; {reason}", flush=True)
            continue

        canonical_args = [
            "--source-root", str(args.source_root),
            "--output-root", str(canonical_root),
            "--ld-radius-m", str(args.ld_radius_m),
            recording,
        ]
        try:
            elapsed = run_command("ms_odd_tagging.canonical.builder", canonical_args)
        except subprocess.CalledProcessError as exc:
            reason = f"process exited with code {exc.returncode}"
            failures.append(
                {
                    "recording": recording,
                    "stage": "canonicalization",
                    "reason": reason,
                }
            )
            canonical_per_recording.append(
                {
                    "recording": recording,
                    "status": "failed",
                    "elapsed_seconds": 0.0,
                    "reason": reason,
                }
            )
            print(f"Canonicalization failed for {recording}; continuing.", flush=True)
            continue

        canonical_successes.append(recording)
        canonical_per_recording.append(
            {
                "recording": recording,
                "status": "succeeded",
                "elapsed_seconds": round(elapsed, 3),
            }
        )
        print(f"Completed {recording} in {format_elapsed(elapsed)}", flush=True)

    canonical_stage_elapsed = time.monotonic() - canonical_stage_start
    canonical_average = average_success_elapsed(canonical_per_recording)
    stage_timings.append(
        {
            "stage": 1,
            "name": "canonicalization",
            "module": "ms_odd_tagging.canonical.builder",
            "elapsed_seconds": round(canonical_stage_elapsed, 3),
            "average_elapsed_seconds_per_successful_recording": (
                round(canonical_average, 3) if canonical_average is not None else None
            ),
            "succeeded": len(canonical_successes),
            "failed": len(args.recordings) - len(canonical_successes),
            "recordings": canonical_per_recording,
        }
    )
    print(
        f"<== Stage 1/{stage_total} complete in "
        f"{format_elapsed(canonical_stage_elapsed)}",
        flush=True,
    )

    if args.stop_after == "canonical":
        total_elapsed = time.monotonic() - pipeline_start
        report_path = write_runtime_report(
            args.output_root,
            args.recordings,
            stage_timings,
            failures,
            total_elapsed,
        )
        print_runtime_summary(stage_timings, failures, total_elapsed, report_path)
        return 1 if failures else 0

    print(
        f"\n==> Stage 2/{stage_total}: frame input / BEV generation "
        f"({len(canonical_successes)} recordings)",
        flush=True,
    )
    frame_stage_start = time.monotonic()
    frame_successes: list[str] = []
    frame_per_recording: list[dict[str, object]] = []

    for index, recording in enumerate(canonical_successes, start=1):
        print(
            f"\n[frame-input {index}/{len(canonical_successes)}] {recording}",
            flush=True,
        )
        model_args = [
            "--input-dir", str(canonical_root),
            "--output-dir", str(frame_input_root),
            "--existing-output", args.existing_output,
            "--recording", recording,
        ]
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

        try:
            elapsed = run_command("ms_odd_tagging.frame_inputs.builder", model_args)
        except subprocess.CalledProcessError as exc:
            reason = f"process exited with code {exc.returncode}"
            failures.append(
                {
                    "recording": recording,
                    "stage": "frame_input_bev_generation",
                    "reason": reason,
                }
            )
            frame_per_recording.append(
                {
                    "recording": recording,
                    "status": "failed",
                    "elapsed_seconds": 0.0,
                    "reason": reason,
                }
            )
            print(f"Frame input generation failed for {recording}; continuing.", flush=True)
            continue

        frame_successes.append(recording)
        frame_per_recording.append(
            {
                "recording": recording,
                "status": "succeeded",
                "elapsed_seconds": round(elapsed, 3),
            }
        )
        print(f"Completed {recording} in {format_elapsed(elapsed)}", flush=True)

    frame_stage_elapsed = time.monotonic() - frame_stage_start
    frame_average = average_success_elapsed(frame_per_recording)
    stage_timings.append(
        {
            "stage": 2,
            "name": "frame_input_bev_generation",
            "module": "ms_odd_tagging.frame_inputs.builder",
            "elapsed_seconds": round(frame_stage_elapsed, 3),
            "average_elapsed_seconds_per_successful_recording": (
                round(frame_average, 3) if frame_average is not None else None
            ),
            "succeeded": len(frame_successes),
            "failed": len(canonical_successes) - len(frame_successes),
            "recordings": frame_per_recording,
        }
    )
    print(
        f"<== Stage 2/{stage_total} complete in {format_elapsed(frame_stage_elapsed)}",
        flush=True,
    )

    total_elapsed = time.monotonic() - pipeline_start
    report_path = write_runtime_report(
        args.output_root,
        args.recordings,
        stage_timings,
        failures,
        total_elapsed,
    )
    print_runtime_summary(stage_timings, failures, total_elapsed, report_path)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
