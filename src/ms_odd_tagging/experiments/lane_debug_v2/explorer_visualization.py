"""Lightweight Plotly explorer for integrated lane-debug-v2 geometry."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _boundary_range_debug(store: dict[str, Any]) -> dict[str, Any]:
    edges: dict[str, dict[str, Any]] = {}
    for collection, key in (("lane_lines", "line_id"), ("road_boundaries", "road_boundary_id")):
        for feature in store.get(collection, []):
            edge_id = feature.get(key)
            if edge_id is not None:
                edges[str(edge_id)] = feature
    result: dict[str, Any] = {}
    for lane in store.get("lanes", []):
        lane_id = str(lane.get("lane_id"))
        sides: dict[str, Any] = {}
        for side in ("left", "right"):
            boundary = (lane.get("boundaries") or {}).get(side)
            if not boundary:
                sides[side] = None
                continue
            edge_id = str(boundary.get("edge_id"))
            edge = edges.get(edge_id) or {}
            order_to_index = {e.get("order"): i for i, e in enumerate(edge.get("elements") or [])}
            start_order, end_order = boundary.get("start_order"), boundary.get("end_order")
            sides[side] = {
                "edge_id": edge_id,
                "start_order": start_order,
                "end_order": end_order,
                "start_index": order_to_index.get(start_order),
                "end_index": order_to_index.get(end_order),
                "endpoint_order_valid": bool(boundary.get("endpoint_order_valid")),
                "geometry_fallback": boundary.get("geometry_fallback"),
            }
        result[lane_id] = sides
    return result


def render_plotly_explorer(
    recording: dict[str, Any],
    following: dict[str, Any],
    lane_changes: dict[str, Any],
    path: Path,
    run_id: str,
) -> None:
    try:
        from plotly.offline import get_plotlyjs
        plotly_js = get_plotlyjs()
    except Exception as exc:
        raise RuntimeError("plotly is required") from exc

    source = {f.get("frame_index"): f for f in recording.get("frames", [])}
    store = recording.get("ld_feature_store") or {}
    points = {
        str(p.get("point_id")): p.get("position_lcs_m", [])[:2]
        for p in store.get("points", [])
        if len(p.get("position_lcs_m") or []) >= 2
    }

    raw = []
    for collection, key, kind in (
        ("lane_lines", "line_id", "lane_line"),
        ("road_boundaries", "road_boundary_id", "road_boundary"),
    ):
        for feature in store.get(collection, []):
            ids = list(feature.get("point_ids") or []) or [e.get("point_id") for e in feature.get("elements") or []]
            pts = [points[str(pid)] for pid in ids if str(pid) in points]
            if len(pts) >= 2:
                raw.append({"id": str(feature.get(key)), "kind": kind, "pts": pts})

    # Explorer frames intentionally contain only fields used by JavaScript.
    # Full detector evidence remains in lane_results JSON, not embedded in HTML.
    frames = []
    trajectory = []
    for frame in following.get("frames", []):
        src = source.get(frame.get("frame_index"), {})
        ego = src.get("ego") or {}
        ego_position = ego.get("position_lcs_m")
        if ego_position:
            trajectory.append(ego_position)
        frames.append({
            "frame_index": frame.get("frame_index"),
            "time_since_start_s": frame.get("time_since_start_s"),
            "ego_position": ego_position,
            "lane_roles": frame.get("lane_roles"),
            "inferred_ego_corridor": frame.get("inferred_ego_corridor"),
        })

    payload = {
        "run_id": run_id,
        "recording_id": following.get("recording_id"),
        "lanes": following.get("lane_geometry", []),
        "lane_boundary_ranges": _boundary_range_debug(store),
        "tracks": following.get("continuous_lane_tracks", []),
        "routes": following.get("inferred_ego_routes", []),
        "raw": raw,
        "trajectory": trajectory,
        "frames": frames,
    }
    data = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/")

    html = r'''<!doctype html>
<html><head><meta charset="utf-8"><title>Lane Debug</title><script>__PLOTLY_JS__</script>
<style>
html,body{height:100%;margin:0}body{font:13px system-ui;background:#f6f7fb;overflow:hidden}
header{padding:8px;background:#fff;position:relative;z-index:3}
#controls{display:flex;gap:9px;flex-wrap:wrap;align-items:center}
#plot{height:calc(100vh - 76px);min-height:500px}
input[type=range]{width:300px}
</style></head><body>
<header><b id="title"></b><div id="controls">
<button id="prev">◀</button><button id="play">▶ Play</button><button id="next">▶</button><button id="center">Center ego</button>
<input id="frame" type="range" min="0" step="1"><span id="label"></span>
<label><input id="follow" type="checkbox" checked>follow ego</label>
<label><input id="canonical" type="checkbox" checked>constructed lanes + fills</label>
<label><input id="bridges" type="checkbox" checked>anchored LD bridges</label>
<label><input id="selected" type="checkbox" checked>ego/adjacent</label>
<label><input id="order" type="checkbox" checked>lane-order neighbors</label>
<label><input id="raw" type="checkbox">raw LD lines</label>
<label><input id="ids" type="checkbox">track IDs + LD indices</label>
<label><input id="traj" type="checkbox" checked>ego trajectory</label>
</div></header><div id="plot"></div>
<script id="data" type="application/json">__DATA__</script><script>
const D=JSON.parse(document.getElementById('data').textContent);
const slider=document.getElementById('frame'),plot=document.getElementById('plot'),playButton=document.getElementById('play');
const laneMap=new Map(D.lanes.map(x=>[String(x.lane_id),x]));
const rangeMap=new Map(Object.entries(D.lane_boundary_ranges||{}));
const trackMap=new Map(D.tracks.map(x=>[String(x.track_id),x]));
const routeMap=new Map((D.routes||[]).map(x=>[String(x.route_id),x]));
const colors={ego:'#22c55e',left_adjacent:'#06b6d4',right_adjacent:'#f59e0b',irrelevant:'#94a3b8',bridge:'#7c3aed'};
const promotedRouteIds=new Set(D.tracks.flatMap(t=>(t.pieces||[]).filter(p=>p.kind==='ego_supported_inferred_route').map(p=>String(p.route_id))));
let timer=null,view=null,span=null,relayoutBound=false;
slider.max=Math.max(0,D.frames.length-1);
document.getElementById('title').textContent=`${D.recording_id} — integrated lane network — ${D.run_id}`;

function lineTrace(points,name,color,width=1,dash='solid'){return{x:(points||[]).map(q=>q[0]),y:(points||[]).map(q=>q[1]),mode:'lines',name,line:{color,width,dash},showlegend:false,hoverinfo:'name'};}
function polygonTrace(points,name,color,width=1,alpha='08',dash='solid'){return{...lineTrace(points,name,color,width,dash),fill:'toself',fillcolor:color+alpha};}
function fmt(v){return v===null||v===undefined?'?':String(v);}
function laneRange(id){return rangeMap.get(String(id))||{};}
function sideText(s){return s?`${fmt(s.start_index)}→${fmt(s.end_index)}`:'?→?';}
function laneRangeText(id){const r=laneRange(id);return`L[${sideText(r.left)}] R[${sideText(r.right)}]`;}
function laneRangeHover(id){const r=laneRange(id),f=(n,v)=>v?`${n}: edge=${v.edge_id} order=${fmt(v.start_order)}→${fmt(v.end_order)} index=${sideText(v)}`:`${n}: unavailable`;return`${f('left',r.left)} · ${f('right',r.right)}`;}
function anchoredPieces(t){return(t.pieces||[]).filter(p=>p.kind==='anchored_ld_bridge');}
function smoothFillPieces(t){return(t.pieces||[]).filter(p=>p.kind==='canonical_track_stitch'||p.kind==='topology_supported_curvature_stitch');}
function promotedRoutePieces(t){return(t.pieces||[]).filter(p=>p.kind==='ego_supported_inferred_route');}

function drawAnchored(out,t,color,strong=false){for(const p of anchoredPieces(t)){if((p.polygon_lcs_m||[]).length)out.push(polygonTrace(p.polygon_lcs_m,`anchored bridge · ${t.track_id}`,color,strong?2:1,strong?'20':'0c','dash'));}}
function drawFillPieces(out,t,color,strong){for(const p of smoothFillPieces(t)){const e=p.connection_evidence||{};const name=`smooth lane completion · ${t.track_id} · gap=${Number(e.endpoint_gap_m||0).toFixed(2)}m`;if((p.polygon_lcs_m||[]).length)out.push(polygonTrace(p.polygon_lcs_m,name,color,strong?2:1,strong?'20':'0b','dot'));}for(const p of promotedRoutePieces(t)){if((p.polygon_lcs_m||[]).length)out.push(polygonTrace(p.polygon_lcs_m,`ego-supported integrated gap · ${t.track_id}`,color,0,strong?'12':'06','solid'));}}
function drawTrack(out,t,role,strong,constructionOnly=false){const color=constructionOnly?colors.irrelevant:(colors[role]||colors.irrelevant);for(const id of t.member_lane_ids||[]){const lane=laneMap.get(String(id));if(!lane)continue;const rt=laneRangeText(id),hover=`${constructionOnly?'constructed':role} ${t.track_id} lane ${id} · ${laneRangeHover(id)}`;out.push(polygonTrace(lane.polygon_lcs_m,hover,color,strong?2:0.7,strong?'22':'07'));if(document.getElementById('ids').checked&&(lane.centerline_lcs_m||[]).length){const q=lane.centerline_lcs_m[Math.floor(lane.centerline_lcs_m.length/2)];out.push({x:[q[0]],y:[q[1]],mode:'text',text:[`${id} · ${rt}`],showlegend:false,hovertext:[hover],hoverinfo:'text',textfont:{size:10}});}}drawFillPieces(out,t,color,strong);if(strong)drawAnchored(out,t,color,true);if(document.getElementById('ids').checked&&(t.centerline_lcs_m||[]).length){const q=t.centerline_lcs_m[Math.floor(t.centerline_lcs_m.length/2)];out.push({x:[q[0]],y:[q[1]],mode:'text',text:[t.track_id],textposition:'top center',showlegend:false,textfont:{size:11}});}}
function roleMap(f){return new Map(((((f.lane_roles||{}).roles)||[])).map(x=>[String(x.track_id),x.role]));}
function drawUnpromotedInferred(out,f){const c=f.inferred_ego_corridor||{},rid=c.inferred_ego_route&&c.inferred_ego_route.route_id;if(!rid||promotedRouteIds.has(String(rid)))return;const r=routeMap.get(String(rid));if(!r)return;const p=(r.pieces||[]).find(x=>x.frame_index===f.frame_index);if(p&&(p.polygon_lcs_m||[]).length)out.push(polygonTrace(p.polygon_lcs_m,`unpromoted inferred ego corridor ${rid}`,colors.ego,1,'0d','dot'));}
function closestPoint(line,o){let best=null,d0=Infinity;for(const q of line||[]){const d=Math.hypot(q[0]-o[0],q[1]-o[1]);if(d<d0){d0=d;best=q;}}return best;}
function drawOrder(out,f){if(!document.getElementById('order').checked)return;const cs=f.lane_roles&&f.lane_roles.cross_section;if(!cs||!cs.point)return;out.push({x:[cs.point[0]],y:[cs.point[1]],mode:'markers',marker:{size:8,color:'#111827'},showlegend:false,hovertext:'static lane-order cross-section',hoverinfo:'text'});for(const side of['left','right']){const c=cs[side];if(!c||!c.track_id)continue;const t=trackMap.get(String(c.track_id));if(!t)continue;const q=closestPoint(t.centerline_lcs_m||[],cs.point);if(q)out.push(lineTrace([cs.point,q],`${side} immediate neighbor`,side==='left'?colors.left_adjacent:colors.right_adjacent,2,'dot'));}}
function stop(){if(timer)clearInterval(timer);timer=null;playButton.textContent='▶ Play';}
function play(){if(timer){stop();return;}playButton.textContent='❚❚ Pause';timer=setInterval(()=>{if(+slider.value>=D.frames.length-1){stop();return;}slider.value=+slider.value+1;draw();},100);}

function draw(){const f=D.frames[+slider.value]||{},ego=f.ego_position||[0,0],out=[],roles=roleMap(f);if(document.getElementById('raw').checked)for(const r of D.raw)out.push(lineTrace(r.pts,`${r.kind} ${r.id}`,'#cbd5e1',0.7));if(document.getElementById('canonical').checked)for(const t of D.tracks)drawTrack(out,t,'irrelevant',false,true);if(document.getElementById('bridges').checked)for(const t of D.tracks)drawAnchored(out,t,colors.bridge,false);if(document.getElementById('selected').checked){for(const t of D.tracks){const role=roles.get(String(t.track_id));if(role&&role!=='irrelevant')drawTrack(out,t,role,true,false);}drawUnpromotedInferred(out,f);}drawOrder(out,f);if(document.getElementById('traj').checked)out.push(lineTrace(D.trajectory,'ego trajectory','#111827',1.2));out.push({x:[ego[0]],y:[ego[1]],mode:'markers+text',text:['EGO'],textposition:'top center',marker:{size:13,color:colors.ego,symbol:'triangle-up'},showlegend:false});const follow=document.getElementById('follow').checked,xs=span?span.x:110,ys=span?span.y:110;const xr=follow?[ego[0]-xs/2,ego[0]+xs/2]:(view?view.x:[ego[0]-55,ego[0]+55]);const yr=follow?[ego[1]-ys/2,ego[1]+ys/2]:(view?view.y:[ego[1]-55,ego[1]+55]);Plotly.react(plot,out,{margin:{l:35,r:10,t:10,b:35},xaxis:{scaleanchor:'y',scaleratio:1,range:xr},yaxis:{range:yr},uirevision:'integrated-lane-network'},{responsive:true,displaylogo:false}).then(()=>{if(!relayoutBound){plot.on('plotly_relayout',e=>{const x0=e['xaxis.range[0]'],x1=e['xaxis.range[1]'],y0=e['yaxis.range[0]'],y1=e['yaxis.range[1]'];if([x0,x1,y0,y1].every(Number.isFinite)){view={x:[x0,x1],y:[y0,y1]};span={x:Math.abs(x1-x0),y:Math.abs(y1-y0)};}});relayoutBound=true;}}).catch(e=>console.error('Plotly render failed',e));document.getElementById('label').textContent=`frame ${f.frame_index} · ${Number(f.time_since_start_s||0).toFixed(2)}s`;}
for(const id of['follow','canonical','bridges','selected','order','raw','ids','traj'])document.getElementById(id).onchange=draw;
slider.oninput=()=>{stop();draw();};
document.getElementById('prev').onclick=()=>{stop();slider.value=Math.max(0,+slider.value-1);draw();};
document.getElementById('next').onclick=()=>{stop();slider.value=Math.min(D.frames.length-1,+slider.value+1);draw();};
document.getElementById('center').onclick=()=>{view=null;span=null;draw();};
playButton.onclick=play;draw();
</script></body></html>'''

    html = html.replace("__PLOTLY_JS__", plotly_js).replace("__DATA__", data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
