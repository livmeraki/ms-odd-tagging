"""Render a single BEV image with a full-window ego path overlay.

This is a standalone PoC helper for inspecting whether a global trajectory
overlay helps VLM verification of starting_u_turn candidates.
"""

from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from ms_odd_tagging.input_generator.model_input import lcs_to_ego
from ms_odd_tagging.input_generator.revised_bev import centered_extent, render_revised_bev_png


DEFAULT_RECORDING = "Rec_Drv_GER_MACHET18_20260422_105826"
DEFAULT_CANDIDATE_ID = f"{DEFAULT_RECORDING}_starting_u_turn_000510_000559"
DEFAULT_CANDIDATE = (
    Path("outputs/qwen_vlm_poc_2_new_scenarios_20260807/recordings")
    / DEFAULT_RECORDING
    / "starting_u_turn/candidates/starting_u_turn"
    / DEFAULT_RECORDING
    / f"{DEFAULT_CANDIDATE_ID}.json"
)
DEFAULT_RECORDING_JSON = (
    Path("/media/stradvision/25eb199d-ae8a-49d6-b7e9-675eb144ddcd")
    / "ms-odd-tagging-data/outputs/01_canonical"
    / f"{DEFAULT_RECORDING}_canonical_odld_frames.json"
)
DEFAULT_OUTPUT_DIR = Path("outputs/qwen_vlm_path_overlay_poc") / DEFAULT_RECORDING


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _candidate_payload(path: Path) -> dict[str, Any]:
    data = _load_json(path)
    return data.get("candidate", data)


