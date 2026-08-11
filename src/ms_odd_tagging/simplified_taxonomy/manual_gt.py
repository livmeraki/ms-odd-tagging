from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

INTERACTION_TAGS = [
    "waiting_for_pedestrian_to_cross",
    "crossed_by_vehicle",
    "near_multiple_vehicles",
    "accelerating_at_crosswalk",
    "stationary_at_crosswalk",
    "stopping_at_crosswalk",
    "near_long_vehicle",
    "near_multiple_pedestrians",
    "near_pedestrian_on_crosswalk",
]

SCALAR_FIELDS = {
    "ego_motion.state": ["stationary", "moving", "starting", "stopping", "unknown"],
    "ego_motion.speed_band": ["low", "medium", "high", "unknown"],
    "ego_maneuver.type": ["lane_keeping", "lane_change", "turn", "u_turn", "unknown"],
    "ego_maneuver.direction": ["left", "right", "straight", None],
    "traffic_relation.lead": ["present", "absent", "unknown"],
    "traffic_relation.trail": ["present", "absent", "unknown"],
    "road_context.intersection": ["yes", "no", "unknown"],
    "road_context.traffic_light_intersection": ["yes", "no", "unknown"],
    "road_context.traffic_light_relevant": ["yes", "no", "unknown"],
    "road_context.on_stopline_crosswalk": ["yes", "no", "unknown"],
}


def _frames(document: Any) -> list[dict[str, Any]]:
    if isinstance(document, list):
        return [x for x in document if isinstance(x, dict)]
    if isinstance(document, dict):
        for key in ("frames", "frame_tags", "results"):
            value = document.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
        return [document]
    raise ValueError("prediction JSON must be an object or list")


def _frame_index(frame: dict[str, Any], fallback: int) -> int:
    for key in ("frame_index", "frameIndex", "frame_id", "index"):
        value = frame.get(key)
        if isinstance(value, int):
            return value
    return fallback


def _simplified(frame: dict[str, Any]) -> dict[str, Any]:
    value = frame.get("simplified_tags")
    if isinstance(value, dict):
        return value
    required = {"ego_motion", "ego_maneuver", "traffic_relation", "road_context"}
    if required.issubset(frame):
        return {k: frame.get(k) for k in (*required, "interaction_tags")}
    return {}


def _get_path(data: dict[str, Any], path: str) -> Any:
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _recording_id(document: Any, prediction_path: Path) -> str:
    if isinstance(document, dict):
        recording = document.get("recording_id")
        if isinstance(recording, str) and recording:
            return recording
    return prediction_path.stem


def _bev_uri(bev_root: Path | None, recording: str, frame_index: int) -> str | None:
    if bev_root is None:
        return None
    path = (bev_root / recording / f"frame_{frame_index:06d}" / "bev_revised.png").resolve()
    return path.as_uri()


def build_review_rows(
    document: Any,
    *,
    source_hz: float = 10.0,
    sample_hz: float = 1.0,
    recording: str = "",
    bev_root: Path | None = None,
) -> list[dict[str, Any]]:
    frames = _frames(document)
    if source_hz <= 0 or sample_hz <= 0:
        raise ValueError("source_hz and sample_hz must be positive")
    step = max(1, round(source_hz / sample_hz))
    rows: list[dict[str, Any]] = []
    for pos, frame in enumerate(frames):
        idx = _frame_index(frame, pos)
        if idx % step != 0:
            continue
        rows.append(
            {
                "frame_index": idx,
                "timestamp": frame.get("timestamp"),
                "prediction": _simplified(frame),
                "bev_uri": _bev_uri(bev_root, recording, idx),
                "gt": None,
                "reviewed": False,
            }
        )
    return rows


