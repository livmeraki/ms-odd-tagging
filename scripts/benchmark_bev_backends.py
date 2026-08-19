#!/usr/bin/env python3
"""A/B benchmark the historical and Pillow BEV raster backends.

This experiment does not modify ``outputs/02_frame_inputs``. It renders the same
sampled canonical frames through the same explorer-aligned geometry code while
swapping only the canvas rasterizer.
"""

from __future__ import annotations

import argparse
import html
import json
import time
from contextlib import contextmanager
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from ms_odd_tagging.common.config import CANONICAL, OUTPUT_ROOT
from ms_odd_tagging.frame_inputs import revised_bev
from ms_odd_tagging.frame_inputs.standard import (
    canonical_recording_id,
    sample_frames_by_rate,
    select_canonical_files,
)
from ms_odd_tagging.frame_inputs.model_input import PngCanvas, safe_name
from ms_odd_tagging.frame_inputs.pillow_canvas import PillowCanvas
from ms_odd_tagging.tagger.rule_based.registry import load_config


DEFAULT_OUTPUT = OUTPUT_ROOT / "experiments" / "bev_backend_compare"


@contextmanager
def canvas_backend(canvas_type):
    previous = revised_bev.PngCanvas
    revised_bev.PngCanvas = canvas_type
    try:
        yield
    finally:
        revised_bev.PngCanvas = previous


def compare_images(first: Path, second: Path) -> dict[str, float]:
    with Image.open(first).convert("RGB") as a, Image.open(second).convert("RGB") as b:
        if a.size != b.size:
            raise ValueError(f"image size mismatch: {a.size} vs {b.size}")
        diff = ImageChops.difference(a, b)
        stat = ImageStat.Stat(diff)
        mean_abs = sum(float(value) for value in stat.mean) / 3.0
        extrema = diff.getbbox()
        changed = 0
        if extrema is not None:
            changed = sum(1 for pixel in diff.getdata() if pixel != (0, 0, 0))
        total = a.width * a.height
        return {
            "mean_absolute_channel_difference": mean_abs,
            "changed_pixel_percent": (changed / total * 100.0) if total else 0.0,
        }