def _ego_motion_frames(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    for item in candidate.get("evidence", []):
        if item.get("kind") == "ego_motion":
            frames = ((item.get("data") or {}).get("frames")) or []
            return [frame for frame in frames if isinstance(frame, dict)]
    return []


def _heading_change(candidate: dict[str, Any]) -> dict[str, Any]:
    for item in candidate.get("evidence", []):
        if item.get("kind") == "ego_heading_change":
            return item.get("data") or {}
    return {}


def _frame_by_index(recording: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        int(frame["frame_index"]): frame
        for frame in recording.get("frames", [])
        if isinstance(frame.get("frame_index"), int)
    }


def _recording_motion_frame(frame: dict[str, Any]) -> dict[str, Any]:
    ego = frame.get("ego") or {}
    return {
        "frame_index": frame.get("frame_index"),
        "time_since_start_s": frame.get("time_since_start_s"),
        "ego": {
            "position_lcs_m": ego.get("position_lcs_m"),
            "speed_mps": ego.get("speed_mps"),
            "acceleration_mps2": ego.get("acceleration_mps2"),
            "heading_lcs_rad": ego.get("heading_lcs_rad"),
        },
    }


def _screen_transform(
    width: int,
    height: int,
    extent: tuple[float, float, float, float],
):
    left_m, right_m, back_m, forward_m = centered_extent(extent)
    scale_x = width / (left_m + right_m)
    scale_y = height / (back_m + forward_m)
    center_x = width / 2.0
    center_y = height / 2.0

    def screen(point: tuple[float, float]) -> tuple[float, float]:
        longitudinal, lateral = point
        return center_x - lateral * scale_x, center_y - longitudinal * scale_y

    return screen


def _arrow_points(
    x: float,
    y: float,
    heading_in_anchor_rad: float,
    *,
    length_px: float = 26.0,
    width_px: float = 10.0,
) -> list[tuple[float, float]]:
    # BEV screen has forward/up at angle -pi/2. Positive lateral is screen-left.
    angle = -math.pi / 2.0 - heading_in_anchor_rad
    tip = (x + math.cos(angle) * length_px, y + math.sin(angle) * length_px)
    left = (
        x + math.cos(angle + 2.45) * width_px,
        y + math.sin(angle + 2.45) * width_px,
    )
    right = (
        x + math.cos(angle - 2.45) * width_px,
        y + math.sin(angle - 2.45) * width_px,
    )
    return [tip, left, right]


def _draw_label(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str) -> None:
    font = ImageFont.load_default()
    x, y = xy
    bbox = draw.textbbox((x, y), text, font=font)
    pad = 4
    draw.rectangle(
        (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad),
        fill=(255, 255, 255),
        outline=(15, 23, 42),
        width=1,
    )
    draw.text((x, y), text, fill=(15, 23, 42), font=font)


def render_overlay(
    *,
    candidate_path: Path,
    recording_json: Path,
    output_dir: Path,
    anchor_frame: int | None,
    buffer_frames: int,
    extent: tuple[float, float, float, float],
    size: tuple[int, int],
) -> tuple[Path, Path, Path]:
    candidate = _candidate_payload(candidate_path)
    motion_frames = _ego_motion_frames(candidate)
    if not motion_frames:
        raise ValueError(f"No ego_motion evidence found in {candidate_path}")

    heading_data = _heading_change(candidate)
    anchor_frame = int(anchor_frame or heading_data.get("strongest_frame_index") or motion_frames[len(motion_frames) // 2]["frame_index"])

    recording = _load_json(recording_json)
    frames_by_index = _frame_by_index(recording)
    anchor = frames_by_index.get(anchor_frame)
    if anchor is None:
        raise ValueError(f"Anchor frame {anchor_frame} not found in {recording_json}")

    visual_start_frame = max(0, int(candidate["start_frame"]) - max(0, buffer_frames))
    visual_end_frame = int(candidate["end_frame"]) + max(0, buffer_frames)
    visual_frames = [
        frames_by_index[index]
        for index in range(visual_start_frame, visual_end_frame + 1)
        if index in frames_by_index
    ]
    if not visual_frames:
        raise ValueError(f"No visual buffer frames found for {visual_start_frame}-{visual_end_frame}")

    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"anchor_{anchor_frame:06d}_buffer_{max(0, buffer_frames):03d}"
    background_path = output_dir / f"{candidate['candidate_id']}_{suffix}_background.png"
    overlay_path = output_dir / f"{candidate['candidate_id']}_{suffix}_path_overlay.png"
    summary_path = output_dir / f"{candidate['candidate_id']}_{suffix}_path_overlay.json"
    bundle_path = output_dir / f"{candidate['candidate_id']}_{suffix}_candidate_bundle.json"
    html_path = output_dir / "review.html"

    render_revised_bev_png(recording, anchor, background_path, extent, size)

    image = Image.open(background_path).convert("RGBA")
    draw = ImageDraw.Draw(image)
    screen = _screen_transform(image.width, image.height, extent)
    anchor_ego = anchor["ego"]
    anchor_pos = anchor_ego["position_lcs_m"]
    anchor_heading = float(anchor_ego.get("heading_lcs_rad") or 0.0)

    path_points = []
    sampled = []
    for frame in visual_frames:
        motion_frame = _recording_motion_frame(frame)
        ego = motion_frame.get("ego") or {}
        pos = ego.get("position_lcs_m")
        if not isinstance(pos, list) or len(pos) < 2:
            continue
        ego_point = lcs_to_ego(pos, anchor_pos, anchor_heading)
        xy = screen(ego_point)
        path_points.append((frame.get("frame_index"), xy))
        sampled.append(
            {
                "frame_index": motion_frame.get("frame_index"),
                "time_since_start_s": motion_frame.get("time_since_start_s"),
                "position_lcs_m": pos,
                "position_anchor_bev_m": [round(float(ego_point[0]), 3), round(float(ego_point[1]), 3)],
                "screen_xy_px": [round(float(xy[0]), 1), round(float(xy[1]), 1)],
                "heading_lcs_rad": ego.get("heading_lcs_rad"),
                "within_candidate_window": int(candidate["start_frame"]) <= int(frame.get("frame_index")) <= int(candidate["end_frame"]),
            }
        )

    candidate_motion_points = []
    for frame in motion_frames:
        ego = frame.get("ego") or {}
        pos = ego.get("position_lcs_m")
        if not isinstance(pos, list) or len(pos) < 2:
            continue
        ego_point = lcs_to_ego(pos, anchor_pos, anchor_heading)
        candidate_motion_points.append((frame.get("frame_index"), screen(ego_point)))

    if len(path_points) < 2:
        raise ValueError("Not enough path points to draw")

    # White underlay keeps the path legible over lane markings.
    all_points = [point for _, point in path_points]
    candidate_points = [point for _, point in candidate_motion_points]
    before_points = [point for frame_index, point in path_points if int(frame_index) < int(candidate["start_frame"])]
    after_points = [point for frame_index, point in path_points if int(frame_index) > int(candidate["end_frame"])]

    draw.line(all_points, fill=(255, 255, 255, 230), width=13, joint="curve")
    if before_points:
        draw.line(before_points + candidate_points[:1], fill=(100, 116, 139, 210), width=5, joint="curve")
    draw.line(candidate_points, fill=(220, 38, 38, 255), width=8, joint="curve")
    if after_points:
        draw.line(candidate_points[-1:] + after_points, fill=(37, 99, 235, 220), width=5, joint="curve")

    for i, point in enumerate(all_points):
        if i in (0, len(path_points) - 1) or i % 5 == 0:
            radius = 4 if i not in (0, len(path_points) - 1) else 7
            fill = (22, 163, 74, 255) if i == 0 else (37, 99, 235, 255) if i == len(path_points) - 1 else (220, 38, 38, 255)
            draw.ellipse((point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius), fill=fill, outline=(255, 255, 255, 255), width=2)

    start = _recording_motion_frame(visual_frames[0])
    end = _recording_motion_frame(visual_frames[-1])
    for frame, point, label, color in (
        (start, all_points[0], f"START f{start.get('frame_index')}", (22, 163, 74, 230)),
        (end, all_points[-1], f"END f{end.get('frame_index')}", (37, 99, 235, 230)),
    ):
        heading = float(((frame.get("ego") or {}).get("heading_lcs_rad")) or 0.0) - anchor_heading
        draw.polygon(_arrow_points(point[0], point[1], heading), fill=color, outline=(255, 255, 255, 255))

    _draw_label(draw, (14, 14), f"{candidate['recording_id']} starting_u_turn")
    _draw_label(
        draw,
        (14, 42),
        f"event {candidate['start_frame']}-{candidate['end_frame']} | visual {visual_frames[0]['frame_index']}-{visual_frames[-1]['frame_index']} | anchor {anchor_frame}",
    )
    _draw_label(
        draw,
        (14, 70),
        f"gray=pre-buffer | red=candidate | blue=post-buffer | net heading {heading_data.get('net_heading_change_deg')} deg",
    )
    _draw_label(draw, (all_points[0][0] + 10, all_points[0][1] + 10), f"buffer start f{visual_frames[0]['frame_index']}")
    _draw_label(draw, (all_points[-1][0] + 10, all_points[-1][1] + 10), f"buffer end f{visual_frames[-1]['frame_index']}")

    image.convert("RGB").save(overlay_path, quality=95)

    summary = {
        "schema_version": "starting-u-turn-path-overlay-poc-v1",
        "candidate_id": candidate["candidate_id"],
        "recording_id": candidate["recording_id"],
        "scenario": candidate["scenario"],
        "start_frame": candidate["start_frame"],
        "end_frame": candidate["end_frame"],
        "visual_start_frame": visual_frames[0]["frame_index"],
        "visual_end_frame": visual_frames[-1]["frame_index"],
        "buffer_frames_requested": max(0, buffer_frames),
        "anchor_frame": anchor_frame,
        "background_path": str(background_path),
        "overlay_path": str(overlay_path),
        "candidate_bundle_path": str(bundle_path),
        "heading_change": heading_data,
        "sampled_path": sampled,
        "note": "Path points are projected into the anchor frame ego-heading-up BEV coordinates.",
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    buffered_candidate = dict(candidate)
    buffered_candidate["bev_paths"] = [str(overlay_path)]
    buffered_candidate["selected_frame_indices"] = [anchor_frame]
    buffered_candidate["metadata"] = {
        **(candidate.get("metadata") or {}),
        "path_overlay_poc": {
            "anchor_frame": anchor_frame,
            "overlay_path": str(overlay_path),
            "visual_start_frame": visual_frames[0]["frame_index"],
            "visual_end_frame": visual_frames[-1]["frame_index"],
            "buffer_frames_before": int(candidate["start_frame"]) - int(visual_frames[0]["frame_index"]),
            "buffer_frames_after": int(visual_frames[-1]["frame_index"]) - int(candidate["end_frame"]),
            "note": "Single anchor-frame BEV includes pre-buffer, candidate event, and post-buffer ego path overlay.",
        },
    }
    overlay_evidence_id = f"{candidate['candidate_id']}:path_overlay_context"
    buffered_candidate["evidence"] = list(candidate.get("evidence") or []) + [
        {
            "evidence_id": overlay_evidence_id,
            "kind": "path_overlay_context",
            "summary": (
                f"Single anchor-frame BEV path overlay uses visual frames "
                f"{visual_frames[0]['frame_index']}-{visual_frames[-1]['frame_index']} "
                f"with event frames {candidate['start_frame']}-{candidate['end_frame']} highlighted."
            ),
            "data": {
                "anchor_frame": anchor_frame,
                "visual_start_frame": visual_frames[0]["frame_index"],
                "visual_end_frame": visual_frames[-1]["frame_index"],
                "event_start_frame": candidate["start_frame"],
                "event_end_frame": candidate["end_frame"],
                "overlay_path": str(overlay_path),
                "legend": {
                    "gray_path": "pre-candidate buffer",
                    "red_path": "candidate event window",
                    "blue_path": "post-candidate buffer",
                },
                "sampled_path": sampled,
            },
        }
    ]
    bundle_path.write_text(
        json.dumps(
            {
                "schema_version": "qwen-vlm-poc-candidate-v1",
                "candidate": buffered_candidate,
                "instructions": {
                    "one_scenario_per_request": True,
                    "use_only_supplied_evidence": True,
                    "json_only": True,
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    html_path.write_text(
        _render_html(candidate, summary, overlay_path, background_path),
        encoding="utf-8",
    )
    return overlay_path, summary_path, html_path


def _relative(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _render_html(
    candidate: dict[str, Any],
    summary: dict[str, Any],
    overlay_path: Path,
    background_path: Path,
) -> str:
    base = overlay_path.parent
    heading = summary.get("heading_change") or {}
    sampled = summary.get("sampled_path") or []
    rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(row.get('frame_index')))}</td>"
        f"<td>{html.escape(str(row.get('position_lcs_m')))}</td>"
        f"<td>{html.escape(str(row.get('position_anchor_bev_m')))}</td>"
        f"<td>{html.escape(str(row.get('heading_lcs_rad')))}</td>"
        "</tr>"
        for row in sampled[::5] + ([sampled[-1]] if sampled and sampled[-1] not in sampled[::5] else [])
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Starting U-turn Path Overlay PoC</title>
<style>
body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#f8fafc;color:#0f172a}}
header{{padding:18px 24px;border-bottom:1px solid #cbd5e1;background:white}}
main{{padding:20px 24px;display:grid;grid-template-columns:minmax(360px,820px) minmax(320px,1fr);gap:20px;align-items:start}}
img{{width:100%;height:auto;border:1px solid #cbd5e1;background:white}}
.panel{{background:white;border:1px solid #cbd5e1;padding:14px}}
.kv{{display:grid;grid-template-columns:170px 1fr;gap:6px 12px;font-size:14px}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin-top:12px}}
td,th{{border-top:1px solid #e2e8f0;padding:6px;text-align:left;vertical-align:top}}
code{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}}
</style>
</head>
<body>
<header>
<h1>Starting U-turn Path Overlay PoC</h1>
<div><code>{html.escape(str(candidate.get("candidate_id")))}</code></div>
</header>
<main>
<section>
<img src="{html.escape(_relative(overlay_path, base))}" alt="Single BEV with full ego path overlay">
</section>
<aside class="panel">
<div class="kv">
<b>Recording</b><span>{html.escape(str(candidate.get("recording_id")))}</span>
<b>Scenario</b><span>{html.escape(str(candidate.get("scenario")))}</span>
<b>Frames</b><span>{html.escape(str(candidate.get("start_frame")))}-{html.escape(str(candidate.get("end_frame")))}</span>
<b>Visual frames</b><span>{html.escape(str(summary.get("visual_start_frame")))}-{html.escape(str(summary.get("visual_end_frame")))}</span>
<b>Buffer</b><span>{html.escape(str(summary.get("buffer_frames_requested")))} frame(s) each side</span>
<b>Anchor frame</b><span>{html.escape(str(summary.get("anchor_frame")))}</span>
<b>Net heading</b><span>{html.escape(str(heading.get("net_heading_change_deg")))} deg</span>
<b>Displacement</b><span>{html.escape(str(heading.get("displacement_m")))} m</span>
<b>Candidate bundle</b><span><code>{html.escape(_relative(Path(str(summary.get("candidate_bundle_path"))), base))}</code></span>
<b>Background</b><span><code>{html.escape(_relative(background_path, base))}</code></span>
</div>
<h2>Sampled Path</h2>
<table>
<thead><tr><th>Frame</th><th>LCS position</th><th>Anchor BEV m</th><th>Heading rad</th></tr></thead>
<tbody>{rows}</tbody>
</table>
</aside>
</main>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--recording-json", type=Path, default=DEFAULT_RECORDING_JSON)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--anchor-frame", type=int)
    parser.add_argument("--buffer-frames", type=int, default=10)
    parser.add_argument("--bev-extent-m", type=float, nargs=4, default=(45.0, 45.0, 25.0, 70.0))
    parser.add_argument("--bev-size-px", type=int, nargs=2, default=(768, 768))
    args = parser.parse_args()

    overlay_path, summary_path, html_path = render_overlay(
        candidate_path=args.candidate,
        recording_json=args.recording_json,
        output_dir=args.output_dir,
        anchor_frame=args.anchor_frame,
        buffer_frames=args.buffer_frames,
        extent=tuple(args.bev_extent_m),
        size=tuple(args.bev_size_px),
    )
    print(f"Wrote overlay: {overlay_path}")
    print(f"Wrote summary: {summary_path}")
    print(f"Wrote HTML: {html_path}")


if __name__ == "__main__":
    main()
