#!/usr/bin/env python3
"""Generate revised explorer-aligned per-frame inputs without replacing v1."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

from ms_odd_tagging.tagger.rule_based.registry import (
    detect_recording_events,
    load_config,
)

from .frame_input import (
    DEFAULT_FRAMES_PER_SECOND,
    build_direct_derivation_context,
    build_frame_json,
    canonical_recording_id,
    sample_frames_by_rate,
    select_canonical_files,
)
from .model_input import ensure_dir, safe_name
from .revised_bev import render_revised_bev_png


DEFAULT_INPUT_DIR = Path("outputs/01_canonical")
DEFAULT_OUTPUT_DIR = Path("outputs/02_frame_inputs_revised")


def build_recording(
    canonical_path: Path,
    output_dir: Path,
    *,
    extent: tuple[float, float, float, float],
    size: tuple[int, int],
    max_objects: int,
    frames_per_second: float | None = DEFAULT_FRAMES_PER_SECOND,
    frame_limit: int | None = None,
) -> tuple[dict, int]:
    recording = json.loads(canonical_path.read_text(encoding="utf-8"))
    recording_id = recording["recording_id"]
    selected_frames = sample_frames_by_rate(recording.get("frames", []), frames_per_second)
    if frame_limit is not None:
        selected_frames = selected_frames[:frame_limit]

    recording_dir = output_dir / safe_name(recording_id)
    ensure_dir(recording_dir)
    config = load_config()
    events, quality = detect_recording_events(recording, config)
    from ms_odd_tagging.scenarios.following_lane.detector import run_following_lane

    lane_result = run_following_lane(recording)
    lane_frames = {
        item["frame_index"]: item for item in lane_result.get("frames", [])
    }
    (recording_dir / "recording_rule_events.json").write_text(
        json.dumps(
            {
                "schema_version": "rule-based-scenario-events-v1",
                "recording_id": recording_id,
                "interval_boundary_convention": "inclusive_samples",
                "rule_based_events": [event.to_dict() for event in events],
                "data_quality": quality,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    rows = []
    for frame in selected_frames:
        index = frame["frame_index"]
        frame_dir = recording_dir / f"frame_{index:06d}"
        ensure_dir(frame_dir)
        bev_path = frame_dir / "bev_revised.png"
        lane_frame = lane_frames.get(index)
        render_revised_bev_png(
            recording,
            frame,
            bev_path,
            extent,
            size,
            lane_context=lane_frame,
            proximity_radius_m=float(
                config["object_relations"]["generic_proximity_radius_m"]
            ),
        )
        payload = build_frame_json(
            recording,
            frame,
            canonical_path,
            bev_path.name,
            max_objects=max_objects,
        )
        derivation_context = build_direct_derivation_context(
            index,
            events,
            set(config["enabled_scenarios"]),
            lane_frame,
        )
        payload["bev"].update(
            {
                "renderer": "explorer-aligned-revised-v1",
                "orientation": "ego-heading-up",
                "annotations": [
                    "ego_speed_and_velocity",
                    "object_speed_and_velocity",
                    "latest_lane_and_lead_assignment",
                    "footprint_proximity_boundary",
                ],
                "footprint_proximity_radius_m": float(
                    config["object_relations"]["generic_proximity_radius_m"]
                ),
                "extent_m": {
                    "left": extent[0],
                    "right": extent[1],
                    "behind": extent[2],
                    "ahead": extent[3],
                },
            }
        )
        frame_path = frame_dir / "frame.json"
        frame_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (frame_dir / "gt_reference.json").write_text(
            json.dumps(derivation_context, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        rows.append(
            {
                "recording_id": recording_id,
                "frame_id": payload["frame_id"],
                "frame_index": index,
                "time_since_start_s": payload["time_since_start_s"],
                "frame_json": str(frame_path),
                "bev": str(bev_path),
                "relative_bev": bev_path.relative_to(output_dir).as_posix(),
            }
        )

    return {
        "recording_id": recording_id,
        "canonical_frame_count": len(recording.get("frames", [])),
        "generated_frame_count": len(rows),
        "frames_per_second": frames_per_second,
        "frames": rows,
    }, len(rows)


def write_review_html(output_dir: Path, rows: list[dict]) -> Path:
    cards = []
    for row in rows:
        cards.append(
            '<article class="frame-card">'
            f'<img src="{html.escape(row["relative_bev"])}" alt="Revised BEV for {html.escape(row["frame_id"])}">'
            f'<div><b>{html.escape(row["recording_id"])}</b><br>'
            f'frame {row["frame_index"]} · {row["time_since_start_s"]:.3f}s</div>'
            "</article>"
        )
    path = output_dir / "revised_bev_review.html"
    path.write_text(
        """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Revised per-frame BEV review</title><style>
body{font-family:Arial,sans-serif;margin:24px;background:#f8fafc;color:#0f172a}
h1{font-size:22px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:18px}
.frame-card{background:white;border:1px solid #cbd5e1;border-radius:8px;overflow:hidden}
.frame-card img{display:block;width:100%;height:auto}.frame-card div{padding:10px 12px;line-height:1.45}
</style></head><body><h1>Revised ego-heading-up BEVs</h1><main class="grid">
"""
        + "\n".join(cards)
        + "\n</main></body></html>\n",
        encoding="utf-8",
    )
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate revised explorer-aligned BEVs in a separate output tree.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--recording", action="append")
    parser.add_argument("--frame-limit", type=int)
    sampling = parser.add_mutually_exclusive_group()
    sampling.add_argument("--frames-per-second", type=float, default=DEFAULT_FRAMES_PER_SECOND)
    sampling.add_argument("--all-frames", action="store_true")
    parser.add_argument("--max-objects", type=int, default=80)
    parser.add_argument("--width", type=int, default=1000)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--left-m", type=float, default=45.0)
    parser.add_argument("--right-m", type=float, default=45.0)
    parser.add_argument("--back-m", type=float, default=25.0)
    parser.add_argument("--forward-m", type=float, default=95.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_dir(args.output_dir)
    requested = set(args.recording or [])
    files = [
        path for path in select_canonical_files(args.input_dir)
        if not requested or canonical_recording_id(path) in requested
    ]
    manifest = {
        "schema_version": "odld-revised-per-frame-input-manifest-v1",
        "renderer": "explorer-aligned-revised-v1",
        "orientation": "ego-heading-up",
        "frames_per_second": None if args.all_frames else args.frames_per_second,
        "recordings": [],
    }
    review_rows = []
    for path in files:
        summary, _ = build_recording(
            path,
            args.output_dir,
            extent=(args.left_m, args.right_m, args.back_m, args.forward_m),
            size=(args.width, args.height),
            max_objects=args.max_objects,
            frames_per_second=None if args.all_frames else args.frames_per_second,
            frame_limit=args.frame_limit,
        )
        manifest["recordings"].append(summary)
        review_rows.extend(summary["frames"])
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    review_path = write_review_html(args.output_dir, review_rows)
    print(f"Generated {len(review_rows)} revised BEV(s).")
    print(f"Review: {review_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
