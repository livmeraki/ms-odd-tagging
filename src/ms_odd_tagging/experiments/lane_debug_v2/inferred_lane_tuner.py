"""Standalone live debugger for static inferred-lane affiliation/integration tuning."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TUNABLE_KEYS = {
    "static_inferred_lane_maximum_endpoint_distance_m": 20.0,
    "static_inferred_affiliation_maximum_boundary_endpoint_distance_m": 20.0,
    "static_inferred_affiliation_maximum_lateral_error_m": 2.0,
    "static_inferred_lane_maximum_heading_difference_deg": 30.0,
    "static_inferred_affiliation_maximum_curvature_difference_per_m": 0.08,
    "static_inferred_affiliation_maximum_width_difference_m": 1.0,
    "static_inferred_affiliation_minimum_unique_score_margin": 0.5,
}


def _compact_lane(lane: dict[str, Any]) -> dict[str, Any]:
    return {
        "lane_id": str(lane.get("lane_id")),
        "centerline_lcs_m": lane.get("centerline_lcs_m") or [],
        "left_boundary_lcs_m": lane.get("left_boundary_lcs_m") or [],
        "right_boundary_lcs_m": lane.get("right_boundary_lcs_m") or [],
        "polygon_lcs_m": lane.get("polygon_lcs_m") or [],
    }


def _compact_track(track: dict[str, Any]) -> dict[str, Any]:
    return {
        "track_id": str(track.get("track_id")),
        "member_lane_ids": [str(x) for x in track.get("member_lane_ids") or []],
        "centerline_lcs_m": track.get("centerline_lcs_m") or [],
        "pieces": [
            {
                "kind": p.get("kind"),
                "lane_id": None if p.get("lane_id") is None else str(p.get("lane_id")),
                "centerline_lcs_m": p.get("centerline_lcs_m") or [],
                "polygon_lcs_m": p.get("polygon_lcs_m") or [],
            }
            for p in track.get("pieces") or []
        ],
    }


def _compact_inferred(lane: dict[str, Any]) -> dict[str, Any]:
    return {
        "static_inferred_lane_id": lane.get("static_inferred_lane_id"),
        "route_id": lane.get("route_id"),
        "centerline_lcs_m": lane.get("centerline_lcs_m") or [],
        "left_boundary_lcs_m": lane.get("left_boundary_lcs_m") or [],
        "right_boundary_lcs_m": lane.get("right_boundary_lcs_m") or [],
        "polygon_lcs_m": lane.get("polygon_lcs_m") or [],
        "start_frame_index": lane.get("start_frame_index"),
        "end_frame_index": lane.get("end_frame_index"),
    }


def render_inferred_lane_tuner(
    following: dict[str, Any],
    path: Path,
    run_id: str,
    config: dict[str, Any],
) -> None:
    """Write a dependency-free HTML tuner using precomputed candidate metrics."""
    lane_geometry = [_compact_lane(x) for x in following.get("lane_geometry", [])]
    tracks = [_compact_track(x) for x in following.get("continuous_lane_tracks", [])]
    inferred = [_compact_inferred(x) for x in following.get("static_inferred_lanes", [])]
    affiliation_debug = following.get("static_inferred_affiliation_debug", [])
    integration_debug = following.get("static_inferred_lane_debug", [])
    defaults = {key: config.get(key, default) for key, default in TUNABLE_KEYS.items()}
    payload = {
        "run_id": run_id,
        "lane_geometry": lane_geometry,
        "tracks": tracks,
        "inferred": inferred,
        "affiliation_debug": affiliation_debug,
        "integration_debug": integration_debug,
        "defaults": defaults,
    }
    data = json.dumps(payload, ensure_ascii=True).replace("</", "<\\/")

    html = r'''<!doctype html>
<html><head><meta charset="utf-8"><title>Inferred lane affiliation tuner</title>
<style>
:root{font-family:Inter,Segoe UI,Arial,sans-serif;color:#172033;background:#f5f7fb}*{box-sizing:border-box}
body{margin:0}header{padding:14px 18px;background:#172033;color:white;display:flex;gap:18px;align-items:center}header b{font-size:17px}header span{opacity:.75;font-size:12px}
.main{display:grid;grid-template-columns:370px minmax(560px,1fr);height:calc(100vh - 50px)}
.controls{overflow:auto;padding:14px;background:white;border-right:1px solid #d9deea}.plotwrap{display:grid;grid-template-rows:minmax(440px,62vh) 1fr;overflow:hidden}
#plot{width:100%;height:100%;background:white}.bottom{overflow:auto;padding:10px 14px;background:#f8fafc;border-top:1px solid #d9deea}
label{font-size:12px;font-weight:600;display:block;margin:10px 0 4px}.row{display:grid;grid-template-columns:1fr 88px;gap:8px;align-items:center}.row input[type=range]{width:100%}.row input[type=number],select{width:100%;padding:6px;border:1px solid #cbd3e1;border-radius:6px;background:white}
button{padding:7px 10px;border:1px solid #aeb8c8;border-radius:7px;background:white;cursor:pointer}button:hover{background:#eef2f7}.btnrow{display:flex;gap:6px;margin:12px 0;flex-wrap:wrap}.status{padding:10px;border-radius:8px;background:#f1f5f9;margin:10px 0;font-size:12px;line-height:1.55}.good{background:#e9f8ef}.bad{background:#fff0ef}.warn{background:#fff8e5}
.legend{font-size:11px;color:#596477;margin-top:8px;line-height:1.8}.sw{display:inline-block;width:16px;height:4px;margin:0 4px 2px 8px;vertical-align:middle}.toggles{display:grid;grid-template-columns:1fr 1fr;gap:6px 10px;margin:12px 0;padding:10px;border:1px solid #d9deea;border-radius:8px;background:#f8fafc}.toggles label{margin:0;font-weight:500;display:flex;gap:6px;align-items:center}
.candidateTables{display:grid;grid-template-columns:1fr 1fr;gap:12px}table{width:100%;border-collapse:collapse;font-size:11px;background:white}th,td{border-bottom:1px solid #e5e9f0;padding:5px 6px;text-align:left;vertical-align:top}th{position:sticky;top:0;background:#eef2f7}.sel{background:#e9f8ef}.eligible{background:#f4f8ff}.rej{color:#7c2730}.small{font-size:11px;color:#647084}.metric{font-variant-numeric:tabular-nums}.sectionTitle{font-weight:700;margin:3px 0 7px}
svg text{font-size:10px;paint-order:stroke;stroke:white;stroke-width:3px;stroke-linejoin:round;pointer-events:none}.lane{fill:none;stroke:#d6dde8;stroke-width:.7}.inferred{stroke:#16a34a;fill:#16a34a}.candidate-track{fill:none;stroke-width:2}.candidate-piece{fill:none;stroke-width:2.6}.candidate-rejected{stroke:#a8b0bd;stroke-dasharray:5 4;opacity:.55}.back-eligible{stroke:#60a5fa;opacity:.82}.front-eligible{stroke:#c084fc;opacity:.82}.back-selected{stroke:#0b5ed7;opacity:1}.front-selected{stroke:#7e22ce;opacity:1}.candidate-endpoint{stroke:white;stroke-width:1.5}.endpointline{stroke-dasharray:4 3;stroke-width:1.3;fill:none;opacity:.9}.boundaryline{stroke-dasharray:2 3;stroke-width:1;fill:none;opacity:.65}.back-line{stroke:#2563eb}.front-line{stroke:#7c3aed}.rejected-line{stroke:#a8b0bd}.candidate-label{font-size:10px;font-weight:600}.candidate-label.rejected{fill:#7b8492}.candidate-label.back{fill:#1d4ed8}.candidate-label.front{fill:#6d28d9}
</style></head><body>
<header><b>Inferred Lane Affiliation / Integration Tuner</b><span id="runLabel"></span></header>
<div class="main"><aside class="controls">
<label>Inferred lane</label><select id="laneSelect"></select>
<div id="controlHost"></div>
<div class="toggles">
<label><input id="showBack" type="checkbox" checked>BACK candidates</label>
<label><input id="showFront" type="checkbox" checked>FRONT candidates</label>
<label><input id="showRejected" type="checkbox" checked>Rejected</label>
<label><input id="showLabels" type="checkbox" checked>Labels</label>
<label><input id="showConnections" type="checkbox" checked>Center connections</label>
<label><input id="showBoundaries" type="checkbox">Boundary connections</label>
<label><input id="showAllLd" type="checkbox" checked>Background LD</label>
<label><input id="showPieces" type="checkbox" checked>Support fragments</label>
</div>
<div class="btnrow"><button id="reset">Reset thresholds</button><button id="download">Download tuned JSON</button></div>
<div id="status" class="status"></div>
<div class="legend">
<span class="sw" style="background:#16a34a"></span>inferred lane<br>
<span class="sw" style="background:#0b5ed7"></span>selected BACK <span class="sw" style="background:#60a5fa"></span>eligible BACK<br>
<span class="sw" style="background:#7e22ce"></span>selected FRONT <span class="sw" style="background:#c084fc"></span>eligible FRONT<br>
<span class="sw" style="background:#a8b0bd"></span>rejected candidate
</div>
</aside><section class="plotwrap"><svg id="plot" viewBox="0 0 1100 650" preserveAspectRatio="xMidYMid meet"></svg><div class="bottom"><div class="candidateTables"><div><div class="sectionTitle">BACK candidates</div><div id="backTable"></div></div><div><div class="sectionTitle">FRONT candidates</div><div id="frontTable"></div></div></div></div></section></div>
<script>const D=__DATA__;
const specs={
 static_inferred_lane_maximum_endpoint_distance_m:{label:'Max center endpoint distance (m)',min:0,max:40,step:.1},
 static_inferred_affiliation_maximum_boundary_endpoint_distance_m:{label:'Max boundary endpoint distance (m)',min:0,max:40,step:.1},
 static_inferred_affiliation_maximum_lateral_error_m:{label:'Max lateral error (m)',min:0,max:8,step:.05},
 static_inferred_lane_maximum_heading_difference_deg:{label:'Max local tangent difference (deg)',min:0,max:90,step:.5},
 static_inferred_affiliation_maximum_curvature_difference_per_m:{label:'Max curvature difference (/m)',min:0,max:.4,step:.005},
 static_inferred_affiliation_maximum_width_difference_m:{label:'Max local endpoint width difference (m)',min:0,max:4,step:.05},
 static_inferred_affiliation_minimum_unique_score_margin:{label:'Minimum unique score margin',min:0,max:10,step:.05}
};
const values={...D.defaults};
const lanes=new Map(D.lane_geometry.map(x=>[String(x.lane_id),x]));
const tracks=new Map((D.tracks||[]).map(x=>[String(x.track_id),x]));
const inferred=new Map(D.inferred.map(x=>[String(x.static_inferred_lane_id),x]));
const dbg=new Map(D.affiliation_debug.map(x=>[String(x.static_inferred_lane_id),x]));
const integ=new Map(D.integration_debug.map(x=>[String(x.static_inferred_lane_id),x]));
const toggleIds=['showBack','showFront','showRejected','showLabels','showConnections','showBoundaries','showAllLd','showPieces'];
document.getElementById('runLabel').textContent='run '+D.run_id;
const select=document.getElementById('laneSelect');
for(const x of D.inferred){const o=document.createElement('option');o.value=x.static_inferred_lane_id;o.textContent=`${x.static_inferred_lane_id} · frames ${x.start_frame_index ?? '?'}–${x.end_frame_index ?? '?'}`;select.appendChild(o)}
const host=document.getElementById('controlHost');
for(const [key,s] of Object.entries(specs)){const lab=document.createElement('label');lab.textContent=s.label;const row=document.createElement('div');row.className='row';const range=document.createElement('input');range.type='range';range.min=s.min;range.max=s.max;range.step=s.step;range.value=values[key];const num=document.createElement('input');num.type='number';num.min=s.min;num.max=s.max;num.step=s.step;num.value=values[key];const update=v=>{values[key]=Number(v);range.value=values[key];num.value=values[key];render()};range.oninput=()=>update(range.value);num.onchange=()=>update(num.value);row.append(range,num);host.append(lab,row)}
function reasons(c){const r=[];if(Number(c.longitudinal_m)<=.1&&Number(c.center_endpoint_distance_m)>.25&&!c.endpoint_inside_inferred_polygon)r.push('not_longitudinally_before_or_after');if(Number(c.center_endpoint_distance_m)>values.static_inferred_lane_maximum_endpoint_distance_m)r.push('center_endpoint_distance');const b=values.static_inferred_affiliation_maximum_boundary_endpoint_distance_m;if(Number(c.left_boundary_endpoint_distance_m)>b)r.push('left_boundary_endpoint_distance');if(Number(c.right_boundary_endpoint_distance_m)>b)r.push('right_boundary_endpoint_distance');if(Number(c.lateral_error_m)>values.static_inferred_affiliation_maximum_lateral_error_m)r.push('lateral_error_adjacent_or_parallel');if(Number(c.heading_difference_deg)>values.static_inferred_lane_maximum_heading_difference_deg)r.push('local_tangent_difference');if(Number(c.local_width_difference_m)>values.static_inferred_affiliation_maximum_width_difference_m)r.push('local_endpoint_width_difference');if(Number(c.curvature_difference_per_m)>values.static_inferred_affiliation_maximum_curvature_difference_per_m&&!c.endpoint_inside_inferred_polygon)r.push('local_curvature_difference');return r}
function choose(rows){const byTrack=new Map();for(const c of rows){if(reasons(c).length)continue;const id=String(c.track_id),prev=byTrack.get(id);if(!prev||Number(c.score)<Number(prev.score))byTrack.set(id,c)}const ok=[...byTrack.values()].sort((a,b)=>Number(a.score)-Number(b.score)||String(a.track_id).localeCompare(String(b.track_id)));if(!ok.length)return{selected:null,why:'no_candidate_passed_local_endpoint_gates',eligible:ok};if(ok.length>1){const margin=Number(ok[1].score)-Number(ok[0].score);if(margin<values.static_inferred_affiliation_minimum_unique_score_margin)return{selected:null,why:`ambiguous_multiple_local_endpoint_continuations (margin ${margin.toFixed(3)})`,runner:ok[1],eligible:ok,margin};return{selected:ok[0],why:null,eligible:ok,margin}}return{selected:ok[0],why:null,eligible:ok,margin:null}}
function candidateKey(c){return `${c.track_id}|${c.track_endpoint_side}|${c.supporting_lane_id}|${c.supporting_lane_endpoint_side}`}
function sameCandidate(a,b){return !!a&&!!b&&candidateKey(a)===candidateKey(b)}
function laneEndpoint(c){const l=lanes.get(String(c.supporting_lane_id));if(!l)return null;const a=l.centerline_lcs_m||[];if(!a.length)return null;return c.supporting_lane_endpoint_side==='start'?a[0]:a[a.length-1]}
function laneBoundaryEndpoint(c,side){const l=lanes.get(String(c.supporting_lane_id));if(!l)return null;const a=side==='left'?(l.left_boundary_lcs_m||[]):(l.right_boundary_lcs_m||[]);if(!a.length)return null;return c.supporting_lane_endpoint_side==='start'?a[0]:a[a.length-1]}
function inferredEndpoint(inf,role){const a=inf.centerline_lcs_m||[];if(!a.length)return null;return role==='back'?a[0]:a[a.length-1]}
function inferredBoundaryEndpoint(inf,role,side){const a=side==='left'?(inf.left_boundary_lcs_m||[]):(inf.right_boundary_lcs_m||[]);if(!a.length)return null;return role==='back'?a[0]:a[a.length-1]}
function trackGeometry(c){const t=tracks.get(String(c.track_id));if(t&&(t.centerline_lcs_m||[]).length>1)return t.centerline_lcs_m;const l=lanes.get(String(c.supporting_lane_id));return l?.centerline_lcs_m||[]}
function supportGeometry(c){const t=tracks.get(String(c.track_id));if(t){const p=(t.pieces||[]).find(p=>String(p.lane_id)===String(c.supporting_lane_id)&&(p.centerline_lcs_m||[]).length>1);if(p)return p.centerline_lcs_m}return lanes.get(String(c.supporting_lane_id))?.centerline_lcs_m||[]}
function uniqueCandidates(rows){const seen=new Set(),out=[];for(const c of rows){const k=candidateKey(c);if(seen.has(k))continue;seen.add(k);out.push(c)}return out}
function visibleRows(backRows,frontRows){let rows=[];if(document.getElementById('showBack').checked)rows.push(...backRows);if(document.getElementById('showFront').checked)rows.push(...frontRows);if(!document.getElementById('showRejected').checked)rows=rows.filter(c=>!reasons(c).length);return uniqueCandidates(rows)}
function allPoints(inf,rows){const pts=[];for(const p of inf.polygon_lcs_m||[])pts.push(p);for(const c of rows){for(const p of trackGeometry(c))pts.push(p);const l=lanes.get(String(c.supporting_lane_id));for(const p of l?.left_boundary_lcs_m||[])pts.push(p);for(const p of l?.right_boundary_lcs_m||[])pts.push(p)}return pts}
function transform(points){let xs=points.map(p=>Number(p[0])),ys=points.map(p=>Number(p[1]));if(!xs.length)return p=>p;let x0=Math.min(...xs),x1=Math.max(...xs),y0=Math.min(...ys),y1=Math.max(...ys);let dx=Math.max(1,x1-x0),dy=Math.max(1,y1-y0);x0-=dx*.08;x1+=dx*.08;y0-=dy*.12;y1+=dy*.12;dx=x1-x0;dy=y1-y0;return p=>[45+(Number(p[0])-x0)/dx*1010,605-(Number(p[1])-y0)/dy*560]}
function path(points,T){return(points||[]).map((p,i)=>{const q=T(p);return`${i?'L':'M'}${q[0].toFixed(1)},${q[1].toFixed(1)}`}).join(' ')}
function svgEl(tag,attrs={}){const e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,v);return e}
function candidateState(c,role,res){if(sameCandidate(c,res.selected))return 'selected';if(reasons(c).length)return 'rejected';return 'eligible'}
function roleClass(role,state){if(state==='rejected')return 'candidate-rejected';return `${role}-${state}`}
function marker(svg,p,T,role,state){if(!p)return;const q=T(p);const fill=state==='rejected'?'#a8b0bd':role==='back'?(state==='selected'?'#0b5ed7':'#60a5fa'):(state==='selected'?'#7e22ce':'#c084fc');svg.appendChild(svgEl('circle',{cx:q[0],cy:q[1],r:state==='selected'?5:3.5,fill,class:'candidate-endpoint'}))}
function addLabel(svg,c,T,role,state,index){if(!document.getElementById('showLabels').checked)return;const p=laneEndpoint(c);if(!p)return;const q=T(p),t=svgEl('text',{x:q[0]+7,y:q[1]-8-(index%3)*11,class:`candidate-label ${state==='rejected'?'rejected':role}`});const prefix=role==='back'?'B':'F';t.textContent=`${prefix}${index+1} ${c.track_id} · LD${c.supporting_lane_id} · ${state} · score ${Number(c.score).toFixed(2)}`;svg.appendChild(t)}
function drawCandidate(svg,inf,c,T,role,res,index){const state=candidateState(c,role,res);if(state==='rejected'&&!document.getElementById('showRejected').checked)return;const tg=trackGeometry(c);if(tg.length>1)svg.appendChild(svgEl('path',{d:path(tg,T),class:`candidate-track ${roleClass(role,state)}`}));if(document.getElementById('showPieces').checked){const sg=supportGeometry(c);if(sg.length>1)svg.appendChild(svgEl('path',{d:path(sg,T),class:`candidate-piece ${roleClass(role,state)}`}))}const a=inferredEndpoint(inf,role),b=laneEndpoint(c);marker(svg,b,T,role,state);if(document.getElementById('showConnections').checked&&a&&b)svg.appendChild(svgEl('path',{d:path([a,b],T),class:`endpointline ${state==='rejected'?'rejected-line':role+'-line'}`}));if(document.getElementById('showBoundaries').checked){for(const side of ['left','right']){const ia=inferredBoundaryEndpoint(inf,role,side),cb=laneBoundaryEndpoint(c,side);if(ia&&cb)svg.appendChild(svgEl('path',{d:path([ia,cb],T),class:`boundaryline ${state==='rejected'?'rejected-line':role+'-line'}`}))}}addLabel(svg,c,T,role,state,index)}
function draw(inf,back,front,backRows,frontRows){const svg=document.getElementById('plot');svg.replaceChildren();const rows=visibleRows(backRows,frontRows),T=transform(allPoints(inf,rows));if(document.getElementById('showAllLd').checked){for(const l of D.lane_geometry){if((l.centerline_lcs_m||[]).length<2)continue;svg.appendChild(svgEl('path',{d:path(l.centerline_lcs_m,T),class:'lane'}))}}const ip=svgEl('path',{d:path(inf.polygon_lcs_m,T)+' Z',class:'inferred','fill-opacity':back.selected&&front.selected?'.12':'.06'});svg.appendChild(ip);svg.appendChild(svgEl('path',{d:path(inf.centerline_lcs_m,T),class:'inferred','fill':'none','stroke-width':'2.5'}));marker(svg,inferredEndpoint(inf,'back'),T,'back','selected');marker(svg,inferredEndpoint(inf,'front'),T,'front','selected');if(document.getElementById('showBack').checked)uniqueCandidates(backRows).forEach((c,i)=>drawCandidate(svg,inf,c,T,'back',back,i));if(document.getElementById('showFront').checked)uniqueCandidates(frontRows).forEach((c,i)=>drawCandidate(svg,inf,c,T,'front',front,i))}
function table(rows,res){const ranked=[...rows].sort((a,b)=>{const as=reasons(a).length?1:0,bs=reasons(b).length?1:0;return as-bs||Number(a.score)-Number(b.score)});let h='<table><thead><tr><th>Track / lane</th><th>center</th><th>L/R</th><th>lat</th><th>head</th><th>width</th><th>curv</th><th>score</th><th>decision</th></tr></thead><tbody>';for(const c of ranked){const rs=reasons(c),sel=sameCandidate(res.selected,c),eligible=!rs.length;h+=`<tr class="${sel?'sel':eligible?'eligible':'rej'}"><td>${c.track_id}<br><span class=small>LD${c.supporting_lane_id} ${c.supporting_lane_endpoint_side}</span></td><td class=metric>${Number(c.center_endpoint_distance_m).toFixed(2)}</td><td class=metric>${Number(c.left_boundary_endpoint_distance_m).toFixed(2)} / ${Number(c.right_boundary_endpoint_distance_m).toFixed(2)}</td><td>${Number(c.lateral_error_m).toFixed(2)}</td><td>${Number(c.heading_difference_deg).toFixed(1)}°</td><td>${Number(c.local_width_difference_m).toFixed(2)}</td><td>${Number(c.curvature_difference_per_m).toFixed(3)}</td><td>${Number(c.score).toFixed(2)}</td><td>${sel?'SELECTED':rs.length?rs.join('<br>'):'ELIGIBLE'}</td></tr>`}return h+'</tbody></table>'}
function render(){const id=select.value,inf=inferred.get(id);if(!inf){document.getElementById('status').className='status warn';document.getElementById('status').textContent='No inferred lanes in this run.';document.getElementById('plot').replaceChildren();return}const d=dbg.get(id)||{},backRows=d.back_candidates||[],frontRows=d.front_candidates||[],back=choose(backRows),front=choose(frontRows);const complete=!!(back.selected&&front.selected);let action='rejected';if(complete)action=String(back.selected.track_id)===String(front.selected.track_id)?'attach_to_same_track':'merge_front_back_tracks';const current=integ.get(id)||{};const s=document.getElementById('status');s.className='status '+(complete?'good':'bad');s.innerHTML=`<b>Tuned result</b><br>BACK: ${back.selected?back.selected.track_id:'—'} ${back.why?'<span class=rej>'+back.why+'</span>':''}<br>FRONT: ${front.selected?front.selected.track_id:'—'} ${front.why?'<span class=rej>'+front.why+'</span>':''}<br>bridge_complete: <b>${complete}</b><br>predicted integration: <b>${action}</b><br><span class=small>eligible candidates: BACK ${back.eligible?.length||0}, FRONT ${front.eligible?.length||0}</span><hr style="border:0;border-top:1px solid #dbe2ec"><span class=small>Current Python integration: ${current.accepted?'accepted':'rejected'} · ${current.action||current.rejection_reason||'n/a'}</span>`;document.getElementById('backTable').innerHTML=table(backRows,back);document.getElementById('frontTable').innerHTML=table(frontRows,front);draw(inf,back,front,backRows,frontRows)}
select.onchange=render;for(const id of toggleIds)document.getElementById(id).onchange=render;document.getElementById('reset').onclick=()=>{Object.assign(values,D.defaults);document.querySelectorAll('#controlHost .row').forEach((r,i)=>{const key=Object.keys(specs)[i];r.children[0].value=values[key];r.children[1].value=values[key]});render()};document.getElementById('download').onclick=()=>{const blob=new Blob([JSON.stringify(values,null,2)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`${D.run_id}_inferred_affiliation_tuned.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),500)};render();
</script></body></html>'''.replace("__DATA__", data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
