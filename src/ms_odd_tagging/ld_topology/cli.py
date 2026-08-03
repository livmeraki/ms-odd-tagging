"""Run fresh LD topology detection over canonical ODLD recordings."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ms_odd_tagging.common.config import CANONICAL

from .config import load_config
from .pipeline import classify_recording, write_frame_csv
from .visualization import render_debug_image


def _frame_indices(values: list[str]) -> set[int] | None:
    if not values:
        return None
    output: set[int] = set()
    for value in values:
        if ":" in value:
            start, stop = value.split(":", 1)
            output.update(range(int(start), int(stop)))
        else:
            output.add(int(value))
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recordings", nargs="*", help="Recording IDs; omit for all canonical ODLD inputs")
    parser.add_argument("--canonical-dir", type=Path, default=CANONICAL)
    parser.add_argument("--output-root", type=Path, default=Path("outputs/ld_topology"))
    parser.add_argument("--config", type=Path, default=Path("configs/ld_topology.json"))
    parser.add_argument("--frame", action="append", default=[], metavar="INDEX_OR_START:STOP")
    parser.add_argument("--debug-images", action="store_true")
    args = parser.parse_args(argv)

    config = load_config(args.config if args.config.is_file() else None)
    if args.recordings:
        inputs = [args.canonical_dir / f"{name}_canonical_odld_frames.json" for name in args.recordings]
    else:
        inputs = sorted(args.canonical_dir.glob("*_canonical_odld_frames.json"))
    if not inputs:
        parser.error(f"no canonical ODLD recordings found in {args.canonical_dir}")

    selected = _frame_indices(args.frame)
    for source in inputs:
        if not source.is_file():
            parser.error(f"missing canonical recording: {source}")
        recording = json.loads(source.read_text(encoding="utf-8"))
        if selected is not None:
            recording = {**recording, "frames": [f for f in recording.get("frames", []) if f.get("frame_index") in selected]}
        result = classify_recording(recording, config)
        recording_id = str(result.get("recording_id") or source.stem.replace("_canonical_odld_frames", ""))
        result_path = args.output_root / "results" / f"{recording_id}_ld_topology.json"
        csv_path = args.output_root / "csv" / f"{recording_id}_ld_topology_frames.csv"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
        write_frame_csv(result, csv_path)
        print(f"Wrote {result_path}")
        print(f"Wrote {csv_path}")
        if args.debug_images:
            scene_path = args.output_root / "debug_images" / f"{recording_id}_scene.png"
            render_debug_image(result, None, scene_path)
            print(f"Wrote {scene_path}")
            frames = recording.get("frames", [])
            for frame in frames[: min(20, len(frames))]:
                frame_path = args.output_root / "debug_images" / f"{recording_id}_frame_{int(frame.get('frame_index')):06d}.png"
                render_debug_image(result, frame, frame_path)
            if frames:
                print(f"Wrote frame debug images under {args.output_root / 'debug_images'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
