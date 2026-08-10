"""Plotly explorer for canonical tracks, anchored LD bridges, and static lane ordering."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def render_plotly_explorer(recording: dict[str, Any], following: dict[str, Any], lane_changes: dict[str, Any], path: Path, run_id: str) -> None:
    try:
        from plotly.offline import get_plotlyjs
        plotly_js = get_plotlyjs()
    except Exception as exc:
        raise RuntimeError("plotly is required") from exc

    source = {f.get("frame_index"): f for f in recording.get("frames", [])}
    store = recording.get("ld_feature_store") or {}
    points = {str(p.get("point_id")): p.get("position_lcs_m", [])[:2] for p in store.get("points", []) if len(p.get("position_lcs_m") or []) >= 2}
    raw = []
    for collection, key, kind in (("lane_lines", "line_id", "lane_line"), ("road_boundaries", "road_boundary_id", "road_boundary")):
        for feature in store.get(collection, []):
            ids = list(feature.get("point_ids") or []) or [e.get("point_id") for e in feature.get("elements") or []]
            pts = [points[str(pid)] for pid in ids if str(pid) in points]
            if len(pts) >= 2:
                raw.append({"id": str(feature.get(key)), "kind": kind, "pts": pts})
    frames = []
    for frame in following.get("frames", []):
        src = source.get(frame.get("frame_index"), {})
        ego = src.get("ego") or {}
        frames.append({**frame, "ego_position": ego.get("position_lcs_m"), "ego_heading": ego.get("heading_lcs_rad")})
    payload = {
        "run_id": run_id,
        "recording_id": following.get("recording_id"),
        "lanes": following.get("lane_geometry", []),
        "tracks": following.get("continuous_lane_tracks", []),
        "network": following.get("constructed_lane_network", {}),
        "lane_order": following.get("static_lane_order_topology", {}),
        "canonical_track_count": following.get("canonical_continuous_lane_track_count", 0),
        "bridge_track_count": following.get("anchored_ld_bridge_track_count", 0),
        "bridge_debug": following.get("anchored_ld_bridge_debug", []),
        "routes": following.get("inferred_ego_routes", []),
        "raw": raw,
        "frames": frames,
    }
    data = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/")
    html = f'''<!doctype html><html><head><meta charset="utf-8"><title>Lane Debug</title><script>{plotly_js}</script><style>body{{font:13px system-ui;margin:0;background:#f6f7fb}}header{{padding:8px;background:#fff;position:sticky;top:0;z-index:3}}#controls{{display:flex;gap:9px;flex-wrap:wrap;align-items:center}}#plot{{height:73vh}}#panel{{height:22vh;overflow:auto;white-space:pre-wrap;background:#fff;padding:8px;font-family:monospace}}input[type=range]{{width:300px}}</style></head><body><header><b id="title"></b><div id="controls"><button id="prev">◀</button><button id="play">▶ Play</button><button id="next">▶</button><button id="center">Center ego</button><input id="frame" type="range" min="0" step="1"><span id="label"></span><label><input id="follow" type="checkbox" checked>follow ego</label><label><input id="canonical" type="checkbox" checked>canonical tracks</label><label><input id="bridges" type="checkbox" checked>anchored LD bridges</label><label><input id="selected" type="checkbox" checked>ego/adjacent roles</label><label><input id="order" type="checkbox" checked>lane-order neighbors</label><label><input id="raw" type="checkbox">raw LD lines</label><label><input id="corridor" type="checkbox" checked>inferred ego corridor</label><label><input id="route" type="checkbox" checked>connected inferred route</label><label><input id="ids" type="checkbox">track IDs</label><label><input id="traj" type="checkbox" checked>ego trajectory</label></div></header><div id="plot"></div><div id="panel"></div><script id="data" type="application/json">{data}</script><script>
const D=JSON.parse(document.getElementById('data').textContent),s=document.getElementById('frame'),p=document.getElementById('plot'),pb=document.getElementById('play');s.max=Math.max(0,D.frames.length-1);document.getElementById('title').textContent=`${{D.recording_id}} — static lane order — ${{D.run_id}}`;
const laneMap=new Map(D.lanes.map(x=>[String(x.lane_id),x]));const col={{ego:'#22c55e',left_adjacent:'#06b6d4',right_adjacent:'#f59e0b',irrelevant:'#94a3b8',corridor:'#16a34a',bridge:'#7c3aed'}};let timer=null,view=null,span=null,bound=false;
function ln(a,n,c,w=1,d='solid'){{return{{x:(a||[]).map(q=>q[0]),y:(a||[]).map(q=>q[1]),mode:'lines',name:n,line:{{color:c,width:w,dash:d}},showlegend:false,hoverinfo:'name'}}}}function pg(a,n,c,w=1,alpha='08',d='solid'){{return{{...ln(a,n,c,w,d),fill:'toself',fillcolor:c+alpha}}}}
function isBridge(tr){{return tr.source==='anchored_ld_bridge'}}
function drawTrack(out,tr,role,strong,constructionOnly=false){{const c=constructionOnly?(isBridge(tr)?col.bridge:col.irrelevant):(col[role]||col.irrelevant);let rendered=false;for(const id of tr.member_lane_ids||[]){{const l=laneMap.get(String(id));if(!l)continue;rendered=true;out.push(pg(l.polygon_lcs_m,`${{constructionOnly?'constructed':role}} ${{tr.track_id}} lane ${{id}}`,c,strong?2:0.7,strong?'22':'07'));out.push(ln(l.left_boundary_lcs_m,`${{id}} left`,c,strong?1.6:0.6));out.push(ln(l.right_boundary_lcs_m,`${{id}} right`,c,strong?1.6:0.6))}}if(!rendered&&(tr.polygon_lcs_m||[]).length){{out.push(pg(tr.polygon_lcs_m,`${{constructionOnly?'anchored bridge':role}} ${{tr.track_id}}`,c,strong?2:1,strong?'22':'0c','dash'));if((tr.left_boundary_lcs_m||[]).length)out.push(ln(tr.left_boundary_lcs_m,`${{tr.track_id}} left boundary ${{tr.left_boundary_id||''}}`,c,strong?1.8:1,'dash'));if((tr.right_boundary_lcs_m||[]).length)out.push(ln(tr.right_boundary_lcs_m,`${{tr.track_id}} right boundary ${{tr.right_boundary_id||''}}`,c,strong?1.8:1,'dash'))}}if(document.getElementById('ids').checked&&(tr.centerline_lcs_m||[]).length){{const q=tr.centerline_lcs_m[Math.floor(tr.centerline_lcs_m.length/2)];out.push({{x:[q[0]],y:[q[1]],mode:'text',text:[tr.track_id],showlegend:false}})}}}}
function roleMap(f){{return new Map((f.lane_roles?.roles||[]).map(x=>[String(x.track_id),x.role]))}}function stop(){{if(timer)clearInterval(timer);timer=null;pb.textContent='▶ Play'}}function play(){{if(timer){{stop();return}}pb.textContent='❚❚ Pause';timer=setInterval(()=>{{if(+s.value>=D.frames.length-1){{stop();return}}s.value=+s.value+1;draw()}},100)}}
function draw(){{const f=D.frames[+s.value]||{{}},ego=f.ego_position||[0,0],out=[],roles=roleMap(f);if(document.getElementById('raw').checked)for(const r of D.raw)out.push(ln(r.pts,`${{r.kind}} ${{r.id}}`,'#cbd5e1',0.7));for(const tr of D.tracks){{if(!isBridge(tr)&&document.getElementById('canonical').checked)drawTrack(out,tr,'irrelevant',false,true);if(isBridge(tr)&&document.getElementById('bridges').checked)drawTrack(out,tr,'irrelevant',false,true)}}if(document.getElementById('selected').checked)for(const tr of D.tracks){{const role=roles.get(String(tr.track_id));if(role&&role!=='irrelevant')drawTrack(out,tr,role,true,false)}}
if(document.getElementById('order').checked){{const cs=f.lane_roles?.cross_section;if(cs?.point){{out.push({{x:[cs.point[0]],y:[cs.point[1]],mode:'markers',marker:{{size:8,color:'#111827'}},showlegend:false,hovertext:'static lane-order cross-section',hoverinfo:'text'}});for(const side of ['left','right']){{const c=cs[side];if(c?.track_id){{const tr=D.tracks.find(x=>String(x.track_id)===String(c.track_id));if(tr?.centerline_lcs_m?.length){{const q=tr.centerline_lcs_m.reduce((a,b)=>Math.hypot(b[0]-cs.point[0],b[1]-cs.point[1])<Math.hypot(a[0]-cs.point[0],a[1]-cs.point[1])?b:a);out.push(ln([cs.point,q],`${{side}} immediate neighbor`,side==='left'?col.left_adjacent:col.right_adjacent,2,'dot'))}}}}}}}}
const c=f.inferred_ego_corridor||{{}};if(document.getElementById('corridor').checked&&c.valid){{out.push(pg(c.polygon_lcs_m,'current inferred ego corridor',col.corridor,2,'18','dash'));out.push(ln(c.left_boundary_lcs_m,`left boundary ${{c.left_boundary_id}}`,col.corridor,3));out.push(ln(c.right_boundary_lcs_m,`right boundary ${{c.right_boundary_id}}`,col.corridor,3))}}if(document.getElementById('route').checked){{const rid=c.inferred_ego_route?.route_id;const r=(D.routes||[]).find(x=>x.route_id===rid);if(r)for(const piece of r.pieces||[])if(piece.frame_index<=f.frame_index)out.push(pg(piece.polygon_lcs_m,`${{rid}} @${{piece.frame_index}}`,col.corridor,0.8,'08','dash'))}}
if(document.getElementById('traj').checked)out.push(ln(D.frames.filter(x=>x.ego_position).map(x=>x.ego_position),'ego trajectory','#111827',1.2));out.push({{x:[ego[0]],y:[ego[1]],mode:'markers+text',text:['EGO'],textposition:'top center',marker:{{size:13,color:col.ego,symbol:'triangle-up'}},showlegend:false}});const follow=document.getElementById('follow').checked,h=55,sx=span?.x??110,sy=span?.y??110,xr=follow?[ego[0]-sx/2,ego[0]+sx/2]:(view?.x||[ego[0]-h,ego[0]+h]),yr=follow?[ego[1]-sy/2,ego[1]+sy/2]:(view?.y||[ego[1]-h,ego[1]+h]);Plotly.react(p,out,{{margin:{{l:35,r:10,t:10,b:35}},xaxis:{{scaleanchor:'y',scaleratio:1,range:xr}},yaxis:{{range:yr}},uirevision:'static-lane-order'}},{{responsive:true,displaylogo:false}}).then(()=>{{if(!bound){{p.on('plotly_relayout',e=>{{const a=e['xaxis.range[0]'],b=e['xaxis.range[1]'],c=e['yaxis.range[0]'],d=e['yaxis.range[1]'];if([a,b,c,d].every(Number.isFinite)){{view={{x:[a,b],y:[c,d]}};span={{x:Math.abs(b-a),y:Math.abs(d-c)}}}}}});bound=true}}}});document.getElementById('label').textContent=`frame ${{f.frame_index}} · ${{Number(f.time_since_start_s||0).toFixed(2)}}s`;document.getElementById('panel').textContent=JSON.stringify({{ego_lane:f.ego_lane,lane_roles:f.lane_roles,inferred_ego_corridor:f.inferred_ego_corridor,constructed_lane_count:D.network?.lane_count,canonical_track_count:D.canonical_track_count,anchored_bridge_count:D.bridge_track_count,anchored_bridge_debug:D.bridge_debug,frame_local_adjacency_debug:f.frame_local_adjacency_debug}},null,2)}}
for(const id of ['follow','canonical','bridges','selected','order','raw','corridor','route','ids','traj'])document.getElementById(id).onchange=draw;s.oninput=()=>{{stop();draw()}};document.getElementById('prev').onclick=()=>{{stop();s.value=Math.max(0,+s.value-1);draw()}};document.getElementById('next').onclick=()=>{{stop();s.value=Math.min(D.frames.length-1,+s.value+1);draw()}};document.getElementById('center').onclick=()=>{{view=null;span=null;draw()}};pb.onclick=play;draw();
</script></body></html>'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