def _html(rows: list[dict[str, Any]], recording: str, sample_hz: float) -> str:
    payload = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    interactions = json.dumps(INTERACTION_TAGS)
    return f'''<!doctype html>
<html><head><meta charset="utf-8"><title>Simplified Manual GT</title>
<style>
body{{font-family:Arial,sans-serif;margin:0;background:#111827;color:#e5e7eb}}header{{position:sticky;top:0;background:#0f172a;padding:12px 18px;z-index:4;border-bottom:1px solid #334155}}main{{display:grid;grid-template-columns:minmax(420px,1.15fr) minmax(460px,.85fr);gap:14px;padding:14px}}.card{{background:#1f2937;border:1px solid #374151;border-radius:10px;padding:14px}}h3{{margin:4px 0 9px}}button{{padding:8px 11px;margin:3px;border:1px solid #64748b;border-radius:7px;background:#334155;color:white;cursor:pointer}}button.active{{background:#2563eb;border-color:#60a5fa}}button.pred{{outline:2px solid #f59e0b}}button:disabled{{opacity:.35;cursor:not-allowed}}.group{{margin-bottom:13px;padding:7px;border:1px solid transparent;border-radius:8px}}.group.focused{{border-color:#38bdf8;background:#172033}}.hint{{color:#94a3b8;font-size:12px}}.shortcut{{font-family:monospace;color:#7dd3fc;font-size:11px}}#bev{{width:100%;display:flex;align-items:center;justify-content:center;background:#0b1020;border-radius:8px;color:#64748b;overflow:hidden;position:relative}}#bev img{{width:100%;height:auto;object-fit:contain;display:none}}#bevMissing{{min-height:240px;display:flex;align-items:center;justify-content:center;padding:18px;text-align:center}}#progress{{font-weight:bold}}.interaction label{{display:block;padding:4px;cursor:pointer}}.toolbar{{display:flex;gap:8px;flex-wrap:wrap}}.predbox{{white-space:pre-wrap;font-family:monospace;font-size:12px;max-height:260px;overflow:auto;background:#111827;padding:9px;border-radius:7px}}#shortcutHelp{{margin-top:5px;color:#cbd5e1;font-size:12px}}@media(max-width:1000px){{main{{grid-template-columns:1fr}}}}
</style></head><body>
<header><span id="progress"></span> &nbsp; {recording} &nbsp; <span class="hint">manual GT @ {sample_hz:g} fps · orange outline = prediction</span><div id="shortcutHelp">Tab / Shift+Tab = select field · 1–5 = choose value · Space = save+next · Enter = save · ←/→ = frame · interaction group: 1–9 toggles tags</div></header>
<main><section class="card"><div id="bev"><img id="bevImg" alt="revised BEV"><div id="bevMissing">Loading BEV…</div></div><div class="hint" id="bevPath"></div><h3>Prediction</h3><div id="pred" class="predbox"></div></section>
<section class="card"><div id="form"></div><div class="toolbar"><button onclick="prev()">← Previous</button><button onclick="save(false)">Save</button><button onclick="save(true)">Save + Next →</button><button onclick="exportGT()">Export GT JSON</button></div></section></main>
<script>
const initialRows={payload}; const interactionTags={interactions};
const key='simplified-gt-v3:{recording}'; let rows=JSON.parse(localStorage.getItem(key)||'null')||initialRows; let i=0;
const defs={json.dumps(SCALAR_FIELDS)}; const scalarPaths=Object.keys(defs); const groupNames=[...scalarPaths,'interaction_tags']; let activeGroup=0;
function clone(x){{return JSON.parse(JSON.stringify(x||{{}}));}}
function ensureGT(row){{if(!row.gt) row.gt=clone(row.prediction); row.gt.ego_motion ||= {{state:'unknown',speed_band:'unknown'}}; row.gt.ego_maneuver ||= {{type:'unknown',direction:null}}; row.gt.traffic_relation ||= {{lead:'unknown',trail:'unknown'}}; row.gt.road_context ||= {{intersection:'unknown',traffic_light_intersection:'unknown',traffic_light_relevant:'unknown',on_stopline_crosswalk:'unknown'}}; row.gt.interaction_tags ||= []; if(row.gt.ego_motion.state==='stationary')row.gt.ego_motion.speed_band=null;}}
function get(obj,path){{return path.split('.').reduce((a,k)=>a&&a[k],obj);}} function set(obj,path,v){{let p=path.split('.'),a=obj; for(let j=0;j<p.length-1;j++){{a[p[j]] ||= {{}};a=a[p[j]];}} a[p[p.length-1]]=v;}}
function label(path){{return path.replaceAll('_',' ').replace('.', ' / ');}}
function setActiveGroup(index){{activeGroup=(index+groupNames.length)%groupNames.length;render();}}
function cycleGroup(delta){{let next=activeGroup; do{{next=(next+delta+groupNames.length)%groupNames.length;}}while(groupNames[next]==='ego_motion.speed_band'&&rows[i].gt?.ego_motion?.state==='stationary');activeGroup=next;render();}}
function renderBEV(r){{const img=document.getElementById('bevImg'), missing=document.getElementById('bevMissing'), path=document.getElementById('bevPath'); img.style.display='none'; missing.style.display='flex'; missing.textContent=`BEV unavailable for frame ${{r.frame_index}}`; path.textContent=r.bev_uri||'No BEV root configured'; if(!r.bev_uri)return; img.onload=()=>{{img.style.display='block';missing.style.display='none';}}; img.onerror=()=>{{img.style.display='none';missing.style.display='flex';missing.textContent=`BEV not generated yet for frame ${{r.frame_index}}`;}}; img.src=r.bev_uri+'?frame='+r.frame_index;}}
function render(){{let r=rows[i]; ensureGT(r); document.getElementById('progress').textContent=`${{i+1}} / ${{rows.length}} · frame ${{r.frame_index}} · ${{r.reviewed?'REVIEWED':'UNREVIEWED'}} · field: ${{label(groupNames[activeGroup])}}`;renderBEV(r);document.getElementById('pred').textContent=JSON.stringify(r.prediction||{{}},null,2);let html=''; scalarPaths.forEach((path,gidx)=>{{const values=defs[path], focused=gidx===activeGroup?' focused':'', disabled=path==='ego_motion.speed_band'&&r.gt.ego_motion.state==='stationary';html+=`<div class="group${{focused}}" onclick="setActiveGroup(${{gidx}})"><h3>${{label(path)}} ${{disabled?'<span class="hint">N/A while stationary</span>':''}}</h3>`; values.forEach((v,vidx)=>{{let val=v===null?null:v, cur=get(r.gt,path), pred=get(r.prediction||{{}},path), c=(cur===val?' active':'')+(pred===val?' pred':'');html+=`<button ${{disabled?'disabled':''}} class="${{c}}" onclick='event.stopPropagation();setActiveGroup(${{gidx}});pick(${{JSON.stringify(path)}},${{JSON.stringify(val)}})'><span class="shortcut">[${{vidx+1}}]</span> ${{val===null?'none':val}}</button>`;}});html+='</div>';}});const interactionIndex=scalarPaths.length, interactionFocused=activeGroup===interactionIndex?' focused':'';html+=`<div class="group interaction${{interactionFocused}}" onclick="setActiveGroup(${{interactionIndex}})"><h3>interaction tags</h3>`; interactionTags.forEach((t,tidx)=>{{let checked=r.gt.interaction_tags.includes(t)?'checked':'', p=(r.prediction?.interaction_tags||[]).includes(t)?' ★pred':'';html+=`<label><input type="checkbox" ${{checked}} onclick="event.stopPropagation()" onchange='setActiveGroup(${{interactionIndex}});toggleInteraction(${{JSON.stringify(t)}},this.checked)'> <span class="shortcut">[${{tidx+1}}]</span> ${{t}}${{p}}</label>`;}});html+='</div>';document.getElementById('form').innerHTML=html;}}
function pick(path,v){{ensureGT(rows[i]);if(path==='ego_motion.speed_band'&&rows[i].gt.ego_motion.state==='stationary')return;set(rows[i].gt,path,v);if(path==='ego_motion.state'){{if(v==='stationary')set(rows[i].gt,'ego_motion.speed_band',null);else if(get(rows[i].gt,'ego_motion.speed_band')===null)set(rows[i].gt,'ego_motion.speed_band','unknown');}}render();}}
function toggleInteraction(t,on){{let a=rows[i].gt.interaction_tags;rows[i].gt.interaction_tags=on?[...new Set([...a,t])]:a.filter(x=>x!==t);persist();render();}}
function chooseNumber(n){{let name=groupNames[activeGroup];if(name==='interaction_tags'){{let t=interactionTags[n-1];if(!t)return;let on=!rows[i].gt.interaction_tags.includes(t);toggleInteraction(t,on);return;}}let values=defs[name];if(!values||n<1||n>values.length)return;if(name==='ego_motion.speed_band'&&rows[i].gt.ego_motion.state==='stationary')return;pick(name,values[n-1]);}}
function persist(){{localStorage.setItem(key,JSON.stringify(rows));}} function save(next){{ensureGT(rows[i]);rows[i].reviewed=true;persist();if(next&&i<rows.length-1)i++;render();}} function prev(){{if(i>0)i--;render();}} function next(){{if(i<rows.length-1)i++;render();}}
function exportGT(){{persist();let reviewed=rows.filter(r=>r.reviewed).map(r=>({{frame_index:r.frame_index,timestamp:r.timestamp,prediction:r.prediction,gt:r.gt,reviewed:true}}));let blob=new Blob([JSON.stringify({{recording:{json.dumps(recording)},sampling_hz:{sample_hz},frames:reviewed}},null,2)],{{type:'application/json'}});let a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download={json.dumps(recording + '_manual_gt.json')};a.click();URL.revokeObjectURL(a.href);}}
document.addEventListener('keydown',e=>{{if(['INPUT','TEXTAREA'].includes(document.activeElement.tagName))return;if(e.key==='Tab'){{e.preventDefault();cycleGroup(e.shiftKey?-1:1);}}else if(/^Digit[1-9]$/.test(e.code)){{e.preventDefault();chooseNumber(Number(e.code.slice(5)));}}else if(e.code==='Space'){{e.preventDefault();save(true);}}else if(e.key==='Enter'){{e.preventDefault();save(false);}}else if(e.key==='ArrowLeft'){{e.preventDefault();prev();}}else if(e.key==='ArrowRight'){{e.preventDefault();next();}}}});render();
</script></body></html>'''


