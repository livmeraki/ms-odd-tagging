"""Run the deterministic input-generation stages in order."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[1]


def run_stage(module: str, arguments: list[str]) -> None:
    command = [sys.executable, "-m", module, *arguments]
    print(f"\n==> {' '.join(command)}", flush=True)
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(SRC_ROOT)
        if not existing_pythonpath
        else f"{SRC_ROOT}{os.pathsep}{existing_pythonpath}"
    )
    subprocess.run(command, check=True, env=env)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run stages 01 canonical -> 02 windows -> 03 model inputs."
    )
    parser.add_argument("recordings", nargs="+", help="Recording IDs to process.")
    parser.add_argument("--source-root", type=Path, default=Path("data/01_raw"))
    parser.add_argument("--output-root", type=Path, default=Path("outputs"))
    parser.add_argument("--odld", action="store_true", help="Use OD+LD canonicalization.")
    parser.add_argument("--ld-radius-m", type=float, default=100.0)
    parser.add_argument("--window-limit", type=int, default=None)
    parser.add_argument(
        "--stop-after", choices=("canonical", "windows", "model-inputs"), default="model-inputs"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    canonical_root = args.output_root / "01_canonical"
    window_root = args.output_root / "02_windows"
    model_input_root = args.output_root / "03_model_inputs"
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
    run_stage(canonical_module, canonical_args)
    if args.stop_after == "canonical":
        return 0

    run_stage(
        "ms_odd_tagging.input_generator.windows",
        ["--canonical-dir", str(canonical_root), "--output-dir", str(window_root)],
    )
    if args.stop_after == "windows":
        return 0

    model_args = ["--input-dir", str(window_root), "--output-dir", str(model_input_root)]
    for recording in args.recordings:
        model_args.extend(["--recording", recording])
    if args.window_limit is not None:
        model_args.extend(["--window-limit", str(args.window_limit)])
    run_stage("ms_odd_tagging.input_generator.model_input", model_args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
