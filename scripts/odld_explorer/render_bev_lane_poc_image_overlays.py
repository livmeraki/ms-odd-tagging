#!/usr/bin/env python3
"""Overlay BEV lane POC assignments on generated frame-input BEV PNGs."""

from __future__ import annotations

import argparse
import html
import json
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from ms_odd_tagging.common.config import FRAME_INPUTS




COLORS = {
    "ego": (22, 163, 74, 96),
    "ego_outline": (22, 163, 74, 255),
    "left": (2, 132, 199, 72),
    "left_outline": (2, 132, 199, 245),
    "right": (217, 119, 6, 72),
    "right_outline": (217, 119, 6, 245),
    "candidate": (148, 163, 184, 28),
    "candidate_outline": (100, 116, 139, 135),
    "weak": (234, 179, 8, 255),
    "unknown": (220, 38, 38, 255),
    "text_bg": (15, 23, 42, 210),
    "text": (248, 250, 252, 255),
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def screen_transform(
    width: int,
    height: int,
    extent: dict[str, float],
):
    left_m = float(extent["left"])
    right_m = float(extent["right"])
    back_m = float(extent["back"])
    forward_m = float(extent["forward"])
    scale = min(width / (left_m + right_m), height / (back_m + forward_m))
    center_x = left_m * scale + (width - (left_m + right_m) * scale) / 2.0
    center_y = forward_m * scale + (height - (back_m + forward_m) * scale) / 2.0

    def screen(point: list[float] | tuple[float, float]) -> tuple[float, float]:
        longitudinal, lateral = float(point[0]), float(point[1])
        return center_x - lateral * scale, center_y - longitudinal * scale

    return screen


def polygon(draw: ImageDraw.ImageDraw, points: list[list[float]], screen, fill, outline, width: int) -> None:
    if len(points) < 3:
        return
    pixels = [screen(point) for point in points]
    draw.polygon(pixels, fill=fill)
    draw.line(pixels + [pixels[0]], fill=outline, width=width, joint="curve")


def label(draw: ImageDraw.ImageDraw, lines: list[str], xy=(12, 12)) -> None:
    font = ImageFont.load_default()
    line_h = 14
    pad = 7
    text_w = max((draw.textlength(line, font=font) for line in lines), default=0)
    box = [
        xy[0],
        xy[1],
        xy[0] + int(text_w) + pad * 2,
        xy[1] + line_h * len(lines) + pad * 2,
    ]
    draw.rounded_rectangle(box, radius=6, fill=COLORS["text_bg"])
    y = xy[1] + pad
    for line in lines:
        draw.text((xy[0] + pad, y), line, fill=COLORS["text"], font=font)
        y += line_h


def overlay_frame(base_png: Path, output_png: Path, frame: dict[str, Any]) -> None:
    image = Image.open(base_png).convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    screen = screen_transform(image.width, image.height, frame["bev_extent_m"])
    selected = {
        (frame.get("ego_lane") or {}).get("lane_id"),
        (frame.get("left_adjacent") or {}).get("lane_id"),
        (frame.get("right_adjacent") or {}).get("lane_id"),
    }
    for lane in frame.get("candidate_lanes") or []:
        if lane.get("lane_id") in selected:
            continue
        polygon(
            draw,
            lane.get("polygon_bev_m") or [],
            screen,
            COLORS["candidate"],
            COLORS["candidate_outline"],
            1,
        )
    polygon(
        draw,
        (frame.get("left_adjacent") or {}).get("polygon_bev_m") or [],
        screen,
        COLORS["left"],
        COLORS["left_outline"],
        3,
    )
    polygon(
        draw,
        (frame.get("right_adjacent") or {}).get("polygon_bev_m") or [],
        screen,
        COLORS["right"],
        COLORS["right_outline"],
        3,
    )
    polygon(
        draw,
        (frame.get("ego_lane") or {}).get("polygon_bev_m") or [],
        screen,
        COLORS["ego"],
        COLORS["ego_outline"],
        5,
    )
    quality = frame.get("assignment_quality") or {}
    state = quality.get("state", "unknown")
    confidence = float(quality.get("confidence") or 0.0)
    reasons = ", ".join(quality.get("reasons") or []) or "none"
    label(
        draw,
        [
            f"frame {frame.get('frame_index')} BEV lane POC",
            f"state: {frame.get('status')}/{state} conf={confidence:.2f}",
            f"ego: {(frame.get('ego_lane') or {}).get('lane_id') or 'none'}",
            f"stable: {(frame.get('ego_lane') or {}).get('stable_key') or 'none'}",
            f"reasons: {reasons}",
        ],
    )
    output_png.parent.mkdir(parents=True, exist_ok=True)
    Image.alpha_composite(image, overlay).convert("RGB").save(output_png)


def render_recording(
    result_path: Path,
    frame_input_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    result = load_json(result_path)
    recording = str(result.get("recording_id") or result_path.name.removesuffix("_bev_lane_poc.json"))
    rows = []
    for frame in result.get("frames") or []:
        frame_index = int(frame["frame_index"])
        source_png = frame_input_root / recording / f"frame_{frame_index:06d}" / "bev.png"
        if not source_png.is_file():
            continue
        output_png = output_root / recording / f"frame_{frame_index:06d}_bev_lane_poc_overlay.png"
        overlay_frame(source_png, output_png, frame)
        rows.append(
            {
                "frame_index": frame_index,
                "image": str(output_png.relative_to(output_root)).replace("/", "/"),
                "state": (frame.get("assignment_quality") or {}).get("state", "unknown"),
                "status": frame.get("status", "unknown"),
                "confidence": (frame.get("assignment_quality") or {}).get("confidence", 0.0),
                "ego_lane_id": (frame.get("ego_lane") or {}).get("lane_id"),
                "stable_key": (frame.get("ego_lane") or {}).get("stable_key"),
                "reasons": (frame.get("assignment_quality") or {}).get("reasons", []),
            }
        )
    return {"recording": recording, "frames": rows}


def index_html(recordings: list[dict[str, Any]]) -> str:
    payload = json.dumps(recordings, ensure_ascii=True, separators=(",", ":"))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BEV Lane POC Image Overlays</title>
<style>
body{{margin:0;background:#eef2f6;color:#17202a;font:14px Arial,sans-serif}}header{{background:#17324d;color:white;padding:18px 24px}}h1{{margin:0 0 6px;font-size:21px}}p{{margin:0;color:#dbeafe}}.toolbar{{position:sticky;top:0;z-index:2;background:#f8fafc;border-bottom:1px solid #cbd5e1;padding:12px 18px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}}input,select{{height:34px;border:1px solid #cbd5e1;border-radius:6px;background:white;padding:0 9px}}main{{padding:16px 18px;display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:14px}}.card{{background:white;border:1px solid #d7dee8;border-radius:8px;overflow:hidden}}.card img{{display:block;width:100%;height:auto;background:#0f172a}}.meta{{padding:9px 10px;display:grid;gap:4px}}.title{{font-weight:700;overflow-wrap:anywhere}}.pill{{display:inline-block;border-radius:999px;background:#edf2f7;padding:3px 7px;font-size:12px;margin-right:4px}}.stable{{background:#dcfce7;color:#166534}}.weak{{background:#fef3c7;color:#92400e}}.unknown{{background:#fee2e2;color:#991b1b}}
</style></head><body>
<header><h1>BEV Lane POC Image Overlays</h1><p>Lane-assignment result polygons over the generated frame-input BEV PNGs.</p></header>
<div class="toolbar"><input id="q" placeholder="recording search"><select id="state"><option value="all">all states</option><option value="stable_candidate">stable</option><option value="weak_candidate">weak</option><option value="unknown">unknown</option></select><span id="count"></span></div>
<main id="grid"></main>
<script>
const RECORDINGS={payload};
const FRAMES=RECORDINGS.flatMap(rec => rec.frames.map(frame => ({{...frame, recording: rec.recording}})));
const q=document.getElementById('q'), state=document.getElementById('state'), grid=document.getElementById('grid'), count=document.getElementById('count');
function esc(s){{return String(s ?? '').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]))}}
function render(){{const term=q.value.toLowerCase();const st=state.value;const rows=FRAMES.filter(frame=>(!term||frame.recording.toLowerCase().includes(term))&&(st==='all'||frame.state===st));count.textContent=`${{rows.length}} / ${{FRAMES.length}}`;grid.innerHTML=rows.map(frame=>`<article class="card"><a href="${{frame.image}}" target="_blank"><img src="${{frame.image}}" loading="lazy"></a><div class="meta"><div class="title">${{esc(frame.recording)}} · frame ${{frame.frame_index}}</div><div><span class="pill ${{frame.state==='stable_candidate'?'stable':frame.state==='weak_candidate'?'weak':'unknown'}}">${{frame.status}}/${{frame.state}}</span><span class="pill">conf ${{Number(frame.confidence||0).toFixed(2)}}</span></div><div>ego: ${{esc(frame.ego_lane_id || 'none')}}</div><div>reasons: ${{esc((frame.reasons || []).join(', ') || 'none')}}</div></div></article>`).join('')||'<p>No matching frames.</p>'}}
q.addEventListener('input',render);state.addEventListener('change',render);render();
</script></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--frame-input-root", type=Path, default=FRAME_INPUTS)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--index-path", type=Path)
    args = parser.parse_args()

    if args.output_dir.exists():
        # Keep this output folder reproducible; it only contains generated overlays.
        shutil.rmtree(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    recordings = [
        render_recording(path, args.frame_input_root, args.output_dir)
        for path in sorted(args.result_dir.glob("*_bev_lane_poc.json"))
    ]
    recordings = [item for item in recordings if item["frames"]]
    index_path = args.index_path or args.output_dir.with_name(args.output_dir.name + "_index.html")
    index_path.write_text(index_html(recordings), encoding="utf-8")
    manifest = {
        "schema_version": "bev-lane-poc-image-overlay-v1",
        "result_dir": str(args.result_dir),
        "frame_input_root": str(args.frame_input_root),
        "output_dir": str(args.output_dir),
        "index_path": str(index_path),
        "recording_count": len(recordings),
        "frame_count": sum(len(item["frames"]) for item in recordings),
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {manifest['frame_count']} BEV overlay image(s)")
    print(f"Wrote index: {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
