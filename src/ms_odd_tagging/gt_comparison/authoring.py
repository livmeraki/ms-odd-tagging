#!/usr/bin/env python3
"""Generate scalable browser GT review pages from sampled frame inputs."""

from __future__ import annotations

import argparse
import html
import json
import math
import os
from pathlib import Path
from typing import Any

from ms_odd_tagging.common.config import DATA_GT, FRAME_GT_AUTHORING
from ms_odd_tagging.gt_comparison.labels import (
    MINIMUM_REVIEW_FRAME_INDEX,
    SCENARIO_GROUPS,
    TAXONOMY,
    build_frame_gt_payload,
    find_frame_files,
    load_json,
)

DEBUG_EVIDENCE_KEYS = (
    "object_track_ids",
    "source_object_ids",
    "object_track_id",
    "object_class",
    "original_class",
    "peak_simultaneous_count",
    "minimum_footprint_distance_m",
    "minimum_distance_m",
    "peak_object_speed_mps",
    "velocity_sources",
    "source_logical_lane_id",
    "target_logical_lane_id",
    "direction",
    "transition_frame",
    "crosswalk_id",
    "crosswalk_ids",
    "stopline_id",
    "stationary_relation",
    "final_relation",
    "association_confidence",
    "pedestrian_track_ids",
    "peak_pedestrian_count",
    "crossing_direction",
    "initial_side",
    "final_side",
    "arc_entry_frame",
    "arc_exit_frame",
    "minimum_path_distance_m",
    "crossing_angle_deg",
    "object_heading_lcs_rad",
    "ego_time_to_intersection_s",
    "object_time_to_intersection_s",
    "time_to_intersection_difference_s",
    "peak_abs_lateral_acceleration_mps2",
    "peak_jerk_mps3",
    "signed_heading_delta_rad",
    "peak_signed_yaw_rate_rad_s",
)


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def compact_event(event: dict[str, Any]) -> dict[str, Any]:
    """Keep reviewer-relevant event evidence without embedding large geometry."""
    evidence = event.get("evidence") if isinstance(event.get("evidence"), dict) else {}
    compact = {key: evidence[key] for key in DEBUG_EVIDENCE_KEYS if key in evidence}
    return {
        "scenario": event.get("scenario"),
        "start_frame": event.get("start_frame"),
        "end_frame": event.get("end_frame"),
        "start_time_s": event.get("start_time_s"),
        "end_time_s": event.get("end_time_s"),
        "evidence": compact,
    }


def compact_object_debug(frame: dict[str, Any], radius_m: float = 30.0) -> list[dict[str, Any]]:
    """Return nearby dynamic-object values useful when checking interaction GT."""
    rows = []
    for obj in frame.get("objects", []):
        if str(obj.get("annotation_type") or "").lower() != "dynamic":
            continue
        position = obj.get("position_ego_m") or {}
        distance = position.get("distance")
        if not _finite(distance) or float(distance) > radius_m:
            continue
        velocity = obj.get("velocity_lcs_mps")
        speed = (
            math.hypot(float(velocity[0]), float(velocity[1]))
            if isinstance(velocity, (list, tuple))
            and len(velocity) >= 2
            and _finite(velocity[0])
            and _finite(velocity[1])
            else None
        )
        rows.append(
            {
                "object_id": str(obj.get("object_id") or ""),
                "class": obj.get("class"),
                "distance_m": round(float(distance), 2),
                "longitudinal_m": position.get("longitudinal"),
                "lateral_m": position.get("lateral"),
                "speed_mps": round(speed, 2) if speed is not None else None,
                "heading_relative_rad": obj.get("heading_relative_rad"),
            }
        )
    return sorted(rows, key=lambda row: row["distance_m"])


def discover_recordings(frame_input_root: Path) -> list[str]:
    """Return recording folders containing at least one sampled frame input."""
    if not frame_input_root.exists():
        raise FileNotFoundError(f"Frame input root does not exist: {frame_input_root}")
    return sorted(
        path.name
        for path in frame_input_root.iterdir()
        if path.is_dir() and any(path.rglob("frame.json"))
    )


