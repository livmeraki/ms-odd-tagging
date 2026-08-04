#!/usr/bin/env python3
"""Generate task-specific review pages for predicted starting turn events."""

from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
from typing import Any


DEFAULT_DATA_ROOT = Path(
    "/media/stradvision/25eb199d-ae8a-49d6-b7e9-675eb144ddcd/ms-odd-tagging-data"
)
TARGET_LABELS = ("starting_left_turn", "starting_right_turn")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def recording_from_gt_path(path: Path) -> str:
    return path.name.removesuffix("_frame_gt.json")


def image_uri(frame_path: Path, output_dir: Path) -> str | None:
    frame = load_json(frame_path)
    bev = frame.get("bev") or {}
    image_path = frame_path.parent / str(bev.get("path") or "bev.png")
    if not image_path.is_file():
        return None
    return os.path.relpath(image_path.resolve(), output_dir.resolve()).replace(os.sep, "/")


def event_target_labels(event: dict[str, Any]) -> list[str]:
    scenario = event.get("scenario")
    return [str(scenario)] if scenario in TARGET_LABELS else []


def build_recording_payload(
    recording: str,
    frame_input_root: Path,
    gt_dir: Path,
    output_dir: Path,
    context_samples: int,
) -> dict[str, Any] | None:
    recording_dir = frame_input_root / recording
    rule_path = recording_dir / "recording_rule_events.json"
    if not rule_path.is_file():
        return None
    events = [
        event
        for event in load_json(rule_path).get("rule_based_events", [])
        if event.get("scenario") in TARGET_LABELS
    ]
    if not events:
        return None

    frame_paths = sorted(recording_dir.glob("frame_*/frame.json"))
    frames_by_index = {load_json(path).get("frame_index"): path for path in frame_paths}
    sorted_indices = sorted(index for index in frames_by_index if isinstance(index, int))
    gt_path = gt_dir / f"{recording}_frame_gt.json"
    gt = load_json(gt_path) if gt_path.is_file() else {"frames": {}}

    selected_indices: set[int] = set()
    event_rows = []
    for event_index, event in enumerate(events):
        inside = [
            index
            for index in sorted_indices
            if event.get("start_frame", 10**12) <= index <= event.get("end_frame", -1)
        ]
        if context_samples and inside:
            start_position = max(0, sorted_indices.index(inside[0]) - context_samples)
            end_position = min(
                len(sorted_indices),
                sorted_indices.index(inside[-1]) + context_samples + 1,
            )
            selected_indices.update(sorted_indices[start_position:end_position])
        selected_indices.update(inside)
        event_rows.append(
            {
                "id": f"event-{event_index}",
                "scenario": event.get("scenario"),
                "start_frame": event.get("start_frame"),
                "end_frame": event.get("end_frame"),
                "start_timestamp_s": event.get("start_timestamp_s"),
                "end_timestamp_s": event.get("end_timestamp_s"),
                "duration_s": event.get("duration_s"),
                "sampled_frame_count": len(inside),
                "evidence": event.get("evidence") if isinstance(event.get("evidence"), dict) else {},
            }
        )

    review_frames = []
    for index in sorted(selected_indices):
        frame_path = frames_by_index[index]
        frame = load_json(frame_path)
        frame_id = str(frame.get("frame_id") or f"{recording}:frame-{index:06d}")
        gt_frame = gt.get("frames", {}).get(frame_id, {})
        labels = gt_frame.get("labels") if isinstance(gt_frame.get("labels"), dict) else {}
        active_events = [
            {
                "id": f"event-{event_index}",
                "scenario": event.get("scenario"),
                "start_frame": event.get("start_frame"),
                "end_frame": event.get("end_frame"),
            }
            for event_index, event in enumerate(events)
            if event.get("start_frame", 10**12) <= index <= event.get("end_frame", -1)
        ]
        predicted = {label: any(event["scenario"] == label for event in active_events) for label in TARGET_LABELS}
        gt_labels = {label: labels.get(label) for label in TARGET_LABELS}
        mismatch = any(isinstance(gt_labels[label], bool) and gt_labels[label] != predicted[label] for label in TARGET_LABELS)
        review_frames.append(
            {
                "frame_id": frame_id,
                "frame_index": index,
                "time_since_start_s": frame.get("time_since_start_s"),
                "speed_mps": (frame.get("ego") or {}).get("speed_mps"),
                "image": image_uri(frame_path, output_dir),
                "predicted": predicted,
                "gt": gt_labels,
                "needs_review": gt_frame.get("needs_review"),
                "excluded_from_evaluation": gt_frame.get("excluded_from_evaluation"),
                "active_events": active_events,
            }
        )

    return {
        "schema_version": "turn-prediction-review-v1",
        "recording_id": recording,
        "target_labels": list(TARGET_LABELS),
        "source_event_file": str(rule_path),
        "gt_file": str(gt_path) if gt_path.is_file() else None,
        "events": event_rows,
        "frames": review_frames,
        "summary": {
            "event_count": len(event_rows),
            "frame_count": len(review_frames),
            "mismatch_frame_count": sum(
                1
                for frame in review_frames
                if any(
                    isinstance(frame["gt"][label], bool)
                    and frame["gt"][label] != frame["predicted"][label]
                    for label in TARGET_LABELS
                )
            ),
            "unknown_gt_frame_count": sum(
                1
                for frame in review_frames
                if any(frame["gt"][label] is None for label in TARGET_LABELS)
            ),
        },
    }


