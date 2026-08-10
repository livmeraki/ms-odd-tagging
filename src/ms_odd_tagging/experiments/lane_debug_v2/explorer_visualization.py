"""Standalone Plotly explorer for lane-debug v2 continuous-track debugging."""
from __future__ import annotations
import json, math
from pathlib import Path
from typing import Any


def _polyline_length(points: list[list[float]]) -> float:
    return round(sum(math.hypot(float(b[0])-float(a[0]),float(b[1])-float(a[1])) for a,b in zip(points,points[1:]) if len(a)>=2 and len(b)>=2),3)


def render_plotly_explorer(recording: dict[str,Any], following: dict[str,Any], lane_changes: dict[str,Any], path: Path, run_id: str) -> None:
    try:
        from plotly.offline import get_plotlyjs
        plotly_js=get_plotlyjs()
    except Exception as exc:
        raise RuntimeError("plotly is required to generate the lane-debug-v2 explorer") from exc
    source={f["frame_index"]:f for f in recording.get("frames",[])}
    store=recording.get("ld_feature_store") or {}
    point_lookup={str(p["point_id"]):p.get("position_lcs_m",[])[:2] for p in store.get("points",[]) if len(p.get("position_lcs_m") or [])>=2}
    edge_lookup={}
    raw=[]
    for collection,id_key,kind in (("lane_lines","line_id","lane_line"),("road_boundaries","road_boundary_id","road_boundary")):
        for feat in store.get(collection,[]):
            eid=str(feat.get(id_key)); pts=[point_lookup[str(pid)] for pid in feat.get("point_ids",[]) if str(pid) in point_lookup]
            raw.append({"id":eid,"kind":kind,"pts":pts}); edge_lookup[eid]={**feat,"edge_kind":kind,"pts":pts}
    reconstructed={str(l.get("lane_id")):l for l in following.get("lane_geometry",[])}
    boundary_debug={}
    for lane in store.get("lanes",[]):
        lid=str(lane.get("lane_id")); rec=reconstructed.get(lid,{})
        sides={}
        for side in ("left","right"):
            ref=(lane.get("boundaries") or {}).get(side) or {}; eid=str(ref.get("edge_id")) if ref.get("edge_id") is not None else None; edge=edge_lookup.get(eid or "")
            full=list(edge.get("pts",[])) if edge else []; selected=[]
            if edge and ref.get("endpoint_order_valid"):
                elements=edge.get("elements") or []; order_to_index={x.get("order"):i for i,x in enumerate(elements)}; a=order_to_index.get(ref.get("start_order")); b=order_to_index.get(ref.get("end_order"))
                if a is not None and b is not None:
                    step=1 if b>=a else -1
                    selected=[point_lookup[str(elements[i].get("point_id"))] for i in range(a,b+step,step) if str(elements[i].get("point_id")) in point_lookup]
            used=list(rec.get("left_boundary_lcs_m" if side=="left" else "right_boundary_lcs_m",[]) or [])
            sides[side]={"edge_id":eid,"start_order":ref.get("start_order"),"end_order":ref.get("end_order"),"endpoint_order_valid":ref.get("endpoint_order_valid"),"geometry_fallback":ref.get("geometry_fallback"),"full_edge_pts":full,"canonical_range_pts":selected,"detector_used_pts":used,"full_edge_length_m":_polyline_length(full),"canonical_range_length_m":_polyline_length(selected),"detector_used_length_m":_polyline_length(used)}
        boundary_debug[lid]={"lane_id":lid,"detector_assignment_valid":rec.get("assignment_valid"),"detector_invalid_reason":rec.get("invalid_reason"),"geometry_recovered":rec.get("geometry_recovered"),"recovery_method":rec.get("recovery_method"),"left":sides["left"],"right":sides["right"]}
    frames=[]
    for item in following.get("frames",[]):
        src=source.get(item["frame_index"],{}); ego=src.get("ego") or {}; by_id={str(o.get("object_id")):o for o in item.get("objects",[])}
        objects=[]
        for obj in src.get("objects",[]):
            oid=str(obj.get("object_id")); dbg=by_id.get(oid,{})
            objects.append({"id":oid,"class":obj.get("class"),"p":obj.get("position_lcs_m"),"heading":dbg.get("object_motion_heading_rad"),"dbg":dbg})
        frames.append({**item,"ego_position":ego.get("position_lcs_m"),"ego_heading":ego.get("heading_lcs_rad"),"source_objects":objects})
    payload={"run_id":run_id,"recording_id":following.get("recording_id"),"lanes":following.get("lane_geometry",[]),"tracks":following.get("continuous_lane_tracks",[]),"connections":following.get("continuous_track_connection_debug",[]),"raw_ld":raw,"boundary_debug":boundary_debug,"frames":frames,"lane_changes":lane_changes}
    data=json.dumps(payload,ensure_ascii=True,separators=(",",":")).replace("</","<\\/")
    html=f'''<!doctype html><html><head><meta charset="utf-8"><title>Lane Debug v2</title><script>{plotly_js}</script><style>body{{font:13px system-ui;margin:0;background:#f6f7fb;color:#172033}}header{{padding:10px 14px;background:#fff;border-bottom:1px solid #ddd;position:sticky;top:0;z-index:4}}#controls{{display:flex;flex-wrap:wrap;gap:9px;align-items:center}}#plot{{height:72vh}}#panel{{background:#fff;padding:10px 14px;white-space:pre-wrap;font-family:ui-monospace,monospace;max-height:24vh;overflow:auto;border-top:1px solid #ddd}}input[type=range]{{width:320px}}</style></head><body><header><b id="title"></b><div id="controls"><button id="prev">◀</button><button id="play">▶ Play</button><button id="next">▶</button><input id="frame" type="range" min="0" step="1"><span id="frameLabel"></span><label><input id="followEgo" type="checkbox" checked>follow ego</label><label><input id="raw" type="checkbox">raw LD</label><label><input id="segments" type="checkbox" checked>raw reconstructed segments</label><label><input id="tracks" type="checkbox" checked>continuous tracks</label><label><input id="laneFill" type="checkbox">lane fill</label><label><input id="trackPieces" type="checkbox" checked>track pieces/gaps</label><label><input id="segmentComparison" type="checkbox">segment adjacency comparison</label><label><input id="fullEdges" type="checkbox">full referenced edges</label><label><input id="canonicalRanges" type="checkbox">canonical ranges</label><label><input id="usedBoundaries" type="checkbox">detector boundaries</label><label><input id="objects" type="checkbox" checked>objects</label><label><input id="trajectory" type="checkbox" checked>ego trajectory</label><label><input id="debugText" type="checkbox" checked>debug text</label></div></header><div id="plot"></div><div id="panel"></div><script id="payload" type="application/json">{data}</script><script>
const D=JSON.parse(document.getElementById('payload').textContent),slider=document.getElementById('frame'),plot=document.getElementById('plot'),playButton=document.getElementById('play');slider.max=D.frames.length-1;document.getElementById('title').textContent=`${{D.recording_id}} — continuous lane-track debug — run ${{D.run_id}}`;let viewState=null,viewSize=null,bound=false,timer=null;
const C={{ego:'#22c55e',left:'#06b6d4',right:'#f59e0b',other:'#94a3b8',gap:'#dc2626',segment:'#a78bfa'}};
function line(pts,name,color,width=1.5,dash='solid'){{return{{x:(pts||[]).map(p=>p[0]),y:(pts||[]).map(p=>p[1]),mode:'lines',name,line:{{color,width,dash}},showlegend:false,hoverinfo:'name'}}}}
function poly(pts,name,color){{const fillOn=document.getElementById('laneFill')?.checked;return{{x:(pts||[]).map(p=>p[0]),y:(pts||[]).map(p=>p[1]),mode:'lines',name,line:{{color,width:1}},fill:fillOn?'toself':'none',fillcolor:fillOn?color+'10':'rgba(0,0,0,0)',showlegend:false,hoverinfo:'name'}}}}
function remember(ev){{const x0=ev['xaxis.range[0]'],x1=ev['xaxis.range[1]'],y0=ev['yaxis.range[0]'],y1=ev['yaxis.range[1]'];if([x0,x1,y0,y1].every(Number.isFinite)){{viewState={{x:[x0,x1],y:[y0,y1]}};viewSize={{x:Math.abs(x1-x0),y:Math.abs(y1-y0)}}}}if(ev['xaxis.autorange']===true||ev['yaxis.autorange']===true){{viewState=null;viewSize=null}}}}
function stop(){{if(timer!==null){{clearInterval(timer);timer=null}}playButton.textContent='▶ Play'}}function play(){{if(timer!==null){{stop();return}}if(+slider.value>=D.frames.length-1)slider.value=0;playButton.textContent='❚❚ Pause';timer=setInterval(()=>{{if(+slider.value>=D.frames.length-1){{stop();return}}slider.value=+slider.value+1;draw()}},100)}}
function physicalRoles(f){{const m=new Map();if(f.ego_lane?.lane_id)m.set(String(f.ego_lane.lane_id),'ego');if(f.left_lane?.lane_id)m.set(String(f.left_lane.lane_id),'left');if(f.right_lane?.lane_id)m.set(String(f.right_lane.lane_id),'right');return m}}function trackRoles(f){{const m=new Map();if(f.continuous_ego_track?.track_id)m.set(String(f.continuous_ego_track.track_id),'ego');if(f.continuous_adjacency?.left?.track_id)m.set(String(f.continuous_adjacency.left.track_id),'left');if(f.continuous_adjacency?.right?.track_id)m.set(String(f.continuous_adjacency.right.track_id),'right');return m}}
function draw(){{const f=D.frames[+slider.value],t=[],ep=f.ego_position||[0,0],proles=physicalRoles(f),troles=trackRoles(f);if(document.getElementById('raw').checked)for(const r of D.raw_ld)if(r.pts.length>1)t.push(line(r.pts,`${{r.kind}} ${{r.id}}`,'#cbd5e1',0.8));if(document.getElementById('segments').checked)for(const l of D.lanes){{const role=proles.get(String(l.lane_id));if(role)t.push(poly(l.polygon_lcs_m,`segment ${{l.lane_id}} (${{role}})`,C[role]));else if(document.getElementById('segmentComparison').checked)t.push(line(l.centerline_lcs_m,`segment ${{l.lane_id}}`,C.segment,0.8,'dot'))}}
if(document.getElementById('tracks').checked)for(const tr of D.tracks){{const role=troles.get(String(tr.track_id));if(!role)continue;t.push(poly(tr.polygon_lcs_m,`${{role}} track ${{tr.track_id}} members=${{tr.member_lane_ids.join(',')}}`,C[role]));t.push(line(tr.centerline_lcs_m,`${{role}} track centerline ${{tr.track_id}}`,C[role],1.8));if(document.getElementById('trackPieces').checked)for(const p of tr.pieces||[]){{const color=p.kind==='inferred_gap'?C.gap:(p.kind==='recovered_full_edge'?'#f59e0b':'#334155');t.push(line(p.centerline_lcs_m,`${{tr.track_id}} ${{p.kind}}`,color,p.kind==='inferred_gap'?2:1,p.kind==='inferred_gap'?'dash':'solid'))}}}}
if(document.getElementById('trajectory').checked)t.push(line(D.frames.filter(x=>x.ego_position).map(x=>x.ego_position),'ego trajectory','#111827',1.2));for(const [laneId,role] of proles.entries()){{const dbg=D.boundary_debug?.[laneId];if(!dbg)continue;for(const side of ['left','right']){{const b=dbg[side];if(document.getElementById('fullEdges').checked)t.push(line(b.full_edge_pts,`${{side}} full edge ${{b.edge_id}}`,'#475569',1.5,'dot'));if(document.getElementById('canonicalRanges').checked)t.push(line(b.canonical_range_pts,`${{side}} range ${{b.start_order}}→${{b.end_order}}`,C[role],1.5,'dash'));if(document.getElementById('usedBoundaries').checked)t.push(line(b.detector_used_pts,`${{side}} detector used`,C[role],1.5))}}}}
t.push({{x:[ep[0]],y:[ep[1]],mode:'markers+text',text:['EGO'],textposition:'top center',marker:{{size:13,color:C.ego,symbol:'triangle-up'}},showlegend:false}});if(document.getElementById('objects').checked)for(const o of f.source_objects)if(o.p?.length>=2)t.push({{x:[o.p[0]],y:[o.p[1]],mode:'markers+text',text:[o.id],textposition:'top center',marker:{{size:9}},showlegend:false,hovertext:JSON.stringify(o.dbg),hoverinfo:'text'}});
const half=55,follow=document.getElementById('followEgo').checked,sx=viewSize?.x??half*2,sy=viewSize?.y??half*2,xr=follow?[ep[0]-sx/2,ep[0]+sx/2]:(viewState?.x||[ep[0]-half,ep[0]+half]),yr=follow?[ep[1]-sy/2,ep[1]+sy/2]:(viewState?.y||[ep[1]-half,ep[1]+half]);Plotly.react(plot,t,{{margin:{{l:40,r:15,t:15,b:40}},xaxis:{{scaleanchor:'y',scaleratio:1,range:xr}},yaxis:{{range:yr}},uirevision:'lane-track-debug'}},{{responsive:true,displaylogo:false}}).then(()=>{{if(!bound){{plot.on('plotly_relayout',remember);bound=true}}}});document.getElementById('frameLabel').textContent=`frame ${{f.frame_index}} · ${{Number(f.time_since_start_s).toFixed(2)}}s`;const panel={{frame_index:f.frame_index,continuous_ego_track:f.continuous_ego_track,continuous_adjacency:f.continuous_adjacency,segment_ego_lane:f.segment_ego_lane,segment_left_lane:f.segment_left_lane,segment_right_lane:f.segment_right_lane,primary_ego_lane:f.ego_lane,primary_left_lane:f.left_lane,primary_right_lane:f.right_lane}};document.getElementById('panel').style.display=document.getElementById('debugText').checked?'block':'none';document.getElementById('panel').textContent=JSON.stringify(panel,null,2)}}
for(const id of ['followEgo','raw','segments','tracks','laneFill','trackPieces','segmentComparison','fullEdges','canonicalRanges','usedBoundaries','objects','trajectory','debugText'])document.getElementById(id).onchange=draw;slider.oninput=()=>{{stop();draw()}};document.getElementById('prev').onclick=()=>{{stop();slider.value=Math.max(0,+slider.value-1);draw()}};document.getElementById('next').onclick=()=>{{stop();slider.value=Math.min(D.frames.length-1,+slider.value+1);draw()}};playButton.onclick=play;draw();</script></body></html>'''
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(html,encoding="utf-8")
