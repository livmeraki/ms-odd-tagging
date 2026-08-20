#!/usr/bin/env python3
"""Generate an editable review GUI for recent lane-change strategy events."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
from pathlib import Path
from typing import Any

from ms_odd_tagging.common.config import (
    DATA_GT,
    FRAME_INPUTS,
    ODLD_SCENARIO_EXPLORERS,
    SCENARIO_REVIEW_EXPLORERS,
)


TARGET_LABELS = ("changing_lane_to_left", "changing_lane_to_right")
STRATEGY_NAME = "topology_turn_aware_lane_change"
RECENT_STRATEGY_EVIDENCE_KEYS = (
    "intersection_active",
    "topology_class",
    "topology_confidence",
    "turn_candidate",
    "lane_change_suppression_reason",
    "final_decision_reason",
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_explorer_data(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    match = re.search(
        r'<script id="recording-data" type="application/json">(.*?)</script>',
        text,
        re.S,
    ) or re.search(r"const DATA = (.*?);\n", text, re.S)
    if not match:
        raise ValueError(f"could not find embedded explorer DATA in {path}")
    return json.loads(match.group(1))


def rel_image(frame_path: Path, output_dir: Path) -> str | None:
    frame = load_json(frame_path)
    bev = frame.get("bev") or {}
    image_path = frame_path.parent / str(bev.get("path") or "bev.png")
    if not image_path.is_file():
        return None
    return os.path.relpath(image_path.resolve(), output_dir.resolve()).replace(os.sep, "/")


def existing_gt_votes(gt_path: Path, label: str, frame_indices: list[int]) -> dict[str, Any]:
    if not gt_path.is_file():
        return {"status": "missing_gt_file", "positive": 0, "negative": 0, "unknown": len(frame_indices)}
    gt = load_json(gt_path)
    frames = gt.get("frames", {})
    by_index = {
        frame.get("frame_index"): frame
        for frame in frames.values()
        if isinstance(frame, dict) and isinstance(frame.get("frame_index"), int)
    }
    positive = negative = unknown = 0
    for index in frame_indices:
        value = ((by_index.get(index) or {}).get("labels") or {}).get(label)
        if value is True:
            positive += 1
        elif value is False:
            negative += 1
        else:
            unknown += 1
    if positive:
        status = "gt_positive"
    elif negative and not unknown:
        status = "gt_negative"
    elif negative:
        status = "gt_negative_with_unknown"
    else:
        status = "gt_unknown"
    return {"status": status, "positive": positive, "negative": negative, "unknown": unknown}


def summarize_recent_strategy_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "strategy": STRATEGY_NAME,
        "recent_strategy_evidence_present": all(key in evidence for key in RECENT_STRATEGY_EVIDENCE_KEYS),
        "topology_class": evidence.get("topology_class"),
        "topology_confidence": evidence.get("topology_confidence"),
        "intersection_active": evidence.get("intersection_active"),
        "turn_candidate": evidence.get("turn_candidate"),
        "lane_change_suppression_reason": evidence.get("lane_change_suppression_reason"),
        "final_decision_reason": evidence.get("final_decision_reason"),
        "source_logical_lane_id": evidence.get("source_logical_lane_id"),
        "target_logical_lane_id": evidence.get("target_logical_lane_id"),
    }


def event_field(event: dict[str, Any], camel: str, snake: str, default: Any = None) -> Any:
    return event.get(camel, event.get(snake, default))


def load_prediction_events(
    frame_input_root: Path,
    explorer_event_root: Path | None,
) -> list[tuple[str, int, dict[str, Any]]]:
    if explorer_event_root is not None and explorer_event_root.is_dir():
        rows = []
        for explorer_path in sorted(explorer_event_root.glob("*_animated_odld_explorer.html")):
            recording = explorer_path.name.removesuffix("_animated_odld_explorer.html")
            data = load_explorer_data(explorer_path)
            for event_index, event in enumerate(((data.get("tags") or {}).get("events") or [])):
                if event.get("scenario") in TARGET_LABELS:
                    rows.append((recording, event_index, event))
        return rows

    rows = []
    for rule_path in sorted(frame_input_root.glob("*/recording_rule_events.json")):
        recording = rule_path.parent.name
        payload = load_json(rule_path)
        for event_index, event in enumerate(payload.get("rule_based_events", [])):
            if event.get("scenario") in TARGET_LABELS:
                rows.append((recording, event_index, event))
    return rows


def build_events(
    frame_input_root: Path,
    gt_dir: Path,
    output_dir: Path,
    context_samples: int,
    explorer_event_root: Path | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for recording, event_index, event in load_prediction_events(frame_input_root, explorer_event_root):
        frame_dir = frame_input_root / recording
        frame_paths = sorted(frame_dir.glob("frame_*/frame.json"))
        frames_by_index = {load_json(path).get("frame_index"): path for path in frame_paths}
        sorted_indices = sorted(index for index in frames_by_index if isinstance(index, int))
        gt_path = gt_dir / f"{recording}_frame_gt.json"
        label = event.get("scenario")
        evidence = event.get("evidence") if isinstance(event.get("evidence"), dict) else {}
        strategy_evidence = summarize_recent_strategy_evidence(evidence)
        start_frame = event_field(event, "startFrame", "start_frame", 10**12)
        end_frame = event_field(event, "endFrame", "end_frame", -1)
        event_indices = [
            index
            for index in sorted_indices
            if start_frame <= index <= end_frame
        ]
        context_indices: list[int] = []
        if event_indices:
            start_pos = max(0, sorted_indices.index(event_indices[0]) - context_samples)
            end_pos = min(
                len(sorted_indices),
                sorted_indices.index(event_indices[-1]) + context_samples + 1,
            )
            context_indices = sorted_indices[start_pos:end_pos]
        frame_cards = []
        for index in context_indices:
            frame_path = frames_by_index[index]
            frame = load_json(frame_path)
            frame_cards.append(
                {
                    "frame_index": index,
                    "time_since_start_s": frame.get("time_since_start_s"),
                    "speed_mps": (frame.get("ego") or {}).get("speed_mps"),
                    "inside_event": index in event_indices,
                    "image": rel_image(frame_path, output_dir),
                }
            )
        rows.append(
            {
                "id": f"{recording}:{label}:{start_frame}-{end_frame}:{event_index}",
                "recording_id": recording,
                "label": label,
                "start_frame": start_frame,
                "end_frame": end_frame,
                "start_timestamp_s": event_field(event, "startTime", "start_timestamp_s"),
                "end_timestamp_s": event_field(event, "endTime", "end_timestamp_s"),
                "duration_s": event_field(event, "durationSec", "duration_s"),
                "sampled_frame_count": len(event_indices),
                "gt": existing_gt_votes(gt_path, str(label), event_indices),
                "strategy": STRATEGY_NAME,
                "recent_strategy_evidence": strategy_evidence,
                "evidence": evidence,
                "frames": frame_cards,
            }
        )
    return rows


def review_html(events: list[dict[str, Any]]) -> str:
    serialized = json.dumps(events, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Recent Strategy Lane Change Review</title>
<style>
:root{{--bg:#f4f6f8;--panel:#fff;--text:#172033;--muted:#667085;--border:#d7dee8;--accent:#2458c6;--yes:#157a3c;--no:#b42318;--warn:#9a6700;--unknown:#64748b}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px Arial,sans-serif}}header{{position:relative;background:white;border-bottom:1px solid var(--border);padding:12px 18px}}h1{{font-size:19px;margin:0 0 10px}}button,input,select,textarea{{font:inherit}}button,select,input{{border:1px solid var(--border);border-radius:6px;background:white;color:var(--text);padding:7px 9px}}button{{cursor:pointer}}button.active{{background:var(--accent);border-color:var(--accent);color:white}}.toolbar{{display:flex;gap:8px;flex-wrap:wrap;align-items:center}}.summary{{display:flex;gap:8px;flex-wrap:wrap;margin-top:9px}}.pill{{border:1px solid var(--border);background:#f8fafc;border-radius:999px;padding:5px 9px;color:#334155}}main{{max-width:1560px;margin:auto;padding:14px}}.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(430px,1fr));gap:12px}}.card{{background:var(--panel);border:1px solid var(--border);border-radius:8px;overflow:hidden}}.card.true{{border-color:#95d5a7}}.card.false{{border-color:#efaaa5}}.card.unsure{{border-color:#e2c36b}}.head{{padding:10px;border-bottom:1px solid var(--border)}}.head b{{display:block;overflow-wrap:anywhere}}.badges{{display:flex;gap:5px;flex-wrap:wrap;margin-top:7px}}.badge{{border-radius:999px;padding:3px 7px;font-size:12px;background:#edf2f7;color:#334155}}.badge.yes{{background:#dff6e6;color:var(--yes)}}.badge.no{{background:#fde3e1;color:var(--no)}}.badge.warn{{background:#fff4cc;color:var(--warn)}}.badge.unknown{{background:#e5e7eb;color:var(--unknown)}}.viewer{{background:#10141c;color:white;padding:8px;display:grid;gap:8px}}.screen{{height:380px;display:grid;place-items:center;background:#0d1117;border:1px solid #263244;border-radius:6px}}.screen.event{{border-color:#60a5fa;box-shadow:0 0 0 2px rgba(96,165,250,.18)}}.screen img{{display:block;width:100%;height:100%;object-fit:contain}}.frameMeta{{font-size:12px;color:#dbeafe}}.player{{display:grid;grid-template-columns:auto auto auto 1fr;gap:6px;align-items:center}}.chips{{display:flex;gap:5px;flex-wrap:wrap}}.chip{{font-size:12px;padding:4px 7px;border:1px solid #334155;background:#1f2937;color:#e5e7eb;border-radius:999px}}.chip.event{{border-color:#60a5fa;color:#bfdbfe}}.chip.active{{background:#2563eb;border-color:#2563eb;color:white}}.body{{padding:10px;display:grid;gap:8px}}.actions{{display:flex;gap:7px;flex-wrap:wrap}}.actions button[data-value="true"].active{{background:var(--yes);border-color:var(--yes);color:white}}.actions button[data-value="false"].active{{background:var(--no);border-color:var(--no);color:white}}.actions button[data-value="unsure"].active{{background:var(--warn);border-color:var(--warn);color:white}}textarea{{width:100%;min-height:54px;border:1px solid var(--border);border-radius:6px;padding:7px;resize:vertical}}code{{white-space:pre-wrap;overflow-wrap:anywhere;color:var(--muted);font-size:12px}}details{{border-top:1px solid var(--border);padding-top:7px}}@media(max-width:700px){{.grid{{grid-template-columns:1fr}}.player{{grid-template-columns:auto auto auto}}.chips{{grid-column:1/-1}}}}
</style></head><body>
<header><h1>Recent Strategy Lane Change Review</h1>
<div class="toolbar">
<input id="search" placeholder="recording search">
<select id="label"><option value="all">both labels</option><option value="changing_lane_to_left">left only</option><option value="changing_lane_to_right">right only</option></select>
<select id="status"><option value="all">all decisions</option><option value="unreviewed">unreviewed</option><option value="true">marked true</option><option value="false">marked false</option><option value="unsure">unsure</option></select>
<select id="gt"><option value="all">all GT</option><option value="gt_positive">GT positive</option><option value="gt_negative">GT negative</option><option value="gt_unknown">unknown/missing GT</option></select>
<button id="export">Export review JSON</button>
<input id="importFile" type="file" accept="application/json" style="display:none"><button id="import">Import JSON</button>
<button id="resetMarks">Reset markings</button>
</div><div class="summary" id="summary"></div></header>
<main><div class="grid" id="grid"></div></main>
<script>
const EVENTS={serialized};const storageKey='ms-odd-changing-lane-prediction-review-v1';
let decisions={{}};let framePositions={{}};let playing={{}};let timers={{}};
function restore(){{try{{decisions=JSON.parse(localStorage.getItem(storageKey)||'{{}}')}}catch(e){{decisions={{}}}}}}
function save(){{localStorage.setItem(storageKey,JSON.stringify(decisions));renderSummary()}}
function decision(id){{return decisions[id]||{{value:null,notes:''}}}}
function badge(text,cls=''){{return `<span class="badge ${{cls}}">${{text}}</span>`}}
function gtClass(status){{if(status==='gt_positive')return 'yes';if(status.startsWith('gt_negative'))return 'no';if(status==='missing_gt_file'||status==='gt_unknown')return 'unknown';return 'warn'}}
function strategyBadges(event){{const s=event.recent_strategy_evidence||{{}};const topo=s.topology_class??'unknown';const topoConf=s.topology_confidence==null?'n/a':Number(s.topology_confidence).toFixed(2);const turn=s.turn_candidate??'none';const reason=s.final_decision_reason??'missing';const intersection=s.intersection_active===true?'intersection':(s.intersection_active===false?'non-intersection':'intersection unknown');const present=s.recent_strategy_evidence_present===true;return [badge('recent topology/turn strategy',present?'yes':'warn'),badge(`topology ${{topo}} conf ${{topoConf}}`),badge(intersection,intersection==='intersection'?'warn':''),badge(`turn ${{turn}}`,turn==='none'?'':'warn'),badge(`reason ${{reason}}`)].join('')}}
function eventVisible(event){{const q=document.getElementById('search').value.toLowerCase();const label=document.getElementById('label').value;const status=document.getElementById('status').value;const gt=document.getElementById('gt').value;const d=decision(event.id);if(q&&!event.recording_id.toLowerCase().includes(q))return false;if(label!=='all'&&event.label!==label)return false;if(status==='unreviewed'&&d.value!==null)return false;if(['true','false','unsure'].includes(status)&&d.value!==status)return false;if(gt==='gt_positive'&&event.gt.status!=='gt_positive')return false;if(gt==='gt_negative'&&!event.gt.status.startsWith('gt_negative'))return false;if(gt==='gt_unknown'&&!['missing_gt_file','gt_unknown'].includes(event.gt.status))return false;return true}}
function renderSummary(){{const reviewed=EVENTS.filter(e=>decision(e.id).value==='true'||decision(e.id).value==='false');const correct=reviewed.filter(e=>decision(e.id).value==='true').length;const incorrect=reviewed.filter(e=>decision(e.id).value==='false').length;const unsure=EVENTS.filter(e=>decision(e.id).value==='unsure').length;const acc=reviewed.length?`${{(correct/reviewed.length*100).toFixed(1)}}%`:'n/a';const visible=EVENTS.filter(eventVisible).length;const recent=EVENTS.filter(e=>(e.recent_strategy_evidence||{{}}).recent_strategy_evidence_present===true).length;document.getElementById('summary').innerHTML=[badge('strategy topology/turn-aware'),badge(`${{EVENTS.length}} predicted events`),badge(`${{recent}} with recent evidence`,'yes'),badge(`${{visible}} visible`),badge(`${{reviewed.length}} reviewed`),badge(`${{correct}} true`,'yes'),badge(`${{incorrect}} false`,'no'),badge(`${{unsure}} unsure`,'warn'),badge(`accuracy ${{acc}}`)].join('')}}
function setDecision(id,value){{decisions[id]={{...decision(id),value}};save();renderCards()}}
function setNotes(id,value){{decisions[id]={{...decision(id),notes:value}};save()}}
function frameIndex(event){{const n=event.frames.length;if(!n)return 0;return Math.max(0,Math.min(n-1,framePositions[event.id]??0))}}
function setFrame(eventId,index){{const event=EVENTS.find(item=>item.id===eventId);if(!event)return;framePositions[eventId]=Math.max(0,Math.min(event.frames.length-1,index));updateViewer(event)}}
function stepFrame(eventId,delta){{const event=EVENTS.find(item=>item.id===eventId);if(!event)return;setFrame(eventId,frameIndex(event)+delta)}}
function togglePlay(eventId){{if(playing[eventId]){{playing[eventId]=false;clearInterval(timers[eventId]);timers[eventId]=null;updatePlayButton(eventId);return}}playing[eventId]=true;timers[eventId]=setInterval(()=>{{const event=EVENTS.find(item=>item.id===eventId);if(!event)return;const next=(frameIndex(event)+1)%event.frames.length;setFrame(eventId,next)}},550);updatePlayButton(eventId)}}
function updatePlayButton(eventId){{const button=document.querySelector(`button[data-play="${{CSS.escape(eventId)}}"]`);if(button)button.textContent=playing[eventId]?'Pause':'Play'}}
function updateViewer(event){{const frame=event.frames[frameIndex(event)]||{{}};const screen=document.querySelector(`[data-screen="${{CSS.escape(event.id)}}"]`);const meta=document.querySelector(`[data-meta="${{CSS.escape(event.id)}}"]`);const chips=document.querySelector(`[data-chips="${{CSS.escape(event.id)}}"]`);if(screen){{screen.className='screen'+(frame.inside_event?' event':'');screen.innerHTML=frame.image?`<img src="${{frame.image}}" loading="lazy">`:'missing BEV'}}if(meta)meta.textContent=`frame ${{frame.frame_index??'n/a'}}${{frame.inside_event?' · inside event':' · buffer'}} · ${{frame.time_since_start_s==null?'n/a':Number(frame.time_since_start_s).toFixed(2)}}s · ${{frame.speed_mps==null?'n/a':Number(frame.speed_mps).toFixed(2)}} m/s`;if(chips)for(const chip of chips.querySelectorAll('button'))chip.classList.toggle('active',Number(chip.dataset.framePosition)===frameIndex(event))}}
function viewer(event){{const i=frameIndex(event);const frame=event.frames[i]||{{}};const chips=event.frames.map((frame,index)=>`<button class="chip ${{frame.inside_event?'event':''}} ${{index===i?'active':''}}" data-frame-id="${{event.id}}" data-frame-position="${{index}}">${{frame.frame_index}}</button>`).join('');return `<div class="viewer"><div class="screen ${{frame.inside_event?'event':''}}" data-screen="${{event.id}}">${{frame.image?`<img src="${{frame.image}}" loading="lazy">`:'missing BEV'}}</div><div class="frameMeta" data-meta="${{event.id}}">frame ${{frame.frame_index??'n/a'}}${{frame.inside_event?' · inside event':' · buffer'}} · ${{frame.time_since_start_s==null?'n/a':Number(frame.time_since_start_s).toFixed(2)}}s · ${{frame.speed_mps==null?'n/a':Number(frame.speed_mps).toFixed(2)}} m/s</div><div class="player"><button data-prev="${{event.id}}">Prev</button><button data-play="${{event.id}}">${{playing[event.id]?'Pause':'Play'}}</button><button data-next="${{event.id}}">Next</button><div class="chips" data-chips="${{event.id}}">${{chips}}</div></div></div>`}}
function card(event){{const d=decision(event.id);const cls=d.value||'';return `<article class="card ${{cls}}" data-id="${{event.id}}"><div class="head"><b>${{event.recording_id}}</b><div>${{event.label.replaceAll('_',' ')}} · frames ${{event.start_frame}}-${{event.end_frame}} · ${{event.duration_s==null?'n/a':Number(event.duration_s).toFixed(2)}}s</div><div class="badges">${{badge('predicted','yes')}}${{badge(event.gt.status,gtClass(event.gt.status))}}${{badge(`GT+ ${{event.gt.positive}} / GT- ${{event.gt.negative}} / ? ${{event.gt.unknown}}`)}}</div><div class="badges">${{strategyBadges(event)}}</div></div>${{viewer(event)}}<div class="body"><div class="actions"><button data-id="${{event.id}}" data-value="true" class="${{d.value==='true'?'active':''}}">True detection</button><button data-id="${{event.id}}" data-value="false" class="${{d.value==='false'?'active':''}}">False detection</button><button data-id="${{event.id}}" data-value="unsure" class="${{d.value==='unsure'?'active':''}}">Unsure</button><button data-id="${{event.id}}" data-value="">Clear</button></div><textarea data-id="${{event.id}}" placeholder="notes">${{(d.notes||'').replaceAll('&','&amp;').replaceAll('<','&lt;')}}</textarea><details><summary>Recent strategy evidence</summary><code>${{JSON.stringify(event.recent_strategy_evidence||{{}},null,2)}}</code></details><details><summary>Full evidence</summary><code>${{JSON.stringify(event.evidence||{{}},null,2)}}</code></details></div></article>`}}
function renderCards(){{for(const id of Object.keys(timers)){{clearInterval(timers[id]);timers[id]=null;playing[id]=false}}const rows=EVENTS.filter(eventVisible);document.getElementById('grid').innerHTML=rows.length?rows.map(card).join(''):'<p>No matching events.</p>';for(const button of document.querySelectorAll('button[data-id]'))button.onclick=()=>setDecision(button.dataset.id,button.dataset.value||null);for(const area of document.querySelectorAll('textarea[data-id]'))area.onchange=()=>setNotes(area.dataset.id,area.value);for(const button of document.querySelectorAll('button[data-prev]'))button.onclick=()=>stepFrame(button.dataset.prev,-1);for(const button of document.querySelectorAll('button[data-next]'))button.onclick=()=>stepFrame(button.dataset.next,1);for(const button of document.querySelectorAll('button[data-play]'))button.onclick=()=>togglePlay(button.dataset.play);for(const chip of document.querySelectorAll('button[data-frame-id]'))chip.onclick=()=>setFrame(chip.dataset.frameId,Number(chip.dataset.framePosition))}}
function render(){{renderSummary();renderCards()}}
for(const id of ['search','label','status','gt'])document.getElementById(id).addEventListener('input',render);
document.getElementById('export').onclick=()=>{{const payload={{schema_version:'changing-lane-prediction-review-v1',exported_at:new Date().toISOString(),accuracy_summary:document.getElementById('summary').innerText,decisions}};const blob=new Blob([JSON.stringify(payload,null,2)+'\\n'],{{type:'application/json'}});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='changing_lane_prediction_review.json';a.click();URL.revokeObjectURL(url)}};
document.getElementById('import').onclick=()=>document.getElementById('importFile').click();document.getElementById('importFile').onchange=async e=>{{const loaded=JSON.parse(await e.target.files[0].text());decisions=loaded.decisions||loaded;save();render()}};
document.getElementById('resetMarks').onclick=()=>{{if(!confirm('Clear all saved markings and notes for this lane-change review page?'))return;decisions={{}};localStorage.removeItem(storageKey);render()}};
restore();render();
</script></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame-input-root", type=Path, default=FRAME_INPUTS)
    parser.add_argument("--explorer-event-root", type=Path, default=ODLD_SCENARIO_EXPLORERS)
    parser.add_argument("--gt-dir", type=Path, default=DATA_GT)
    parser.add_argument("--output-dir", type=Path, default=SCENARIO_REVIEW_EXPLORERS / "lane_change_prediction")
    parser.add_argument("--context-samples", type=int, default=1)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    events = build_events(
        args.frame_input_root,
        args.gt_dir,
        args.output_dir,
        max(0, args.context_samples),
        args.explorer_event_root,
    )
    (args.output_dir / "index.html").write_text(review_html(events), encoding="utf-8")
    (args.output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "lane-change-prediction-review-manifest-v1",
                "strategy": STRATEGY_NAME,
                "requires_recent_strategy_evidence": True,
                "frame_input_root": str(args.frame_input_root),
                "event_source": "06_scenario_explorers/odld",
                "event_source_root": str(args.explorer_event_root),
                "gt_dir": str(args.gt_dir),
                "target_labels": list(TARGET_LABELS),
                "event_count": len(events),
                "left_event_count": sum(1 for event in events if event["label"] == "changing_lane_to_left"),
                "right_event_count": sum(1 for event in events if event["label"] == "changing_lane_to_right"),
                "recent_strategy_evidence_count": sum(
                    1
                    for event in events
                    if event["recent_strategy_evidence"]["recent_strategy_evidence_present"]
                ),
                "context_samples_before_after": max(0, args.context_samples),
                "initial_viewer_frame": "first_buffer_frame",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(args.output_dir / "index.html")
    print(f"events {len(events)}")
    print(f"left {sum(1 for event in events if event['label'] == 'changing_lane_to_left')}")
    print(f"right {sum(1 for event in events if event['label'] == 'changing_lane_to_right')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