def recording_html(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c")
    title = html.escape(f"Turn Prediction Review - {payload['recording_id']}")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
:root{{--bg:#f4f6f8;--panel:#fff;--text:#172033;--muted:#667085;--border:#d7dee8;--accent:#2458c6;--yes:#16703a;--no:#b42318;--warn:#b76e00;--unknown:#64748b}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px Arial,sans-serif}}header{{position:sticky;top:0;z-index:2;background:var(--panel);border-bottom:1px solid var(--border);padding:12px 18px}}h1{{font-size:18px;margin:0 0 8px}}.toolbar{{display:flex;gap:8px;flex-wrap:wrap;align-items:center}}button,select,input{{border:1px solid var(--border);background:var(--panel);color:var(--text);border-radius:6px;padding:7px 9px}}button{{cursor:pointer}}button.active{{background:var(--accent);border-color:var(--accent);color:white}}main{{max-width:1550px;margin:auto;padding:14px}}.summary{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}}.pill{{border:1px solid var(--border);background:var(--panel);border-radius:999px;padding:5px 9px;color:var(--muted)}}.layout{{display:grid;grid-template-columns:340px 1fr;gap:12px}}.panel{{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:10px}}.events{{display:grid;gap:8px;max-height:76vh;overflow:auto}}.event{{border:1px solid var(--border);border-radius:7px;padding:8px;cursor:pointer}}.event.active{{border-color:var(--accent);box-shadow:0 0 0 2px rgba(36,88,198,.12)}}.event b{{display:block;margin-bottom:4px}}.frames{{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:10px}}.card{{background:var(--panel);border:1px solid var(--border);border-radius:8px;overflow:hidden}}.card.mismatch{{border-color:var(--no);box-shadow:0 0 0 2px rgba(180,35,24,.10)}}.card.match{{border-color:#9ed4ad}}.card.unknown{{border-color:var(--warn)}}.media{{background:#0d1117;min-height:190px;display:grid;place-items:center}}img{{display:block;width:100%;height:240px;object-fit:contain}}.body{{padding:9px}}.badges{{display:flex;gap:5px;flex-wrap:wrap;margin:6px 0}}.badge{{border-radius:999px;padding:3px 7px;font-size:12px;background:#edf2f7;color:#334155}}.badge.yes{{background:#dff6e6;color:var(--yes)}}.badge.no{{background:#fde3e1;color:var(--no)}}.badge.warn{{background:#fff2cc;color:#7a4b00}}.badge.unknown{{background:#e5e7eb;color:var(--unknown)}}code{{white-space:pre-wrap;overflow-wrap:anywhere;color:var(--muted);font-size:12px}}@media(max-width:920px){{.layout{{grid-template-columns:1fr}}.events{{max-height:none}}}}
</style></head><body>
<header><h1>{title}</h1><div class="toolbar">
<button id="all" class="active">All</button><button id="mismatch">Mismatches</button><button id="unknown">Unknown GT</button>
<select id="label"><option value="all">both labels</option><option value="starting_left_turn">starting left turn</option><option value="starting_right_turn">starting right turn</option></select>
<input id="jump" type="number" placeholder="frame index"><button id="jumpBtn">Jump</button>
</div></header>
<main><div class="summary" id="summary"></div><div class="layout"><aside class="panel"><h2>Predicted Events</h2><div class="events" id="events"></div></aside><section><div class="frames" id="frames"></div></section></div></main>
<script>
const DATA={serialized};let mode='all';let selectedEvent=null;
function badge(text,cls=''){{return `<span class="badge ${{cls}}">${{text}}</span>`}}
function value(v,d=2){{return v==null?'n/a':Number(v).toFixed(d)}}
function frameStatus(frame){{let hasBool=false, mismatch=false, unknown=false;for(const label of DATA.target_labels){{const gt=frame.gt[label], pred=frame.predicted[label];if(gt===null||gt===undefined)unknown=true;if(typeof gt==='boolean'){{hasBool=true;if(gt!==pred)mismatch=true}}}}if(mismatch)return 'mismatch';if(unknown||!hasBool)return 'unknown';return 'match'}}
function labelOk(frame){{const label=document.getElementById('label').value;if(label==='all')return true;return frame.predicted[label] || frame.gt[label]===true}}
function modeOk(frame){{const status=frameStatus(frame);if(mode==='mismatch')return status==='mismatch';if(mode==='unknown')return status==='unknown';return true}}
function eventOk(frame){{return selectedEvent==null || frame.active_events.some(event=>event.id===selectedEvent)}}
function renderSummary(){{const frames=DATA.frames.filter(frame=>labelOk(frame));document.getElementById('summary').innerHTML=[
badge(`${{DATA.summary.event_count}} predicted events`),badge(`${{DATA.summary.frame_count}} review frames`),badge(`${{frames.filter(frame=>frameStatus(frame)==='mismatch').length}} mismatches`,'no'),badge(`${{frames.filter(frame=>frameStatus(frame)==='unknown').length}} unknown GT`,'warn'),badge(`${{frames.filter(frame=>frameStatus(frame)==='match').length}} matches`,'yes')
].join('')}}
function renderEvents(){{const root=document.getElementById('events');root.innerHTML='';for(const event of DATA.events){{const div=document.createElement('div');div.className='event'+(selectedEvent===event.id?' active':'');div.onclick=()=>{{selectedEvent=selectedEvent===event.id?null:event.id;render()}};div.innerHTML=`<b>${{event.scenario.replaceAll('_',' ')}}</b><div>frames ${{event.start_frame}}-${{event.end_frame}} · ${{value(event.duration_s)}}s · ${{event.sampled_frame_count}} sampled frames</div><code>${{JSON.stringify(event.evidence||{{}},null,2)}}</code>`;root.appendChild(div)}}}}
function renderFrames(){{const root=document.getElementById('frames');root.innerHTML='';const frames=DATA.frames.filter(frame=>labelOk(frame)&&modeOk(frame)&&eventOk(frame));if(!frames.length){{root.innerHTML='<div class="panel">No frames match the current filter.</div>';return}}for(const frame of frames){{const status=frameStatus(frame);const card=document.createElement('article');card.className=`card ${{status}}`;const labelBadges=DATA.target_labels.map(label=>{{const pred=frame.predicted[label], gt=frame.gt[label];const cls=gt==null?'unknown':gt===pred?'yes':'no';return badge(`${{label.replace('starting_','').replace('_turn','')}} · pred ${{pred?'Y':'N'}} · GT ${{gt==null?'?':gt?'Y':'N'}}`,cls)}}).join('');const events=frame.active_events.map(event=>event.scenario.replaceAll('_',' ')).join(', ')||'none';card.innerHTML=`<div class="media">${{frame.image?`<img src="${{frame.image}}" loading="lazy">`:'missing BEV'}}</div><div class="body"><b>Frame ${{frame.frame_index}}</b><div>${{value(frame.time_since_start_s,3)}}s · speed ${{value(frame.speed_mps)}} m/s</div><div class="badges">${{labelBadges}}${{frame.needs_review?badge('needs review','warn'):''}}${{frame.excluded_from_evaluation?badge('excluded','warn'):''}}</div><div>Active predicted event: ${{events}}</div></div>`;root.appendChild(card)}}}}
function render(){{for(const id of ['all','mismatch','unknown'])document.getElementById(id).classList.toggle('active',mode===id);renderSummary();renderEvents();renderFrames()}}
for(const id of ['all','mismatch','unknown'])document.getElementById(id).onclick=()=>{{mode=id;render()}};document.getElementById('label').onchange=render;document.getElementById('jumpBtn').onclick=()=>{{const target=Number(document.getElementById('jump').value);if(!Number.isFinite(target))return;selectedEvent=null;mode='all';render();const card=[...document.querySelectorAll('.card')].find(node=>node.textContent.includes(`Frame ${{target}}`));if(card)card.scrollIntoView({{behavior:'smooth',block:'center'}})}};render();
</script></body></html>"""


def index_html(rows: list[dict[str, Any]]) -> str:
    row_json = json.dumps(rows, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c")
    cards = "\n".join(
        f"""<a class="card" href="{html.escape(row['file'])}">
  <h2>{html.escape(row['recording_id'])}</h2>
  <p>{row['event_count']} events · {row['frame_count']} frames · {row['mismatch_frame_count']} mismatches · {row['unknown_gt_frame_count']} unknown GT</p>
</a>"""
        for row in rows
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Starting Turn Prediction Review</title><style>
body{{margin:0;background:#f4f6f8;color:#172033;font:14px Arial,sans-serif}}header{{position:sticky;top:0;background:white;border-bottom:1px solid #d7dee8;padding:16px 22px}}h1{{margin:0 0 10px;font-size:21px}}.toolbar{{display:grid;grid-template-columns:minmax(240px,1fr) 160px 160px 160px;gap:8px}}input,select{{border:1px solid #d7dee8;border-radius:6px;padding:8px}}main{{padding:16px 22px;display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:12px}}.card{{display:block;background:white;border:1px solid #d7dee8;border-radius:8px;padding:12px;text-decoration:none;color:inherit}}.card:hover{{border-color:#2458c6}}h2{{font-size:15px;overflow-wrap:anywhere}}p{{color:#667085}}@media(max-width:800px){{.toolbar{{grid-template-columns:1fr}}main{{grid-template-columns:1fr}}}}
</style></head><body><header><h1>Starting Turn Prediction Review</h1><div class="toolbar"><input id="search" placeholder="recording search"><select id="label"><option value="all">both labels</option><option value="left">left predicted</option><option value="right">right predicted</option></select><select id="issue"><option value="all">all</option><option value="mismatch">has mismatch</option><option value="unknown">has unknown GT</option></select><select id="sort"><option value="recording_id">recording</option><option value="event_count">event count</option><option value="mismatch_frame_count">mismatches</option></select></div></header><main id="grid">{cards}</main><script>
const ROWS={row_json};const grid=document.getElementById('grid');
function card(row){{return `<a class="card" href="${{row.file}}"><h2>${{row.recording_id}}</h2><p>${{row.event_count}} events · ${{row.frame_count}} frames · ${{row.mismatch_frame_count}} mismatches · ${{row.unknown_gt_frame_count}} unknown GT</p></a>`}}
function render(){{const q=document.getElementById('search').value.toLowerCase(),label=document.getElementById('label').value,issue=document.getElementById('issue').value,sort=document.getElementById('sort').value;let rows=ROWS.filter(row=>row.recording_id.toLowerCase().includes(q));if(label==='left')rows=rows.filter(row=>row.left_event_count>0);if(label==='right')rows=rows.filter(row=>row.right_event_count>0);if(issue==='mismatch')rows=rows.filter(row=>row.mismatch_frame_count>0);if(issue==='unknown')rows=rows.filter(row=>row.unknown_gt_frame_count>0);rows.sort((a,b)=>sort==='recording_id'?a.recording_id.localeCompare(b.recording_id):(b[sort]-a[sort]));grid.innerHTML=rows.map(card).join('')||'<p>No matching recordings.</p>'}}
for(const id of ['search','label','issue','sort'])document.getElementById(id).addEventListener('input',render);render();
</script></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame-input-root", type=Path, default=DEFAULT_DATA_ROOT / "outputs/02_frame_inputs")
    parser.add_argument("--gt-dir", type=Path, default=DEFAULT_DATA_ROOT / "data/02_gt")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_DATA_ROOT / "outputs/08_turn_prediction_gt_review",
    )
    parser.add_argument("--context-samples", type=int, default=1)
    parser.add_argument("recordings", nargs="*")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    requested = set(args.recordings)
    recording_ids = (
        sorted(requested)
        if requested
        else sorted(path.name for path in args.frame_input_root.iterdir() if path.is_dir())
    )
    rows = []
    for recording in recording_ids:
        payload = build_recording_payload(
            recording,
            args.frame_input_root,
            args.gt_dir,
            args.output_dir,
            max(0, args.context_samples),
        )
        if payload is None:
            continue
        filename = f"{recording}_turn_prediction_gt_review.html"
        (args.output_dir / filename).write_text(recording_html(payload), encoding="utf-8")
        row = {
            "recording_id": recording,
            "file": filename,
            **payload["summary"],
            "left_event_count": sum(1 for event in payload["events"] if event["scenario"] == "starting_left_turn"),
            "right_event_count": sum(1 for event in payload["events"] if event["scenario"] == "starting_right_turn"),
        }
        rows.append(row)
        print(f"Wrote {args.output_dir / filename}")

    (args.output_dir / "index.html").write_text(index_html(rows), encoding="utf-8")
    (args.output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "turn-prediction-review-manifest-v1",
                "frame_input_root": str(args.frame_input_root),
                "gt_dir": str(args.gt_dir),
                "target_labels": list(TARGET_LABELS),
                "recordings": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.output_dir / 'index.html'}")
    print(f"Recordings: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