def image_uri(
    frame_path: Path,
    bev: dict[str, Any] | None,
    image_base_dir: Path | None = None,
) -> str | None:
    if not isinstance(bev, dict) or not bev.get("path"):
        return None
    image_path = frame_path.parent / str(bev["path"])
    if not image_path.is_file():
        return None
    if image_base_dir is not None:
        return os.path.relpath(image_path.resolve(), image_base_dir.resolve()).replace(
            os.sep,
            "/",
        )
    return image_path.resolve().as_uri()


def build_review_payload(
    frame_input_root: Path,
    recording: str,
    existing_gt_path: Path | None = None,
    image_base_dir: Path | None = None,
) -> dict[str, Any]:
    """Build a compact browser payload for independent sampled frames."""
    gt = build_frame_gt_payload(frame_input_root, recording, existing_gt_path)
    review_frames = []
    for frame_path in find_frame_files(frame_input_root, recording):
        frame = load_json(frame_path)
        reference_path = frame_path.with_name("gt_reference.json")
        derivation = load_json(reference_path) if reference_path.is_file() else {}
        rule_reference = derivation.get("rule_based_reference") or {}
        rule_reference = {
            **rule_reference,
            "active_labels": [
                label
                for label in rule_reference.get("active_labels", [])
                if label in TAXONOMY
            ],
            "active_events": [
                compact_event(event)
                for event in rule_reference.get("active_events", [])
                if isinstance(event, dict) and event.get("scenario") in TAXONOMY
            ],
        }
        frame_id = str(frame.get("frame_id") or frame_path.parent.name)
        gt_frame = gt["frames"][frame_id]
        review_frames.append(
            {
                "frame_id": frame_id,
                "frame_index": gt_frame.get("frame_index"),
                "timestamp_unix_s": gt_frame.get("timestamp_unix_s"),
                "time_since_start_s": gt_frame.get("time_since_start_s"),
                "reference": gt_frame.get("reference") or {},
                "derivation": rule_reference,
                "debug": {
                    "ego": {
                        key: (frame.get("ego") or {}).get(key)
                        for key in (
                            "speed_mps",
                            "acceleration_mps2",
                            "yaw_rate_radps",
                            "heading_lcs_rad",
                        )
                    },
                    "nearby_dynamic_objects": compact_object_debug(frame),
                    "scenario_signals": frame.get("scenario_signals") or {},
                    "ld_summary": (frame.get("ld") or {}).get("summary") or {},
                },
                "image": image_uri(frame_path, frame.get("bev"), image_base_dir),
            }
        )
    return {
        "schema_version": "scenario-frame-gt-review-v1",
        "recording_id": recording,
        "download_filename": f"{recording}_frame_gt.json",
        "taxonomy": TAXONOMY,
        "scenario_groups": SCENARIO_GROUPS,
        "minimum_scored_frame_index": MINIMUM_REVIEW_FRAME_INDEX,
        "gt": gt,
        "review_frames": review_frames,
    }