def generate_review(
    prediction_path: Path,
    output_html: Path,
    *,
    source_hz: float,
    sample_hz: float,
    bev_root: Path | None = Path("outputs/02_frame_inputs_revised"),
) -> Path:
    document = json.loads(prediction_path.read_text(encoding="utf-8"))
    recording = _recording_id(document, prediction_path)
    rows = build_review_rows(
        document,
        source_hz=source_hz,
        sample_hz=sample_hz,
        recording=recording,
        bev_root=bev_root,
    )
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(_html(rows, recording, sample_hz), encoding="utf-8")
    return output_html


def _iter_reviewed(gt_doc: Any) -> Iterable[dict[str, Any]]:
    for row in _frames(gt_doc):
        if row.get("reviewed") is True and isinstance(row.get("gt"), dict):
            yield row


def _f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def evaluate_gt(gt_doc: Any) -> dict[str, Any]:
    scalar_counts: dict[str, Counter] = {path: Counter() for path in SCALAR_FIELDS}
    interaction_counts: dict[str, Counter] = {tag: Counter() for tag in INTERACTION_TAGS}
    reviewed = 0
    for row in _iter_reviewed(gt_doc):
        reviewed += 1
        gt = row["gt"]
        pred = row.get("prediction") if isinstance(row.get("prediction"), dict) else {}
        for path in SCALAR_FIELDS:
            g = _get_path(gt, path)
            p = _get_path(pred, path)
            if g in ("unknown", None):
                continue
            if p == g:
                scalar_counts[path]["tp"] += 1
            else:
                scalar_counts[path]["fp"] += 1
                scalar_counts[path]["fn"] += 1
        gtags = set(gt.get("interaction_tags") or [])
        ptags = set(pred.get("interaction_tags") or [])
        for tag in INTERACTION_TAGS:
            g, p = tag in gtags, tag in ptags
            if g and p:
                interaction_counts[tag]["tp"] += 1
            elif p and not g:
                interaction_counts[tag]["fp"] += 1
            elif g and not p:
                interaction_counts[tag]["fn"] += 1
            else:
                interaction_counts[tag]["tn"] += 1

    def pack(counts: Counter) -> dict[str, Any]:
        pr, rc, f = _f1(counts["tp"], counts["fp"], counts["fn"])
        return {
            "tp": counts["tp"],
            "fp": counts["fp"],
            "fn": counts["fn"],
            "precision": pr,
            "recall": rc,
            "f1": f,
        }

    scalar = {k: pack(v) for k, v in scalar_counts.items()}
    interactions = {k: pack(v) for k, v in interaction_counts.items()}
    all_items = list(scalar.values()) + list(interactions.values())
    macro_f1 = sum(x["f1"] for x in all_items) / len(all_items) if all_items else 0.0
    total = Counter()
    for counts in list(scalar_counts.values()) + list(interaction_counts.values()):
        total.update({k: counts[k] for k in ("tp", "fp", "fn")})
    micro = pack(total)
    return {
        "reviewed_frames": reviewed,
        "scalar_fields": scalar,
        "interaction_tags": interactions,
        "macro_f1": macro_f1,
        "micro": micro,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fast manual GT authoring and F1 for the simplified frame taxonomy")
    sub = parser.add_subparsers(dest="command", required=True)
    review = sub.add_parser("review", help="Generate a prediction-prefilled manual GT HTML with revised BEV images")
    review.add_argument("prediction", type=Path)
    review.add_argument("--output", type=Path, default=Path("outputs/06_gt_comparison/simplified_manual_gt.html"))
    review.add_argument("--source-hz", type=float, default=10.0)
    review.add_argument("--sample-hz", type=float, default=1.0)
    review.add_argument(
        "--bev-root",
        type=Path,
        default=Path("outputs/02_frame_inputs_revised"),
        help="Root containing <recording>/frame_XXXXXX/bev_revised.png",
    )
    review.add_argument("--no-bev", action="store_true", help="Disable BEV lookup")
    score = sub.add_parser("score", help="Score an exported manual GT JSON")
    score.add_argument("gt", type=Path)
    score.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "review":
        path = generate_review(
            args.prediction,
            args.output,
            source_hz=args.source_hz,
            sample_hz=args.sample_hz,
            bev_root=None if args.no_bev else args.bev_root,
        )
        print(f"Manual GT review: {path}")
        return 0
    gt_doc = json.loads(args.gt.read_text(encoding="utf-8"))
    report = evaluate_gt(gt_doc)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"F1 report: {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())