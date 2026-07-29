"""Run the deterministic input-generation stages in order."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from ms_odd_tagging.common.config import DATA_RAW, OUTPUT_ROOT


SRC_ROOT = Path(__file__).resolve().parents[1]


def run_stage(index: int, total: int, module: str, arguments: list[str]) -> None:
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
    print(f"<== Stage {index}/{total} complete in {elapsed:.1f}s", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run 01 canonical -> 02 timestamp-sampled frame inputs and BEVs."
    )
    parser.add_argument("recordings", nargs="+", help="Recording IDs to process.")
    parser.add_argument("--source-root", type=Path, default=DATA_RAW)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--odld", action="store_true", help="Use OD+LD canonicalization.")
    parser.add_argument("--ld-radius-m", type=float, default=100.0)
    parser.add_argument("--frame-limit", type=int, default=None)
    sampling = parser.add_mutually_exclusive_group()
    sampling.add_argument(
        "--frames-per-second", type=float, default=1.0,
        help="BEV/model-input sampling rate (default: 1.0).",
    )
    sampling.add_argument(
        "--all-frames", action="store_true",
        help="Generate a BEV and model input for every canonical frame.",
    )
    parser.add_argument(
        "--stop-after", choices=("canonical", "frame-inputs"), default="frame-inputs"
    )
    parser.add_argument(
        "--profile-generation",
        action="store_true",
        help="Write optional frame-generation profiling artifacts under output-root/02_frame_inputs/profiling.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    canonical_root = args.output_root / "01_canonical"
    frame_input_root = args.output_root / "02_frame_inputs"
    canonical_module = (
        "ms_odd_tagging.input_generator.canonical_odld"
        if args.odld
        else "ms_odd_tagging.input_generator.canonical"
    )
    canonical_args = [
        "--source-root", str(args.source_root),
        "--output-root", str(canonical_root),
    ]
    if args.odld:
        canonical_args.extend(["--ld-radius-m", str(args.ld_radius_m)])
    canonical_args.extend(args.recordings)
    stage_total = 1 if args.stop_after == "canonical" else 2
    run_stage(1, stage_total, canonical_module, canonical_args)
    if args.stop_after == "canonical":
        return 0

    model_args = ["--input-dir", str(canonical_root), "--output-dir", str(frame_input_root)]
    for recording in args.recordings:
        model_args.extend(["--recording", recording])
    if args.frame_limit is not None:
        model_args.extend(["--frame-limit", str(args.frame_limit)])
    if args.all_frames:
        model_args.append("--all-frames")
    else:
        model_args.extend(["--frames-per-second", str(args.frames_per_second)])
    if args.profile_generation:
        model_args.append("--profile-generation")
    run_stage(2, stage_total, "ms_odd_tagging.input_generator.frame_input", model_args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