def reviewer_html(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c")
    title = html.escape(f"Frame GT Review - {payload['recording_id']}")
    scenario_options = "".join(
        f'<option value="{html.escape(label)}">{html.escape(label.replace("_", " "))}</option>'
        for label in TAXONOMY
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
:root{{--bg:#f5f7fa;--panel:#fff;--text:#172033;--muted:#657087;--border:#d8deea;--accent:#2458c6;--yes:#16803c;--no:#b42318;--unknown:#6b7280}}
@media(prefers-color-scheme:dark){{:root{{--bg:#10141c;--panel:#181e29;--text:#edf2f9;--muted:#aab4c5;--border:#354052;--accent:#8fb4ff;--yes:#5bd584;--no:#ff8b82;--unknown:#adb5c3}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px system-ui,sans-serif}}button,input,select,textarea{{font:inherit}}header{{position:sticky;top:0;z-index:4;background:var(--panel);border-bottom:1px solid var(--border);padding:10px 16px}}.top{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}h1{{font-size:18px;margin:0 auto 0 0}}h2{{font-size:15px;margin:12px 0 7px}}button{{border:1px solid var(--border);background:var(--panel);color:var(--text);padding:7px 10px;border-radius:6px;cursor:pointer}}button.primary{{background:var(--accent);color:#fff;border-color:var(--accent)}}button:disabled{{opacity:.45;cursor:not-allowed}}header select,header input{{width:auto;min-width:120px}}#scenarioFilter{{min-width:230px}}main{{max-width:1500px;margin:auto;padding:12px}}.status{{display:flex;gap:14px;flex-wrap:wrap;color:var(--muted);margin:6px 0 10px}}.layout{{display:grid;grid-template-columns:minmax(0,2fr) minmax(390px,1fr);gap:12px}}.panel{{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:11px}}figure{{margin:0}}img{{display:block;width:100%;max-height:72vh;object-fit:contain;background:#0d1117;border-radius:5px}}.missing{{display:grid;place-items:center;min-height:420px;color:var(--muted)}}details.group{{border-top:1px solid var(--border);padding:7px 0}}details.group:first-child{{border-top:0}}summary{{cursor:pointer;font-weight:650}}.labels{{display:grid;grid-template-columns:1fr auto;gap:6px 9px;align-items:center;margin-top:7px}}.label-name.predicted{{color:var(--yes);font-weight:650}}.tri{{display:flex}}.tri button{{border-radius:0;min-width:34px;padding:5px 8px}}.tri button:first-child{{border-radius:5px 0 0 5px}}.tri button:last-child{{border-radius:0 5px 5px 0}}.tri button.active[data-value="true"]{{background:var(--yes);color:#fff}}.tri button.active[data-value="false"]{{background:var(--no);color:#fff}}.tri button.active[data-value="null"]{{background:var(--unknown);color:#fff}}.fields{{display:grid;gap:7px;margin-top:10px}}label span{{display:block;color:var(--muted);margin-bottom:3px}}input,select,textarea{{width:100%;border:1px solid var(--border);border-radius:5px;background:var(--panel);color:var(--text);padding:7px}}textarea{{min-height:62px;resize:vertical}}.actions{{display:flex;gap:7px;flex-wrap:wrap;margin-top:9px}}.hint,.muted{{color:var(--muted);font-size:12px;margin:8px 0 0}}.excluded{{color:var(--no);font-weight:650}}.debug-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:6px}}.debug-item{{border-left:3px solid var(--border);padding:4px 7px}}.debug-item b{{display:block}}.event{{border-top:1px solid var(--border);padding:7px 0}}.event:first-child{{border-top:0}}.event code{{display:block;white-space:pre-wrap;overflow-wrap:anywhere;color:var(--muted)}}table{{width:100%;border-collapse:collapse;margin-top:6px}}th,td{{padding:4px 6px;text-align:left;border-bottom:1px solid var(--border)}}th{{color:var(--muted);font-weight:500}}#importFile{{display:none}}@media(max-width:900px){{.layout{{grid-template-columns:1fr}}img{{max-height:none}}}}
</style></head><body><header><div class="top"><h1>{title}</h1><select id="filter"><option value="all">All frames</option><option value="pending">Needs review</option><option value="complete">Reviewed</option></select><select id="scenarioFilter" aria-label="Scenario filter"><option value="all">All scenarios</option>{scenario_options}</select><input id="jump" type="number" min="0" placeholder="Frame index" aria-label="Jump to frame index"><button id="importButton">Import GT JSON</button><input id="importFile" type="file" accept="application/json"><button id="download" class="primary">Download GT JSON</button></div></header>
<main><div class="status"><b id="position"></b><span id="frameMeta"></span><span id="progress"></span><span id="saveState"></span></div><div class="layout"><section><div class="panel"><figure id="figure"></figure><p class="hint">←/→ navigate · Space mark reviewed + next · F set unknown false · C copy previous. Changes autosave locally.</p></div><div class="panel" style="margin-top:12px"><h2>Frame debug evidence</h2><div id="debug"></div></div></section><aside class="panel"><div id="exclusion"></div><div id="labels"></div><div class="actions"><button id="unknownFalse">Set unknown to false</button><button id="copyPrevious">Copy previous</button></div><div class="fields"><label><span>Review status</span><select id="needsReview"><option value="true">Needs review</option><option value="false">Reviewed</option></select></label><label><span>Confidence</span><select id="confidence"><option value="">Not set</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></label><label><span>Reviewer</span><input id="reviewer"></label><label><span>Notes</span><textarea id="notes"></textarea></label></div><div class="actions"><button id="previous">Previous</button><button id="reviewNext" class="primary">Mark reviewed + next</button><button id="next">Next</button></div></aside></div></main>
<script>
const DATA={serialized};
const storageKey=`ms-odd-frame-gt:${{DATA.recording_id}}`;const groupStateKey=`ms-odd-frame-gt-groups:${{DATA.recording_id}}`;let gt=DATA.gt;let current=0;let visible=[];let groupOpenState={{}};
function restore(){{try{{const saved=localStorage.getItem(storageKey);if(saved){{const loaded=JSON.parse(saved);if(loaded.schema_version===gt.schema_version)gt=loaded}}}}catch(error){{console.warn(error)}}}}
function restoreGroupState(){{try{{groupOpenState=JSON.parse(localStorage.getItem(groupStateKey)||'{{}}')}}catch(error){{console.warn(error);groupOpenState={{}}}}}}
function saveGroupState(){{localStorage.setItem(groupStateKey,JSON.stringify(groupOpenState))}}
function normalize(){{gt.label_fields=[...DATA.taxonomy];gt.formula_filled_label_fields=[...(DATA.gt.formula_filled_label_fields||[])];for(const item of DATA.review_frames){{const baseline=DATA.gt.frames[item.frame_id],saved=gt.frames?.[item.frame_id]||{{}};gt.frames=gt.frames||{{}};gt.frames[item.frame_id]={{...baseline,...saved,labels:{{...baseline.labels,...(saved.labels||{{}})}}}}}}}}
function save(){{localStorage.setItem(storageKey,JSON.stringify(gt));document.getElementById('saveState').textContent='Autosaved';updateProgress()}}
function meta(){{return DATA.review_frames[current]}}
function gtFrame(){{return gt.frames[meta().frame_id]}}
function selectedScenario(){{return document.getElementById('scenarioFilter').value}}
function frameMatchesScenario(item,frame,scenario){{if(scenario==='all')return true;const active=item.derivation.active_labels||[];return active.includes(scenario)||frame.labels?.[scenario]===true}}
function filtered(){{const mode=document.getElementById('filter').value,scenario=selectedScenario();return DATA.review_frames.map((_,i)=>i).filter(i=>{{const item=DATA.review_frames[i],frame=gt.frames[item.frame_id];return (mode==='all'||(mode==='pending')===Boolean(frame.needs_review))&&frameMatchesScenario(item,frame,scenario)}})}}
function move(delta){{visible=filtered();if(!visible.length)return;let pos=visible.indexOf(current);if(pos<0)pos=0;current=visible[Math.max(0,Math.min(visible.length-1,pos+delta))];render()}}
function jumpToFrame(){{const target=Number(document.getElementById('jump').value);if(!Number.isFinite(target))return;let best=0,distance=Infinity;DATA.review_frames.forEach((item,index)=>{{const next=Math.abs(Number(item.frame_index)-target);if(next<distance){{best=index;distance=next}}}});current=best;render()}}
function updateProgress(){{const frames=Object.values(gt.frames);const reviewed=frames.filter(item=>!item.needs_review).length;const known=frames.reduce((sum,item)=>sum+Object.values(item.labels).filter(value=>typeof value==='boolean').length,0);document.getElementById('progress').textContent=`${{reviewed}}/${{frames.length}} frames reviewed · ${{known}}/${{frames.length*DATA.taxonomy.length}} labels set`}}
function setLabel(label,value){{gtFrame().labels[label]=value;save();renderLabels()}}
function renderLabels(){{
  const root=document.getElementById('labels');root.innerHTML='';
  const automatic=new Set(gt.formula_filled_label_fields||[]);
  const predicted=new Set(meta().derivation.active_labels||[]);
  const excluded=Boolean(gtFrame().excluded_from_evaluation);
  const scenario=selectedScenario();
  for(const definition of DATA.scenario_groups){{
    const shownScenarios=scenario==='all'?definition.scenarios:definition.scenarios.filter(label=>label===scenario);
    if(!shownScenarios.length)continue;
    const details=document.createElement('details');details.className='group';
    const groupKey=definition.label;
    details.open=scenario!=='all'||(Object.prototype.hasOwnProperty.call(groupOpenState,groupKey)?Boolean(groupOpenState[groupKey]):definition.implemented!==false);
    details.addEventListener('toggle',()=>{{groupOpenState[groupKey]=details.open;saveGroupState()}});
    const summary=document.createElement('summary');
    summary.textContent=definition.label+(definition.implemented===false?' · unavailable rule support':'');
    if(definition.support==='qwen_vlm_poc')
      summary.textContent=definition.label+' - VLM-assisted; no deterministic rule support';
    else if(definition.support==='manual')
      summary.textContent=definition.label+' - manual review; no automatic support';
    details.appendChild(summary);
    const labels=document.createElement('div');labels.className='labels';
    for(const label of shownScenarios){{
      const name=document.createElement('span');name.className='label-name';
      name.classList.toggle('predicted',predicted.has(label));
      name.textContent=label.replaceAll('_',' ')+(predicted.has(label)?' · predicted':'')+(automatic.has(label)?' · auto':'');
      if(automatic.has(label))name.title='Directly derived; remains editable for reviewer correction';
      labels.appendChild(name);
      const group=document.createElement('div');group.className='tri';group.setAttribute('role','group');group.setAttribute('aria-label',name.textContent);
      for(const [text,value] of [['Y',true],['N',false],['?',null]]){{
        const button=document.createElement('button');button.type='button';button.textContent=text;button.dataset.value=String(value);
        button.disabled=excluded;button.classList.toggle('active',gtFrame().labels[label]===value);
        button.setAttribute('aria-pressed',String(gtFrame().labels[label]===value));button.onclick=()=>setLabel(label,value);group.appendChild(button)
      }}
      labels.appendChild(group)
    }}
    details.appendChild(labels);root.appendChild(details)
  }}
}}
function renderImage(){{const root=document.getElementById('figure');root.innerHTML='';if(!meta().image){{const missing=document.createElement('div');missing.className='missing';missing.textContent='Missing same-frame BEV';root.appendChild(missing);return}}const image=document.createElement('img');image.src=meta().image;image.alt=`BEV for frame ${{meta().frame_index}}`;root.appendChild(image)}}
function valueText(value,unit=''){{return value==null||Number.isNaN(Number(value))?'n/a':`${{Number(value).toFixed(2)}}${{unit}}`}}
function renderDebug(){{
  const root=document.getElementById('debug'),item=meta(),debug=item.debug||{{}},ego=debug.ego||{{}},lane=item.derivation.lane_tracker||{{}};
  root.innerHTML='';
  const grid=document.createElement('div');grid.className='debug-grid';
  const facts=[
    ['Ego speed',valueText(ego.speed_mps,' m/s')],
    ['Acceleration',valueText(ego.acceleration_mps2,' m/s²')],
    ['Yaw rate',valueText(ego.yaw_rate_radps,' rad/s')],
    ['Heading',valueText(ego.heading_lcs_rad,' rad')],
    ['Lane state',lane.state||'n/a'],
    ['Ego lane',lane.ego_lane?.logical_lane_id||'n/a'],
    ['Lead',lane.lead?`${{lane.lead.class||'object'}} #${{lane.lead.object_id||'n/a'}}`:'none'],
  ];
  for(const [label,value] of facts){{const cell=document.createElement('div');cell.className='debug-item';const b=document.createElement('b');b.textContent=label;cell.append(b,document.createTextNode(value));grid.appendChild(cell)}}root.appendChild(grid);
  const events=item.derivation.active_events||[];const eventTitle=document.createElement('h2');eventTitle.textContent='Active rule events';root.appendChild(eventTitle);
  if(!events.length){{const empty=document.createElement('p');empty.className='muted';empty.textContent='No rule event is active at this frame.';root.appendChild(empty)}}
  for(const event of events){{const row=document.createElement('div');row.className='event';const b=document.createElement('b');b.textContent=`${{event.scenario}} · frames ${{event.start_frame}}–${{event.end_frame}}`;const evidence=document.createElement('code');evidence.textContent=JSON.stringify(event.evidence||{{}},null,2);row.append(b,evidence);root.appendChild(row)}}
  const objects=debug.nearby_dynamic_objects||[];const objectTitle=document.createElement('h2');objectTitle.textContent=`Dynamic objects within 30 m (${{objects.length}})`;root.appendChild(objectTitle);
  if(objects.length){{const table=document.createElement('table');table.innerHTML='<thead><tr><th>Object</th><th>Distance</th><th>Long / lat</th><th>Speed</th><th>Rel. heading</th></tr></thead>';const body=document.createElement('tbody');for(const obj of objects){{const row=document.createElement('tr');for(const text of [`${{obj.class||'object'}} #${{obj.object_id}}`,valueText(obj.distance_m,' m'),`${{valueText(obj.longitudinal_m,' m')}} / ${{valueText(obj.lateral_m,' m')}}`,valueText(obj.speed_mps,' m/s'),valueText(obj.heading_relative_rad,' rad')]){{const cell=document.createElement('td');cell.textContent=text;row.appendChild(cell)}}body.appendChild(row)}}table.appendChild(body);root.appendChild(table)}}else{{const empty=document.createElement('p');empty.className='muted';empty.textContent='No dynamic object is inside the configured 30 m proximity region.';root.appendChild(empty)}}
}}
function render(){{visible=filtered();if(!visible.length){{document.getElementById('position').textContent='No frames match filter';return}}if(!visible.includes(current))current=visible[0];const item=meta(),frame=gtFrame(),speed=item.reference.speed_mps,active=item.derivation.active_labels||[],excluded=Boolean(frame.excluded_from_evaluation);document.getElementById('position').textContent=`Frame ${{current+1}}/${{DATA.review_frames.length}}`;document.getElementById('frameMeta').textContent=`source frame ${{item.frame_index}} · ${{Number(item.time_since_start_s).toFixed(3)}} s · speed ${{speed==null?'n/a':Number(speed).toFixed(3)}} m/s · predicted: ${{active.length?active.join(', '):'none'}}`;document.getElementById('exclusion').innerHTML=excluded?`<p class="excluded">Excluded from scoring: source frames below ${{DATA.minimum_scored_frame_index}} are unreliable.</p>`:'';document.getElementById('jump').value=item.frame_index;renderImage();renderDebug();renderLabels();document.getElementById('needsReview').value=String(Boolean(frame.needs_review));document.getElementById('confidence').value=frame.confidence??'';document.getElementById('reviewer').value=frame.reviewer??'';document.getElementById('notes').value=frame.notes??'';for(const id of ['needsReview','confidence','reviewer','notes','reviewNext','unknownFalse','copyPrevious'])document.getElementById(id).disabled=excluded;document.getElementById('previous').disabled=current===visible[0];document.getElementById('next').disabled=current===visible[visible.length-1];updateProgress()}}
for(const id of ['needsReview','confidence','reviewer','notes'])document.getElementById(id).addEventListener('change',event=>{{const key={{needsReview:'needs_review',confidence:'confidence',reviewer:'reviewer',notes:'notes'}}[id];gtFrame()[key]=id==='needsReview'?event.target.value==='true':event.target.value||'';if(id==='needsReview'&&!gtFrame().needs_review)gtFrame().reviewed_at=new Date().toISOString();save()}});
document.getElementById('previous').onclick=()=>move(-1);document.getElementById('next').onclick=()=>move(1);document.getElementById('reviewNext').onclick=()=>{{gtFrame().needs_review=false;gtFrame().reviewed_at=new Date().toISOString();save();move(1)}};document.getElementById('unknownFalse').onclick=()=>{{const scenario=selectedScenario(),labels=scenario==='all'?DATA.taxonomy:[scenario];for(const label of labels)if(gtFrame().labels[label]===null)gtFrame().labels[label]=false;save();renderLabels()}};document.getElementById('copyPrevious').onclick=()=>{{if(current>0){{const scenario=selectedScenario();if(scenario==='all')gtFrame().labels={{...gt.frames[DATA.review_frames[current-1].frame_id].labels}};else gtFrame().labels[scenario]=gt.frames[DATA.review_frames[current-1].frame_id].labels?.[scenario]??null}}save();renderLabels()}};document.getElementById('filter').onchange=render;document.getElementById('scenarioFilter').onchange=render;document.getElementById('jump').onchange=jumpToFrame;
document.getElementById('download').onclick=()=>{{const blob=new Blob([JSON.stringify(gt,null,2)+'\\n'],{{type:'application/json'}}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=DATA.download_filename;a.click();URL.revokeObjectURL(url)}};
document.getElementById('importButton').onclick=()=>document.getElementById('importFile').click();document.getElementById('importFile').onchange=async event=>{{const loaded=JSON.parse(await event.target.files[0].text());if(loaded.recording_id!==DATA.recording_id||loaded.schema_version!==gt.schema_version){{alert('Recording or frame GT schema does not match');return}}gt=loaded;save();render()}};
document.addEventListener('keydown',event=>{{if(['INPUT','TEXTAREA','SELECT'].includes(event.target.tagName))return;if(event.key==='ArrowLeft')move(-1);if(event.key==='ArrowRight')move(1);if(event.key===' '){{event.preventDefault();document.getElementById('reviewNext').click()}}if(event.key.toLowerCase()==='f')document.getElementById('unknownFalse').click();if(event.key.toLowerCase()==='c')document.getElementById('copyPrevious').click()}});restore();restoreGroupState();normalize();render();
</script></body></html>"""


def write_reviewer(
    frame_input_root: Path,
    recording: str,
    output_path: Path,
    existing_gt_path: Path | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_review_payload(
        frame_input_root,
        recording,
        existing_gt_path,
        output_path.parent,
    )
    output_path.write_text(reviewer_html(payload), encoding="utf-8")
    return output_path


def write_index(output_root: Path, rows: list[dict[str, Any]]) -> Path:
    cards = "\n".join(
        f'<li><a href="{html.escape(row["file"])}">{html.escape(row["recording"])}</a><span>{row["frames"]} sampled frames</span></li>'
        for row in rows
    )
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Frame GT Review</title><style>body{{font:15px system-ui,sans-serif;max-width:900px;margin:auto;padding:24px}}ul{{list-style:none;padding:0}}li{{display:flex;justify-content:space-between;padding:12px;border-bottom:1px solid #aaa}}a{{font-weight:600}}</style></head><body><h1>Frame ground-truth review</h1><ul>{cards}</ul></body></html>"""
    path = output_root / "index.html"
    path.write_text(page, encoding="utf-8")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate efficient sampled-frame GT review pages.")
    parser.add_argument("recordings", nargs="*")
    parser.add_argument("--frame-input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=FRAME_GT_AUTHORING)
    parser.add_argument("--gt-root", type=Path, default=DATA_GT, help="Existing frame GT JSON directory used to prefill reviews.")
    parser.add_argument("--all", action="store_true", help="Generate reviewers for every recording under the frame-input root.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    recordings = discover_recordings(args.frame_input_root) if args.all else args.recordings
    if not recordings:
        raise SystemExit("Provide recording IDs or use --all")
    args.output_root.mkdir(parents=True, exist_ok=True)
    rows = []
    for recording in recordings:
        gt_path = args.gt_root / f"{recording}_frame_gt.json"
        output_path = args.output_root / f"{recording}_frame_gt_review.html"
        payload = build_review_payload(
            args.frame_input_root,
            recording,
            gt_path if gt_path.exists() else None,
            output_path.parent,
        )
        output_path.write_text(reviewer_html(payload), encoding="utf-8")
        rows.append({"recording": recording, "file": output_path.name, "frames": len(payload["review_frames"])})
        print(f"Wrote {output_path} ({len(payload['review_frames'])} sampled frames)")
    index = write_index(args.output_root, rows)
    print(f"Wrote {index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
