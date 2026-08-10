"""Standalone Plotly explorer for lane-debug v2.

Detected continuous lanes are rendered from their exact member polygons, never
from the synthetic merged-track corridor. Boundary-inferred ego corridors are
shown directly from the selected physical left/right boundary lines.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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
        raise RuntimeError("plotly is required to generate the lane-debug-v2 explorer") from exc

    source_by_frame = {f.get("frame_index"): f for f in recording.get("frames", [])}
    store = recording.get("ld_feature_store") or {}
    point_lookup = {
        str(p.get("point_id")): p.get("position_lcs_m", [])[:2]
        for p in store.get("points", [])
        if len(p.get("position_lcs_m") or []) >= 2
    }
    raw_ld = []
    for collection, id_key, kind in (
        ("lane_lines", "line_id", "lane_line"),
        ("road_boundaries", "road_boundary_id", "road_boundary"),
    ):
        for feature in store.get(collection, []):
            point_ids = list(feature.get("point_ids") or [])
            if not point_ids:
                point_ids = [item.get("point_id") for item in feature.get("elements") or []]
            pts = [point_lookup[str(pid)] for pid in point_ids if str(pid) in point_lookup]
            if len(pts) >= 2:
                raw_ld.append({"id": str(feature.get(id_key)), "kind": kind, "pts": pts})

    frames = []
    for frame in following.get("frames", []):
        source = source_by_frame.get(frame.get("frame_index"), {})
        ego = source.get("ego") or {}
        object_debug = {str(o.get("object_id")): o for o in frame.get("objects", [])}
        objects = []
        for obj in source.get("objects", []):
            oid = str(obj.get("object_id"))
            objects.append({
                "id": oid,
                "class": obj.get("class"),
                "p": obj.get("position_lcs_m"),
                "dbg": object_debug.get(oid, {}),
            })
        frames.append({
            **frame,
            "ego_position": ego.get("position_lcs_m"),
            "ego_heading": ego.get("heading_lcs_rad"),
            "source_objects": objects,
        })

    payload = {
        "run_id": run_id,
        "recording_id": following.get("recording_id"),
        "lanes": following.get("lane_geometry", []),
        "tracks": following.get("continuous_lane_tracks", []),
        "track_adjacency_graph": following.get("track_adjacency_graph", {}),
        "raw_ld": raw_ld,
        "frames": frames,
        "lane_changes": lane_changes,
    }
    data = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/")

    html = f'''<!doctype html><html><head><meta charset="utf-8"><title>Lane Debug v2</title><script>{plotly_js}</script><style>
body{{font:13px system-ui;margin:0;background:#f6f7fb;color:#172033}}header{{padding:8px 12px;background:#fff;border-bottom:1px solid #ddd;position:sticky;top:0;z-index:4}}#controls{{display:flex;flex-wrap:wrap;gap:9px;align-items:center}}#plot{{height:73vh}}#panel{{background:#fff;padding:10px 14px;white-space:pre-wrap;font-family:ui-monospace,monospace;max-height:23vh;overflow:auto;border-top:1px solid #ddd}}input[type=range]{{width:320px}}</style></head><body>
<header><b id="title"></b><div id="controls"><button id="prev">◀</button><button id="play">▶ Play</button><button id="next">▶</button><button id="center">Center ego</button><input id="frame" type="range" min="0" step="1"><span id="frameLabel"></span>
<label><input id="followEgo" type="checkbox" checked>follow ego</label><label><input id="raw" type="checkbox">raw LD</label><label><input id="lanes" type="checkbox" checked>detected lanes</label><label><input id="corridor" type="checkbox" checked>inferred ego corridor</label><label><input id="laneIds" type="checkbox" checked>lane IDs</label><label><input id="gaps" type="checkbox" checked>inferred gaps</label><label><input id="allSegments" type="checkbox">all reconstructed segments</label><label><input id="objects" type="checkbox" checked>objects</label><label><input id="trajectory" type="checkbox" checked>ego trajectory</label><label><input id="debugText" type="checkbox" checked>debug text</label></div></header>
<div id="plot"></div><div id="panel"></div><script id="payload" type="application/json">{data}</script><script>
const D=JSON.parse(document.getElementById('payload').textContent),slider=document.getElementById('frame'),plot=document.getElementById('plot'),playButton=document.getElementById('play');slider.max=Math.max(0,D.frames.length-1);document.getElementById('title').textContent=`${{D.recording_id}} — lane debug v2 — run ${{D.run_id}}`;
const C={{ego:'#22c55e',left:'#06b6d4',right:'#f59e0b',segment:'#a78bfa',raw:'#cbd5e1',corridor:'#16a34a'}};const laneById=new Map(D.lanes.map(l=>[String(l.lane_id),l]));const trackById=new Map(D.tracks.map(t=>[String(t.track_id),t]));let viewState=null,viewSize=null,bound=false,timer=null;
function line(pts,name,color,width=1.5,dash='solid'){{return{{x:(pts||[]).map(p=>p[0]),y:(pts||[]).map(p=>p[1]),mode:'lines',name,line:{{color,width,dash}},showlegend:false,hoverinfo:'name'}}}}
function poly(pts,name,color,dash='solid',alpha='22'){{return{{x:(pts||[]).map(p=>p[0]),y:(pts||[]).map(p=>p[1]),mode:'lines',name,line:{{color,width:2,dash}},fill:'toself',fillcolor:color+alpha,showlegend:false,hoverinfo:'name'}}}}
function remember(ev){{const x0=ev['xaxis.range[0]'],x1=ev['xaxis.range[1]'],y0=ev['yaxis.range[0]'],y1=ev['yaxis.range[1]'];if([x0,x1,y0,y1].every(Number.isFinite)){{viewState={{x:[x0,x1],y:[y0,y1]}};viewSize={{x:Math.abs(x1-x0),y:Math.abs(y1-y0)}}}}if(ev['xaxis.autorange']===true||ev['yaxis.autorange']===true){{viewState=null;viewSize=null}}}}
function stop(){{if(timer!==null){{clearInterval(timer);timer=null}}playButton.textContent='▶ Play'}}function play(){{if(timer!==null){{stop();return}}if(+slider.value>=D.frames.length-1)slider.value=0;playButton.textContent='❚❚ Pause';timer=setInterval(()=>{{if(+slider.value>=D.frames.length-1){{stop();return}}slider.value=+slider.value+1;draw()}},100)}}
function roles(f){{const m=new Map();if(f.continuous_ego_track?.track_id)m.set(String(f.continuous_ego_track.track_id),'ego');if(f.continuous_adjacency?.left?.track_id)m.set(String(f.continuous_adjacency.left.track_id),'left');if(f.continuous_adjacency?.right?.track_id)m.set(String(f.continuous_adjacency.right.track_id),'right');return m}}
function drawTrack(t,track,role){{const color=C[role];for(const memberId of track.member_lane_ids||[]){{const lane=laneById.get(String(memberId));if(!lane)continue;t.push(poly(lane.polygon_lcs_m,`${{role}} member lane ${{memberId}} · ${{track.track_id}}`,color));t.push(line(lane.left_boundary_lcs_m,`${{memberId}} left boundary`,color,1.6));t.push(line(lane.right_boundary_lcs_m,`${{memberId}} right boundary`,color,1.6));if(document.getElementById('laneIds').checked&&lane.centerline_lcs_m?.length){{const q=lane.centerline_lcs_m[Math.floor(lane.centerline_lcs_m.length/2)];t.push({{x:[q[0]],y:[q[1]],mode:'text',text:[String(memberId)],textfont:{{size:10,color}},showlegend:false,hoverinfo:'skip'}})}}}}if(document.getElementById('gaps').checked)for(const piece of track.pieces||[])if(piece.kind==='inferred_gap'&&(piece.polygon_lcs_m||[]).length)t.push(poly(piece.polygon_lcs_m,`${{role}} inferred gap`,color,'dash','14'))}}
function draw(){{const f=D.frames[+slider.value]||{{}},t=[],ep=f.ego_position||[0,0],r=roles(f);if(document.getElementById('raw').checked)for(const raw of D.raw_ld)t.push(line(raw.pts,`${{raw.kind}} ${{raw.id}}`,C.raw,0.8));if(document.getElementById('lanes').checked)for(const [trackId,role] of r.entries()){{const tr=trackById.get(trackId);if(tr)drawTrack(t,tr,role)}}if(document.getElementById('allSegments').checked)for(const lane of D.lanes)if((lane.centerline_lcs_m||[]).length>1)t.push(line(lane.centerline_lcs_m,`reconstructed ${{lane.lane_id}}`,C.segment,0.8,'dot'));
const corr=f.inferred_ego_corridor||{{}};if(document.getElementById('corridor').checked&&corr.valid){{t.push(poly(corr.polygon_lcs_m,'INFERRED EGO CORRIDOR',C.corridor,'dash','18'));t.push(line(corr.left_boundary_lcs_m,`corridor left boundary ${{corr.left_boundary_id}}`,C.corridor,3));t.push(line(corr.right_boundary_lcs_m,`corridor right boundary ${{corr.right_boundary_id}}`,C.corridor,3));t.push(line(corr.centerline_lcs_m,'inferred ego centerline',C.corridor,1.5,'dash'))}}
if(document.getElementById('trajectory').checked)t.push(line(D.frames.filter(x=>x.ego_position).map(x=>x.ego_position),'ego trajectory','#111827',1.2));t.push({{x:[ep[0]],y:[ep[1]],mode:'markers+text',text:['EGO'],textposition:'top center',marker:{{size:13,color:C.ego,symbol:'triangle-up'}},showlegend:false}});if(document.getElementById('objects').checked)for(const o of f.source_objects||[])if(o.p?.length>=2)t.push({{x:[o.p[0]],y:[o.p[1]],mode:'markers+text',text:[o.id],textposition:'top center',marker:{{size:9}},showlegend:false,hovertext:JSON.stringify(o.dbg),hoverinfo:'text'}});
const half=55,follow=document.getElementById('followEgo').checked,sx=viewSize?.x??half*2,sy=viewSize?.y??half*2,xr=follow?[ep[0]-sx/2,ep[0]+sx/2]:(viewState?.x||[ep[0]-half,ep[0]+half]),yr=follow?[ep[1]-sy/2,ep[1]+sy/2]:(viewState?.y||[ep[1]-half,ep[1]+half]);Plotly.react(plot,t,{{margin:{{l:40,r:15,t:15,b:40}},xaxis:{{scaleanchor:'y',scaleratio:1,range:xr}},yaxis:{{range:yr}},uirevision:'lane-debug-v2-topology'}},{{responsive:true,displaylogo:false}}).then(()=>{{if(!bound){{plot.on('plotly_relayout',remember);bound=true}}}});document.getElementById('frameLabel').textContent=`frame ${{f.frame_index}} · ${{Number(f.time_since_start_s||0).toFixed(2)}}s`;const panel={{frame_index:f.frame_index,ego_lane:f.ego_lane,continuous_ego_track:f.continuous_ego_track,inferred_ego_corridor:f.inferred_ego_corridor,topology_adjacency:f.continuous_adjacency,frame_local_adjacency_debug:f.frame_local_adjacency_debug,segment_ego_lane:f.segment_ego_lane,segment_left_lane:f.segment_left_lane,segment_right_lane:f.segment_right_lane}};document.getElementById('panel').style.display=document.getElementById('debugText').checked?'block':'none';document.getElementById('panel').textContent=JSON.stringify(panel,null,2)}}
for(const id of ['followEgo','raw','lanes','corridor','laneIds','gaps','allSegments','objects','trajectory','debugText'])document.getElementById(id).onchange=draw;slider.oninput=()=>{{stop();draw()}};document.getElementById('prev').onclick=()=>{{stop();slider.value=Math.max(0,+slider.value-1);draw()}};document.getElementById('next').onclick=()=>{{stop();slider.value=Math.min(D.frames.length-1,+slider.value+1);draw()}};document.getElementById('center').onclick=()=>{{viewState=null;viewSize=null;draw()}};playButton.onclick=play;draw();
</script></body></html>'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
