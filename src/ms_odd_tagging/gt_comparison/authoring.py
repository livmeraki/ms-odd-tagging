#!/usr/bin/env python3
"""Generate scalable browser GT review pages from sampled frame inputs."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

from ms_odd_tagging.common.config import DATA_GT, FRAME_GT_AUTHORING
from ms_odd_tagging.gt_comparison.labels import (
    TAXONOMY,
    build_frame_gt_payload,
    find_frame_files,
    load_json,
)


def discover_recordings(frame_input_root: Path) -> list[str]:
    """Return recording folders containing at least one sampled frame input."""
    if not frame_input_root.exists():
        raise FileNotFoundError(f"Frame input root does not exist: {frame_input_root}")
    return sorted(
        path.name
        for path in frame_input_root.iterdir()
        if path.is_dir() and any(path.rglob("frame.json"))
    )


def image_uri(frame_path: Path, bev: dict[str, Any] | None) -> str | None:
    if not isinstance(bev, dict) or not bev.get("path"):
        return None
    image_path = frame_path.parent / str(bev["path"])
    return image_path.resolve().as_uri() if image_path.is_file() else None


def build_review_payload(
    frame_input_root: Path,
    recording: str,
    existing_gt_path: Path | None = None,
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
                "image": image_uri(frame_path, frame.get("bev")),
            }
        )
    return {
        "schema_version": "scenario-frame-gt-review-v1",
        "recording_id": recording,
        "download_filename": f"{recording}_frame_gt.json",
        "taxonomy": TAXONOMY,
        "gt": gt,
        "review_frames": review_frames,
    }


def reviewer_html(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c")
    title = html.escape(f"Frame GT Review - {payload['recording_id']}")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
:root{{--bg:#f5f7fa;--panel:#fff;--text:#172033;--muted:#657087;--border:#d8deea;--accent:#2458c6;--yes:#16803c;--no:#b42318;--unknown:#6b7280}}
@media(prefers-color-scheme:dark){{:root{{--bg:#10141c;--panel:#181e29;--text:#edf2f9;--muted:#aab4c5;--border:#354052;--accent:#8fb4ff;--yes:#5bd584;--no:#ff8b82;--unknown:#adb5c3}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px system-ui,sans-serif}}button,input,select,textarea{{font:inherit}}header{{position:sticky;top:0;z-index:4;background:var(--panel);border-bottom:1px solid var(--border);padding:10px 16px}}.top{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}h1{{font-size:18px;margin:0 auto 0 0}}button{{border:1px solid var(--border);background:var(--panel);color:var(--text);padding:7px 10px;border-radius:6px;cursor:pointer}}button.primary{{background:var(--accent);color:#fff;border-color:var(--accent)}}button:disabled{{opacity:.45;cursor:not-allowed}}header select,header input{{width:auto;min-width:120px}}main{{max-width:1400px;margin:auto;padding:12px}}.status{{display:flex;gap:14px;flex-wrap:wrap;color:var(--muted);margin:6px 0 10px}}.layout{{display:grid;grid-template-columns:minmax(0,2fr) minmax(340px,1fr);gap:12px}}.panel{{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:11px}}figure{{margin:0}}img{{display:block;width:100%;max-height:76vh;object-fit:contain;background:#0d1117;border-radius:5px}}.missing{{display:grid;place-items:center;min-height:420px;color:var(--muted)}}.labels{{display:grid;grid-template-columns:1fr auto;gap:6px 9px;align-items:center}}.tri{{display:flex}}.tri button{{border-radius:0;min-width:34px;padding:5px 8px}}.tri button:first-child{{border-radius:5px 0 0 5px}}.tri button:last-child{{border-radius:0 5px 5px 0}}.tri button.active[data-value="true"]{{background:var(--yes);color:#fff}}.tri button.active[data-value="false"]{{background:var(--no);color:#fff}}.tri button.active[data-value="null"]{{background:var(--unknown);color:#fff}}.fields{{display:grid;gap:7px;margin-top:10px}}label span{{display:block;color:var(--muted);margin-bottom:3px}}input,select,textarea{{width:100%;border:1px solid var(--border);border-radius:5px;background:var(--panel);color:var(--text);padding:7px}}textarea{{min-height:62px;resize:vertical}}.actions{{display:flex;gap:7px;flex-wrap:wrap;margin-top:9px}}.hint{{color:var(--muted);font-size:12px;margin:8px 0 0}}#importFile{{display:none}}@media(max-width:900px){{.layout{{grid-template-columns:1fr}}img{{max-height:none}}}}
</style></head><body><header><div class="top"><h1>{title}</h1><select id="filter"><option value="all">All frames</option><option value="pending">Needs review</option><option value="complete">Reviewed</option></select><input id="jump" type="number" min="0" placeholder="Frame index" aria-label="Jump to frame index"><button id="importButton">Import GT JSON</button><input id="importFile" type="file" accept="application/json"><button id="download" class="primary">Download GT JSON</button></div></header>
<main><div class="status"><b id="position"></b><span id="frameMeta"></span><span id="progress"></span><span id="saveState"></span></div><div class="layout"><section class="panel"><figure id="figure"></figure><p class="hint">←/→ navigate · Space mark reviewed + next · F set unknown false · C copy previous. Changes autosave locally.</p></section><aside class="panel"><div class="labels" id="labels"></div><div class="actions"><button id="unknownFalse">Set unknown to false</button><button id="copyPrevious">Copy previous</button></div><div class="fields"><label><span>Review status</span><select id="needsReview"><option value="true">Needs review</option><option value="false">Reviewed</option></select></label><label><span>Confidence</span><select id="confidence"><option value="">Not set</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></label><label><span>Reviewer</span><input id="reviewer"></label><label><span>Notes</span><textarea id="notes"></textarea></label></div><div class="actions"><button id="previous">Previous</button><button id="reviewNext" class="primary">Mark reviewed + next</button><button id="next">Next</button></div></aside></div></main>
<script>
const DATA={serialized};
const storageKey=`ms-odd-frame-gt:${{DATA.recording_id}}`;let gt=DATA.gt;let current=0;let visible=[];
function restore(){{try{{const saved=localStorage.getItem(storageKey);if(saved){{const loaded=JSON.parse(saved);if(loaded.schema_version===gt.schema_version)gt=loaded}}}}catch(error){{console.warn(error)}}}}
function normalize(){{gt.label_fields=[...DATA.taxonomy];gt.formula_filled_label_fields=[...(DATA.gt.formula_filled_label_fields||[])];for(const item of DATA.review_frames){{const baseline=DATA.gt.frames[item.frame_id],saved=gt.frames?.[item.frame_id]||{{}};gt.frames=gt.frames||{{}};gt.frames[item.frame_id]={{...baseline,...saved,labels:{{...baseline.labels,...(saved.labels||{{}})}}}}}}}}
function save(){{localStorage.setItem(storageKey,JSON.stringify(gt));document.getElementById('saveState').textContent='Autosaved';updateProgress()}}
function meta(){{return DATA.review_frames[current]}}
function gtFrame(){{return gt.frames[meta().frame_id]}}
function filtered(){{const mode=document.getElementById('filter').value;return DATA.review_frames.map((_,i)=>i).filter(i=>mode==='all'||(mode==='pending')===Boolean(gt.frames[DATA.review_frames[i].frame_id].needs_review))}}
function move(delta){{visible=filtered();if(!visible.length)return;let pos=visible.indexOf(current);if(pos<0)pos=0;current=visible[Math.max(0,Math.min(visible.length-1,pos+delta))];render()}}
function jumpToFrame(){{const target=Number(document.getElementById('jump').value);if(!Number.isFinite(target))return;let best=0,distance=Infinity;DATA.review_frames.forEach((item,index)=>{{const next=Math.abs(Number(item.frame_index)-target);if(next<distance){{best=index;distance=next}}}});current=best;render()}}
function updateProgress(){{const frames=Object.values(gt.frames);const reviewed=frames.filter(item=>!item.needs_review).length;const known=frames.reduce((sum,item)=>sum+Object.values(item.labels).filter(value=>typeof value==='boolean').length,0);document.getElementById('progress').textContent=`${{reviewed}}/${{frames.length}} frames reviewed · ${{known}}/${{frames.length*DATA.taxonomy.length}} labels set`}}
function setLabel(label,value){{gtFrame().labels[label]=value;save();renderLabels()}}
function renderLabels(){{const root=document.getElementById('labels');root.innerHTML='';const automatic=new Set(gt.formula_filled_label_fields||[]);for(const label of DATA.taxonomy){{const name=document.createElement('span');name.textContent=label.replaceAll('_',' ')+(automatic.has(label)?' · auto':'');if(automatic.has(label))name.title='Directly derived; remains editable for reviewer correction';root.appendChild(name);const group=document.createElement('div');group.className='tri';group.setAttribute('role','group');group.setAttribute('aria-label',name.textContent);for(const [text,value] of [['Y',true],['N',false],['?',null]]){{const button=document.createElement('button');button.type='button';button.textContent=text;button.dataset.value=String(value);button.classList.toggle('active',gtFrame().labels[label]===value);button.setAttribute('aria-pressed',String(gtFrame().labels[label]===value));button.onclick=()=>setLabel(label,value);group.appendChild(button)}}root.appendChild(group)}}}}
function renderImage(){{const root=document.getElementById('figure');root.innerHTML='';if(!meta().image){{const missing=document.createElement('div');missing.className='missing';missing.textContent='Missing same-frame BEV';root.appendChild(missing);return}}const image=document.createElement('img');image.src=meta().image;image.alt=`BEV for frame ${{meta().frame_index}}`;root.appendChild(image)}}
function render(){{visible=filtered();if(!visible.length){{document.getElementById('position').textContent='No frames match filter';return}}if(!visible.includes(current))current=visible[0];const item=meta(),frame=gtFrame(),speed=item.reference.speed_mps,active=item.derivation.active_labels||[];document.getElementById('position').textContent=`Frame ${{current+1}}/${{DATA.review_frames.length}}`;document.getElementById('frameMeta').textContent=`source frame ${{item.frame_index}} · ${{Number(item.time_since_start_s).toFixed(3)}} s · speed ${{speed==null?'n/a':Number(speed).toFixed(3)}} m/s · auto active: ${{active.length?active.join(', '):'none'}}`;document.getElementById('jump').value=item.frame_index;renderImage();renderLabels();document.getElementById('needsReview').value=String(Boolean(frame.needs_review));document.getElementById('confidence').value=frame.confidence??'';document.getElementById('reviewer').value=frame.reviewer??'';document.getElementById('notes').value=frame.notes??'';document.getElementById('previous').disabled=current===visible[0];document.getElementById('next').disabled=current===visible[visible.length-1];updateProgress()}}
for(const id of ['needsReview','confidence','reviewer','notes'])document.getElementById(id).addEventListener('change',event=>{{const key={{needsReview:'needs_review',confidence:'confidence',reviewer:'reviewer',notes:'notes'}}[id];gtFrame()[key]=id==='needsReview'?event.target.value==='true':event.target.value||'';if(id==='needsReview'&&!gtFrame().needs_review)gtFrame().reviewed_at=new Date().toISOString();save()}});
document.getElementById('previous').onclick=()=>move(-1);document.getElementById('next').onclick=()=>move(1);document.getElementById('reviewNext').onclick=()=>{{gtFrame().needs_review=false;gtFrame().reviewed_at=new Date().toISOString();save();move(1)}};document.getElementById('unknownFalse').onclick=()=>{{for(const label of DATA.taxonomy)if(gtFrame().labels[label]===null)gtFrame().labels[label]=false;save();renderLabels()}};document.getElementById('copyPrevious').onclick=()=>{{if(current>0)gtFrame().labels={{...gt.frames[DATA.review_frames[current-1].frame_id].labels}};save();renderLabels()}};document.getElementById('filter').onchange=render;document.getElementById('jump').onchange=jumpToFrame;
document.getElementById('download').onclick=()=>{{const blob=new Blob([JSON.stringify(gt,null,2)+'\\n'],{{type:'application/json'}}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=DATA.download_filename;a.click();URL.revokeObjectURL(url)}};
document.getElementById('importButton').onclick=()=>document.getElementById('importFile').click();document.getElementById('importFile').onchange=async event=>{{const loaded=JSON.parse(await event.target.files[0].text());if(loaded.recording_id!==DATA.recording_id||loaded.schema_version!==gt.schema_version){{alert('Recording or frame GT schema does not match');return}}gt=loaded;save();render()}};
document.addEventListener('keydown',event=>{{if(['INPUT','TEXTAREA','SELECT'].includes(event.target.tagName))return;if(event.key==='ArrowLeft')move(-1);if(event.key==='ArrowRight')move(1);if(event.key===' '){{event.preventDefault();document.getElementById('reviewNext').click()}}if(event.key.toLowerCase()==='f')document.getElementById('unknownFalse').click();if(event.key.toLowerCase()==='c')document.getElementById('copyPrevious').click()}});restore();normalize();render();
</script></body></html>"""


def write_reviewer(
    frame_input_root: Path,
    recording: str,
    output_path: Path,
    existing_gt_path: Path | None = None,
) -> Path:
    payload = build_review_payload(frame_input_root, recording, existing_gt_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
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
        payload = build_review_payload(args.frame_input_root, recording, gt_path if gt_path.exists() else None)
        output_path.write_text(reviewer_html(payload), encoding="utf-8")
        rows.append({"recording": recording, "file": output_path.name, "frames": len(payload["review_frames"])})
        print(f"Wrote {output_path} ({len(payload['review_frames'])} sampled frames)")
    index = write_index(args.output_root, rows)
    print(f"Wrote {index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
