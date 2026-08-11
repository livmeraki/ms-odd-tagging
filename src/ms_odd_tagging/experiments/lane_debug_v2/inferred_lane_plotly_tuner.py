"""Interactive Plotly debugger for static inferred-lane affiliation/integration tuning.

This is intentionally separate from the SVG tuner.  It renders only the
currently selected inferred lane and its affiliation candidates with regular
2D Plotly scatter traces (not scattergl), keeping the page light while adding
zoom/pan/hover/legend interaction.
"""
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
                "kind": piece.get("kind"),
                "lane_id": None if piece.get("lane_id") is None else str(piece.get("lane_id")),
                "centerline_lcs_m": piece.get("centerline_lcs_m") or [],
                "polygon_lcs_m": piece.get("polygon_lcs_m") or [],
            }
            for piece in track.get("pieces") or []
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


def render_inferred_lane_plotly_tuner(
    following: dict[str, Any],
    path: Path,
    run_id: str,
    config: dict[str, Any],
) -> None:
    try:
        from plotly.offline import get_plotlyjs
        plotly_js = get_plotlyjs()
    except Exception as exc:  # pragma: no cover - environment failure
        raise RuntimeError("plotly is required for the inferred-lane Plotly tuner") from exc

    payload = {
        "run_id": run_id,
        "recording_id": following.get("recording_id"),
        "lane_geometry": [_compact_lane(x) for x in following.get("lane_geometry", [])],
        "tracks": [_compact_track(x) for x in following.get("continuous_lane_tracks", [])],
        "inferred": [_compact_inferred(x) for x in following.get("static_inferred_lanes", [])],
        "affiliation_debug": following.get("static_inferred_affiliation_debug", []),
        "integration_debug": following.get("static_inferred_lane_debug", []),
        "defaults": {key: config.get(key, default) for key, default in TUNABLE_KEYS.items()},
    }
    data = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/")

    html = r'''<!doctype html>
<html><head><meta charset="utf-8"><title>Plotly inferred lane candidate tuner</title><script>__PLOTLY_JS__</script>
<style>
html,body{margin:0;height:100%;font:13px system-ui,Segoe UI,Arial,sans-serif;color:#172033;background:#f5f7fb}
*{box-sizing:border-box}.page{display:grid;grid-template-columns:390px minmax(0,1fr);height:100vh}.side{overflow:auto;background:white;border-right:1px solid #d8deea;padding:14px}.main{min-width:0;display:grid;grid-template-rows:auto minmax(620px,1fr) minmax(180px,32vh);overflow:hidden}.top{padding:10px 14px;background:white;border-bottom:1px solid #d8deea;display:flex;gap:14px;align-items:center;flex-wrap:wrap}.plot{width:100%;height:100%;min-height:620px;background:white}.tables{overflow:auto;padding:10px 14px;background:#f8fafc;border-top:1px solid #d8deea}.candidateTables{display:grid;grid-template-columns:1fr 1fr;gap:12px}
h2{font-size:16px;margin:0 0 4px}.sub{color:#657086;font-size:11px;margin-bottom:12px}.section{font-weight:700;margin:14px 0 6px}.control{margin:9px 0}.control label{font-size:11px;font-weight:600;display:block;margin-bottom:3px}.row{display:grid;grid-template-columns:1fr 82px;gap:7px;align-items:center}.row input[type=range]{width:100%}.row input[type=number],select{width:100%;padding:6px;border:1px solid #c8d0de;border-radius:6px;background:white}.toggles{display:grid;grid-template-columns:1fr 1fr;gap:6px 8px;margin:10px 0}.toggles label{font-size:11px;display:flex;align-items:center;gap:5px}.buttons{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}button{padding:7px 9px;background:white;border:1px solid #abb5c5;border-radius:7px;cursor:pointer}.status{padding:9px;border-radius:8px;background:#eef2f7;line-height:1.55;font-size:12px}.status.good{background:#e9f8ef}.status.bad{background:#fff0ef}.legend{font-size:11px;line-height:1.8;color:#596477}.sw{display:inline-block;width:15px;height:4px;vertical-align:middle;margin-right:4px}.blue{background:#0b5ed7}.lblue{background:#60a5fa}.purple{background:#7e22ce}.lpurple{background:#c084fc}.gray{background:#9ca3af}.green{background:#16a34a}
table{width:100%;border-collapse:collapse;background:white;font-size:11px}th,td{border-bottom:1px solid #e4e8ef;padding:5px 6px;text-align:left;vertical-align:top}th{position:sticky;top:0;background:#eef2f7}.sel{background:#e9f8ef}.eligible{background:#f3f8ff}.rej{color:#8a2831}.small{font-size:10px;color:#657086}.sectionTitle{font-weight:700;margin:2px 0 6px}@media(max-width:1000px){.page{grid-template-columns:320px minmax(0,1fr)}.main{grid-template-rows:auto minmax(560px,1fr) minmax(180px,35vh)}}
</style></head><body><div class="page"><aside class="side">
<h2>Plotly inferred lane candidate tuner</h2><div class="sub" id="runLabel"></div>
<div class="section">Inferred lane</div><select id="laneSelect"></select>
<div class="section">Affiliation thresholds</div><div id="controlHost"></div>
<div class="section">Display</div><div class="toggles">
<label><input id="showBack" type="checkbox" checked>BACK</label><label><input id="showFront" type="checkbox" checked>FRONT</label>
<label><input id="showRejected" type="checkbox" checked>Rejected</label><label><input id="showBackground" type="checkbox">Background LD</label>
<label><input id="showSupport" type="checkbox" checked>Support fragment</label><label><input id="showCenterLinks" type="checkbox" checked>Center links</label>
<label><input id="showBoundaryLinks" type="checkbox">Boundary links</label><label><input id="showLabels" type="checkbox">Text labels</label>
</div><div class="buttons"><button id="reset">Reset thresholds</button><button id="fit">Fit candidates</button><button id="download">Download tuned JSON</button></div>
<div id="status" class="status"></div><div class="section">Legend</div><div class="legend"><span class="sw green"></span>inferred lane<br><span class="sw blue"></span>selected BACK &nbsp;<span class="sw lblue"></span>eligible BACK<br><span class="sw purple"></span>selected FRONT &nbsp;<span class="sw lpurple"></span>eligible FRONT<br><span class="sw gray"></span>rejected</div>
</aside><main class="main"><div class="top"><b id="title"></b><span class="small">Wheel zoom · drag pan · double-click reset · hover for candidate evidence · click legend to hide traces</span></div><div id="plot" class="plot"></div><div class="tables"><div class="candidateTables"><div><div class="sectionTitle">BACK candidates</div><div id="backTable"></div></div><div><div class="sectionTitle">FRONT candidates</div><div id="frontTable"></div></div></div></div></main></div>
<script id="data" type="application/json">__DATA__</script><script>
const D=JSON.parse(document.getElementById('data').textContent);
const lanes=new Map(D.lane_geometry.map(x=>[String(x.lane_id),x]));
const tracks=new Map((D.tracks||[]).map(x=>[String(x.track_id),x]));
const inferred=new Map(D.inferred.map(x=>[String(x.static_inferred_lane_id),x]));
const dbg=new Map(D.affiliation_debug.map(x=>[String(x.static_inferred_lane_id),x]));
const integ=new Map(D.integration_debug.map(x=>[String(x.static_inferred_lane_id),x]));
const values={...D.defaults}; let keepView=null;
const specs={
 static_inferred_lane_maximum_endpoint_distance_m:{label:'Max center endpoint distance (m)',min:0,max:40,step:.1},
 static_inferred_affiliation_maximum_boundary_endpoint_distance_m:{label:'Max boundary endpoint distance (m)',min:0,max:40,step:.1},
 static_inferred_affiliation_maximum_lateral_error_m:{label:'Max lateral error (m)',min:0,max:8,step:.05},
 static_inferred_lane_maximum_heading_difference_deg:{label:'Max local tangent difference (deg)',min:0,max:90,step:.5},
 static_inferred_affiliation_maximum_curvature_difference_per_m:{label:'Max curvature difference (/m)',min:0,max:.4,step:.005},
 static_inferred_affiliation_maximum_width_difference_m:{label:'Max local endpoint width difference (m)',min:0,max:4,step:.05},
 static_inferred_affiliation_minimum_unique_score_margin:{label:'Minimum unique score margin',min:0,max:10,step:.05}
};
const select=document.getElementById('laneSelect');for(const x of D.inferred){const o=document.createElement('option');o.value=x.static_inferred_lane_id;o.textContent=`${x.static_inferred_lane_id} · frames ${x.start_frame_index??'?'}–${x.end_frame_index??'?'}`;select.appendChild(o)}
document.getElementById('runLabel').textContent=`${D.recording_id||''} · run ${D.run_id}`;document.getElementById('title').textContent='Interactive affiliation candidate geometry';
const host=document.getElementById('controlHost');for(const[key,s]of Object.entries(specs)){const wrap=document.createElement('div');wrap.className='control';const lab=document.createElement('label');lab.textContent=s.label;const row=document.createElement('div');row.className='row';const range=document.createElement('input');range.type='range';range.min=s.min;range.max=s.max;range.step=s.step;range.value=values[key];const num=document.createElement('input');num.type='number';num.min=s.min;num.max=s.max;num.step=s.step;num.value=values[key];const set=v=>{values[key]=Number(v);range.value=values[key];num.value=values[key];render(false)};range.oninput=()=>set(range.value);num.onchange=()=>set(num.value);row.append(range,num);wrap.append(lab,row);host.appendChild(wrap)}
function reasons(c){const r=[];if(Number(c.longitudinal_m)<=.1&&Number(c.center_endpoint_distance_m)>.25&&!c.endpoint_inside_inferred_polygon)r.push('not_longitudinally_before_or_after');if(Number(c.center_endpoint_distance_m)>values.static_inferred_lane_maximum_endpoint_distance_m)r.push('center_endpoint_distance');const b=values.static_inferred_affiliation_maximum_boundary_endpoint_distance_m;if(Number(c.left_boundary_endpoint_distance_m)>b)r.push('left_boundary_endpoint_distance');if(Number(c.right_boundary_endpoint_distance_m)>b)r.push('right_boundary_endpoint_distance');if(Number(c.lateral_error_m)>values.static_inferred_affiliation_maximum_lateral_error_m)r.push('lateral_error_adjacent_or_parallel');if(Number(c.heading_difference_deg)>values.static_inferred_lane_maximum_heading_difference_deg)r.push('local_tangent_difference');if(Number(c.local_width_difference_m)>values.static_inferred_affiliation_maximum_width_difference_m)r.push('local_endpoint_width_difference');if(Number(c.curvature_difference_per_m)>values.static_inferred_affiliation_maximum_curvature_difference_per_m&&!c.endpoint_inside_inferred_polygon)r.push('local_curvature_difference');return r}
function choose(rows){const best=new Map();for(const c of rows){if(reasons(c).length)continue;const id=String(c.track_id),p=best.get(id);if(!p||Number(c.score)<Number(p.score))best.set(id,c)}const ok=[...best.values()].sort((a,b)=>Number(a.score)-Number(b.score)||String(a.track_id).localeCompare(String(b.track_id)));if(!ok.length)return{selected:null,eligible:ok,why:'no_candidate_passed_local_endpoint_gates'};if(ok.length>1){const m=Number(ok[1].score)-Number(ok[0].score);if(m<values.static_inferred_affiliation_minimum_unique_score_margin)return{selected:null,eligible:ok,why:`ambiguous_multiple_local_endpoint_continuations (margin ${m.toFixed(3)})`,margin:m};return{selected:ok[0],eligible:ok,why:null,margin:m}}return{selected:ok[0],eligible:ok,why:null,margin:null}}
function key(c){return`${c.track_id}|${c.track_endpoint_side}|${c.supporting_lane_id}|${c.supporting_lane_endpoint_side}`}function same(a,b){return!!a&&!!b&&key(a)===key(b)}
function xy(points){return{x:(points||[]).map(p=>p[0]),y:(points||[]).map(p=>p[1])}}function laneEndpoint(c){const l=lanes.get(String(c.supporting_lane_id)),a=l?.centerline_lcs_m||[];return a.length?(c.supporting_lane_endpoint_side==='start'?a[0]:a[a.length-1]):null}function laneBoundary(c,side){const l=lanes.get(String(c.supporting_lane_id)),a=side==='left'?(l?.left_boundary_lcs_m||[]):(l?.right_boundary_lcs_m||[]);return a.length?(c.supporting_lane_endpoint_side==='start'?a[0]:a[a.length-1]):null}function infEndpoint(inf,role){const a=inf.centerline_lcs_m||[];return a.length?(role==='back'?a[0]:a[a.length-1]):null}function infBoundary(inf,role,side){const a=side==='left'?(inf.left_boundary_lcs_m||[]):(inf.right_boundary_lcs_m||[]);return a.length?(role==='back'?a[0]:a[a.length-1]):null}
function trackLine(c){const t=tracks.get(String(c.track_id));if((t?.centerline_lcs_m||[]).length>1)return t.centerline_lcs_m;return lanes.get(String(c.supporting_lane_id))?.centerline_lcs_m||[]}function supportLine(c){const t=tracks.get(String(c.track_id));const p=(t?.pieces||[]).find(p=>String(p.lane_id)===String(c.supporting_lane_id)&&(p.centerline_lcs_m||[]).length>1);return p?.centerline_lcs_m||lanes.get(String(c.supporting_lane_id))?.centerline_lcs_m||[]}
const colors={inferred:'#16a34a',backSelected:'#0b5ed7',backEligible:'#60a5fa',frontSelected:'#7e22ce',frontEligible:'#c084fc',rejected:'#9ca3af',background:'#d5dbe5'};
function state(c,res){if(same(c,res.selected))return'selected';return reasons(c).length?'rejected':'eligible'}function color(role,st){if(st==='rejected')return colors.rejected;if(role==='back')return st==='selected'?colors.backSelected:colors.backEligible;return st==='selected'?colors.frontSelected:colors.frontEligible}
function hover(c,role,st){const rs=reasons(c);return[`<b>${role.toUpperCase()} ${st.toUpperCase()}</b>`,`track=${c.track_id} · supporting LD=${c.supporting_lane_id} ${c.supporting_lane_endpoint_side}`,`center=${Number(c.center_endpoint_distance_m).toFixed(3)} m`,`left/right boundary=${Number(c.left_boundary_endpoint_distance_m).toFixed(3)} / ${Number(c.right_boundary_endpoint_distance_m).toFixed(3)} m`,`longitudinal=${Number(c.longitudinal_m).toFixed(3)} m · lateral=${Number(c.lateral_error_m).toFixed(3)} m`,`heading=${Number(c.heading_difference_deg).toFixed(3)}°`,`width diff=${Number(c.local_width_difference_m).toFixed(3)} m · curvature diff=${Number(c.curvature_difference_per_m).toFixed(5)} /m`,`score=${Number(c.score).toFixed(4)}`,rs.length?`REJECT: ${rs.join(', ')}`:'passes hard gates'].join('<br>')}
function lineTrace(points,name,c,width,dash,hovertext,legendgroup,showlegend=true){const q=xy(points);return{x:q.x,y:q.y,type:'scatter',mode:'lines',name,legendgroup,showlegend,line:{color:c,width,dash},hovertemplate:hovertext?hovertext+'<extra></extra>':name+'<extra></extra>'}}
function markerTrace(point,name,c,hovertext,legendgroup){return{x:[point[0]],y:[point[1]],type:'scatter',mode:'markers',name,legendgroup,showlegend:false,marker:{size:9,color:c,line:{width:1,color:'#ffffff'}},hovertemplate:hovertext+'<extra></extra>'}}
function polygonTrace(points,name,c,alpha){const q=xy(points);return{x:q.x,y:q.y,type:'scatter',mode:'lines',name,showlegend:true,line:{color:c,width:2},fill:'toself',fillcolor:`rgba(${c==='#16a34a'?'22,163,74':'100,116,139'},${alpha})`,hovertemplate:name+'<extra></extra>'}}
function candidateTraces(inf,c,role,res,index){const st=state(c,res);if(st==='rejected'&&!document.getElementById('showRejected').checked)return[];const cc=color(role,st),dash=st==='rejected'?'dash':'solid',h=hover(c,role,st),group=`${role}-${index}-${key(c)}`,out=[];const tl=trackLine(c);if(tl.length>1)out.push(lineTrace(tl,`${role.toUpperCase()} ${index+1} · ${c.track_id} · ${st}`,cc,st==='selected'?4:2,dash,h,group,true));if(document.getElementById('showSupport').checked){const sl=supportLine(c);if(sl.length>1)out.push(lineTrace(sl,`support LD${c.supporting_lane_id}`,cc,st==='selected'?6:4,dash,h,group,false))}const ip=infEndpoint(inf,role),cp=laneEndpoint(c);if(cp)out.push(markerTrace(cp,`${role} endpoint`,cc,h,group));if(document.getElementById('showCenterLinks').checked&&ip&&cp)out.push(lineTrace([ip,cp],`${role} center link`,cc,1,'dot',h,group,false));if(document.getElementById('showBoundaryLinks').checked){for(const side of['left','right']){const a=infBoundary(inf,role,side),b=laneBoundary(c,side);if(a&&b)out.push(lineTrace([a,b],`${role} ${side} boundary link`,cc,1,'dot',h,group,false))}}if(document.getElementById('showLabels').checked&&cp){out.push({x:[cp[0]],y:[cp[1]],type:'scatter',mode:'text',text:[`${role==='back'?'B':'F'}${index+1} ${c.track_id}<br>LD${c.supporting_lane_id} · ${st}`],textposition:'top center',textfont:{size:10,color:cc},hoverinfo:'skip',showlegend:false,legendgroup:group})}return out}
function unique(rows){const seen=new Set(),out=[];for(const c of rows){const k=key(c);if(seen.has(k))continue;seen.add(k);out.push(c)}return out}
function table(rows,res){const ranked=[...rows].sort((a,b)=>{const ar=reasons(a).length?1:0,br=reasons(b).length?1:0;return ar-br||Number(a.score)-Number(b.score)});let h='<table><thead><tr><th>track / support</th><th>center</th><th>L/R</th><th>lat</th><th>head</th><th>width</th><th>curv</th><th>score</th><th>decision</th></tr></thead><tbody>';for(const c of ranked){const rs=reasons(c),sel=same(c,res.selected),ok=!rs.length;h+=`<tr class="${sel?'sel':ok?'eligible':'rej'}"><td>${c.track_id}<br><span class=small>LD${c.supporting_lane_id} ${c.supporting_lane_endpoint_side}</span></td><td>${Number(c.center_endpoint_distance_m).toFixed(2)}</td><td>${Number(c.left_boundary_endpoint_distance_m).toFixed(2)} / ${Number(c.right_boundary_endpoint_distance_m).toFixed(2)}</td><td>${Number(c.lateral_error_m).toFixed(2)}</td><td>${Number(c.heading_difference_deg).toFixed(1)}°</td><td>${Number(c.local_width_difference_m).toFixed(2)}</td><td>${Number(c.curvature_difference_per_m).toFixed(3)}</td><td>${Number(c.score).toFixed(2)}</td><td>${sel?'SELECTED':rs.length?rs.join('<br>'):'ELIGIBLE'}</td></tr>`}return h+'</tbody></table>'}
function buildTraces(inf,backRows,frontRows,back,front){const out=[];if(document.getElementById('showBackground').checked){for(const l of D.lane_geometry){if((l.centerline_lcs_m||[]).length>1)out.push(lineTrace(l.centerline_lcs_m,`LD${l.lane_id}`,colors.background,1,'solid',`background LD${l.lane_id}`,`bg-${l.lane_id}`,false))}}out.push(polygonTrace(inf.polygon_lcs_m,`inferred ${inf.static_inferred_lane_id}`,colors.inferred,.12));out.push(lineTrace(inf.centerline_lcs_m,'inferred centerline',colors.inferred,3,'solid','inferred centerline','inferred',false));const bp=infEndpoint(inf,'back'),fp=infEndpoint(inf,'front');if(bp)out.push(markerTrace(bp,'inferred BACK',colors.backSelected,'inferred BACK endpoint','inferred'));if(fp)out.push(markerTrace(fp,'inferred FRONT',colors.frontSelected,'inferred FRONT endpoint','inferred'));if(document.getElementById('showBack').checked)unique(backRows).forEach((c,i)=>out.push(...candidateTraces(inf,c,'back',back,i)));if(document.getElementById('showFront').checked)unique(frontRows).forEach((c,i)=>out.push(...candidateTraces(inf,c,'front',front,i)));return out}
function render(resetView=false){const id=select.value,inf=inferred.get(id);if(!inf){document.getElementById('status').className='status bad';document.getElementById('status').textContent='No inferred lanes in this run.';Plotly.purge('plot');return}const d=dbg.get(id)||{},backRows=d.back_candidates||[],frontRows=d.front_candidates||[],back=choose(backRows),front=choose(frontRows),complete=!!(back.selected&&front.selected);let action='rejected';if(complete)action=String(back.selected.track_id)===String(front.selected.track_id)?'attach_to_same_track':'merge_front_back_tracks';const cur=integ.get(id)||{},s=document.getElementById('status');s.className='status '+(complete?'good':'bad');s.innerHTML=`<b>Tuned result</b><br>BACK: ${back.selected?back.selected.track_id:'—'} ${back.why?'<span class=rej>'+back.why+'</span>':''}<br>FRONT: ${front.selected?front.selected.track_id:'—'} ${front.why?'<span class=rej>'+front.why+'</span>':''}<br>bridge_complete: <b>${complete}</b><br>predicted integration: <b>${action}</b><br><span class=small>eligible BACK ${back.eligible.length} · FRONT ${front.eligible.length}</span><hr style="border:0;border-top:1px solid #d8deea"><span class=small>Python run: ${cur.accepted?'accepted':'rejected'} · ${cur.action||cur.rejection_reason||'n/a'}</span>`;document.getElementById('backTable').innerHTML=table(backRows,back);document.getElementById('frontTable').innerHTML=table(frontRows,front);const traces=buildTraces(inf,backRows,frontRows,back,front);const layout={margin:{l:45,r:20,t:25,b:40},paper_bgcolor:'#ffffff',plot_bgcolor:'#ffffff',hovermode:'closest',dragmode:'pan',showlegend:true,legend:{orientation:'v',x:1.01,y:1,font:{size:10},groupclick:'togglegroup'},xaxis:{title:'LCS x (m)',zeroline:false,gridcolor:'#edf0f5'},yaxis:{title:'LCS y (m)',zeroline:false,gridcolor:'#edf0f5',scaleanchor:'x',scaleratio:1},uirevision:resetView?String(Date.now()):'preserve-view'};Plotly.react('plot',traces,layout,{responsive:true,scrollZoom:true,displaylogo:false,modeBarButtonsToAdd:['drawline','eraseshape']})}
select.onchange=()=>render(true);for(const id of['showBack','showFront','showRejected','showBackground','showSupport','showCenterLinks','showBoundaryLinks','showLabels'])document.getElementById(id).onchange=()=>render(false);document.getElementById('reset').onclick=()=>{Object.assign(values,D.defaults);document.querySelectorAll('#controlHost .row').forEach((r,i)=>{const key=Object.keys(specs)[i];r.children[0].value=values[key];r.children[1].value=values[key]});render(false)};document.getElementById('fit').onclick=()=>render(true);document.getElementById('download').onclick=()=>{const blob=new Blob([JSON.stringify(values,null,2)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`${D.run_id}_inferred_affiliation_tuned.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),500)};render(true);
</script></body></html>'''.replace("__PLOTLY_JS__", plotly_js).replace("__DATA__", data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