def render_backend(
    *,
    backend_name: str,
    canvas_type,
    recording: dict,
    frames: list[dict],
    output_dir: Path,
    extent: tuple[float, float, float, float],
    size: tuple[int, int],
    proximity_radius_m: float,
    crossing_arc: tuple[float, float, float],
    static_context,
) -> tuple[float, list[dict]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    start = time.perf_counter()
    with canvas_backend(canvas_type):
        for frame in frames:
            index = int(frame["frame_index"])
            output = output_dir / f"frame_{index:06d}.png"
            frame_start = time.perf_counter()
            revised_bev.render_revised_bev_png(
                recording,
                frame,
                output,
                extent,
                size,
                proximity_radius_m=proximity_radius_m,
                crossing_arc=crossing_arc,
                static_context=static_context,
            )
            rows.append(
                {
                    "frame_index": index,
                    "seconds": time.perf_counter() - frame_start,
                    "path": str(output),
                }
            )
    return time.perf_counter() - start, rows


def write_html(output_dir: Path, recording_id: str, rows: list[dict]) -> Path:
    cards = []
    for row in rows:
        baseline = Path(row["baseline_path"]).relative_to(output_dir).as_posix()
        pillow = Path(row["pillow_path"]).relative_to(output_dir).as_posix()
        cards.append(
            "<section class='row'>"
            f"<h2>Frame {row['frame_index']}</h2>"
            "<div class='images'>"
            f"<figure><figcaption>Baseline · {row['baseline_seconds']:.3f}s</figcaption><img src='{html.escape(baseline)}'></figure>"
            f"<figure><figcaption>Pillow · {row['pillow_seconds']:.3f}s</figcaption><img src='{html.escape(pillow)}'></figure>"
            "</div>"
            f"<p>Changed pixels: {row['changed_pixel_percent']:.3f}% · mean abs RGB diff: {row['mean_absolute_channel_difference']:.3f}</p>"
            "</section>"
        )
    path = output_dir / "comparison.html"
    path.write_text(
        "<!doctype html><html><head><meta charset='utf-8'><title>BEV backend comparison</title>"
        "<style>body{font-family:Arial,sans-serif;margin:24px;background:#f8fafc;color:#0f172a}"
        ".row{background:white;border:1px solid #cbd5e1;border-radius:10px;padding:16px;margin-bottom:18px}"
        ".images{display:grid;grid-template-columns:1fr 1fr;gap:16px}figure{margin:0}img{width:100%;height:auto;border:1px solid #e2e8f0}"
        "figcaption{font-weight:700;margin-bottom:8px}@media(max-width:800px){.images{grid-template-columns:1fr}}</style>"
        "</head><body>"
        f"<h1>BEV raster backend comparison · {html.escape(recording_id)}</h1>"
        + "".join(cards)
        + "</body></html>",
        encoding="utf-8",
    )
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", help="Recording ID to benchmark.")
    parser.add_argument("--input-dir", type=Path, default=CANONICAL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--frames-per-second", type=float, default=1.0)
    parser.add_argument("--frame-limit", type=int, default=10)
    parser.add_argument("--width", type=int, default=900)
    parser.add_argument("--height", type=int, default=1200)
    parser.add_argument("--left-m", type=float, default=45.0)
    parser.add_argument("--right-m", type=float, default=45.0)
    parser.add_argument("--back-m", type=float, default=25.0)
    parser.add_argument("--forward-m", type=float, default=95.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    matches = [
        path
        for path in select_canonical_files(args.input_dir)
        if canonical_recording_id(path) == args.recording
    ]
    if not matches:
        raise SystemExit(f"Canonical recording not found: {args.recording}")

    canonical_path = matches[0]
    recording = json.loads(canonical_path.read_text(encoding="utf-8"))
    frames = sample_frames_by_rate(recording.get("frames", []), args.frames_per_second)
    if args.frame_limit is not None:
        frames = frames[: max(0, args.frame_limit)]
    if not frames:
        raise SystemExit("No frames selected.")

    config = load_config()
    crossing = config["object_path_crossing_interactions"]
    crossing_arc = (
        float(crossing["arc_inner_radius_m"]),
        float(crossing["arc_outer_radius_m"]),
        float(crossing["arc_half_angle_deg"]),
    )
    proximity = float(config["object_relations"]["generic_proximity_radius_m"])
    extent = (args.left_m, args.right_m, args.back_m, args.forward_m)
    size = (args.width, args.height)
    static_context = revised_bev.build_bev_static_context(recording)

    recording_dir = args.output_dir / safe_name(args.recording)
    baseline_dir = recording_dir / "baseline"
    pillow_dir = recording_dir / "pillow"

    baseline_total, baseline_rows = render_backend(
        backend_name="baseline",
        canvas_type=PngCanvas,
        recording=recording,
        frames=frames,
        output_dir=baseline_dir,
        extent=extent,
        size=size,
        proximity_radius_m=proximity,
        crossing_arc=crossing_arc,
        static_context=static_context,
    )
    pillow_total, pillow_rows = render_backend(
        backend_name="pillow",
        canvas_type=PillowCanvas,
        recording=recording,
        frames=frames,
        output_dir=pillow_dir,
        extent=extent,
        size=size,
        proximity_radius_m=proximity,
        crossing_arc=crossing_arc,
        static_context=static_context,
    )

    rows = []
    for baseline, pillow in zip(baseline_rows, pillow_rows):
        comparison = compare_images(Path(baseline["path"]), Path(pillow["path"]))
        rows.append(
            {
                "frame_index": baseline["frame_index"],
                "baseline_seconds": baseline["seconds"],
                "pillow_seconds": pillow["seconds"],
                "baseline_path": baseline["path"],
                "pillow_path": pillow["path"],
                **comparison,
            }
        )

    speedup = baseline_total / pillow_total if pillow_total > 0 else None
    report = {
        "recording_id": args.recording,
        "canonical_file": str(canonical_path),
        "frame_count": len(frames),
        "size_px": list(size),
        "extent_m": list(extent),
        "baseline_total_seconds": baseline_total,
        "pillow_total_seconds": pillow_total,
        "speedup": speedup,
        "average_changed_pixel_percent": sum(row["changed_pixel_percent"] for row in rows) / len(rows),
        "average_mean_absolute_channel_difference": sum(row["mean_absolute_channel_difference"] for row in rows) / len(rows),
        "frames": rows,
    }
    recording_dir.mkdir(parents=True, exist_ok=True)
    report_path = recording_dir / "benchmark.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    html_path = write_html(recording_dir, args.recording, rows)

    print(f"Frames: {len(frames)}")
    print(f"Baseline: {baseline_total:.3f}s ({baseline_total / len(frames):.3f}s/frame)")
    print(f"Pillow:   {pillow_total:.3f}s ({pillow_total / len(frames):.3f}s/frame)")
    print(f"Speedup:  {speedup:.2f}x" if speedup is not None else "Speedup: n/a")
    print(f"Average changed pixels: {report['average_changed_pixel_percent']:.3f}%")
    print(f"Average mean abs RGB diff: {report['average_mean_absolute_channel_difference']:.3f}")
    print(f"Report: {report_path}")
    print(f"Visual comparison: {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
