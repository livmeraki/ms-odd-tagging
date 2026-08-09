"""Standalone Plotly explorer for lane-debug v2."""
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

    source = {f["frame_index"]: f for f in recording.get("frames", [])}
    store = recording.get("ld_feature_store") or {}
    point_lookup = {
        str(p["point_id"]): p.get("position_lcs_m", [])[:2]
        for p in store.get("points", [])
        if len(p.get("position_lcs_m") or []) >= 2
    }

    raw = []
    for feat in store.get("lane_lines", []):
        raw.append({
            "id": str(feat.get("line_id")),
            "kind": "lane_line",
            "pts": [
                point_lookup[str(pid)]
                for pid in feat.get("point_ids", [])
                if str(pid) in point_lookup
            ],
        })
    for feat in store.get("road_boundaries", []):
        raw.append({
            "id": str(feat.get("road_boundary_id")),
            "kind": "road_boundary",
            "pts": [
                point_lookup[str(pid)]
                for pid in feat.get("point_ids", [])
                if str(pid) in point_lookup
            ],
        })

    frames = []
    for item in following.get("frames", []):
        src = source.get(item["frame_index"], {})
        ego = src.get("ego") or {}
        by_id = {str(o.get("object_id")): o for o in item.get("objects", [])}
        objects = []
        for obj in src.get("objects", []):
            oid = str(obj.get("object_id"))
            dbg = by_id.get(oid, {})
            objects.append({
                "id": oid,
                "class": obj.get("class"),
                "p": obj.get("position_lcs_m"),
                "heading": dbg.get("object_motion_heading_rad"),
                "dbg": dbg,
            })
        frames.append({
            **item,
            "ego_position": ego.get("position_lcs_m"),
            "ego_heading": ego.get("heading_lcs_rad"),
            "source_objects": objects,
        })

    payload = {
        "run_id": run_id,
        "recording_id": following.get("recording_id"),
        "lanes": following.get("lane_geometry", []),
        "bridges": following.get("probable_lane_bridges", []),
        "raw_ld": raw,
        "frames": frames,
        "lane_changes": lane_changes,
    }
    data = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/")

    html = f'''<!doctype html><html><head><meta charset="utf-8"><title>Lane Debug v2</title><script>{plotly_js}</script><style>
body{{font:13px system-ui;margin:0;background:#f6f7fb;color:#172033}}header{{padding:10px 14px;background:#fff;border-bottom:1px solid #ddd;position:sticky;top:0;z-index:4}}#controls{{display:flex;flex-wrap:wrap;gap:10px;align-items:center}}#plot{{height:72vh}}#panel{{background:#fff;padding:10px 14px;white-space:pre-wrap;font-family:ui-monospace,monospace;max-height:24vh;overflow:auto;border-top:1px solid #ddd}}input[type=range]{{width:340px}}</style></head><body>
<header><b id="title"></b><div id="controls"><button id="prev">◀</button><button id="play">▶ Play</button><button id="next">▶</button><input id="frame" type="range" min="0" step="1"><span id="frameLabel"></span>
<label><input id="followEgo" type="checkbox" checked>follow ego</label><label><input id="raw" type="checkbox" checked>raw LD</label><label><input id="recon" type="checkbox" checked>reconstructed lanes</label><label><input id="ids" type="checkbox" checked>lane IDs</label><label><input id="routes" type="checkbox">logical routes</label><label><input id="egoLane" type="checkbox" checked>ego lane</label><label><input id="adj" type="checkbox" checked>adjacent lanes</label><label><input id="objects" type="checkbox" checked>objects</label><label><input id="objHeading" type="checkbox" checked>object heading</label><label><input id="leadCandidates" type="checkbox" checked>lead candidates</label><label><input id="trajectory" type="checkbox" checked>ego trajectory</label><label><input id="debugText" type="checkbox" checked>debug text</label></div></header><div id="plot"></div><div id="panel"></div>
<script id="payload" type="application/json">{data}</script><script>
const D=JSON.parse(document.getElementById('payload').textContent),slider=document.getElementById('frame'),plot=document.getElementById('plot'),playButton=document.getElementById('play');slider.max=D.frames.length-1;document.getElementById('title').textContent=`${{D.recording_id}} — lane debug v2 — run ${{D.run_id}}`;
const roleColor={{ego:'#22c55e',left:'#06b6d4',right:'#f59e0b',other:'#94a3b8',lead:'#ef4444',candidate:'#a855f7'}};
let viewState=null,viewSize=null,relayoutBound=false,playTimer=null;
function traceLine(pts,name,color,width=1,dash='solid',showlegend=false){{return{{x:pts.map(p=>p[0]),y:pts.map(p=>p[1]),mode:'lines',name,line:{{color,width,dash}},hoverinfo:'name',showlegend}}}}
function polygon(l,name,color,fill='toself'){{const p=l.polygon_lcs_m||[];return{{x:p.map(q=>q[0]),y:p.map(q=>q[1]),mode:'lines',name,line:{{color,width:2}},fill,fillcolor:color+'22',hovertemplate:name+'<extra></extra>',showlegend:false}}}}
function rememberView(ev){{
 const x0=ev['xaxis.range[0]'],x1=ev['xaxis.range[1]'],y0=ev['yaxis.range[0]'],y1=ev['yaxis.range[1]'];
 if([x0,x1,y0,y1].every(Number.isFinite)){{viewState={{x:[x0,x1],y:[y0,y1]}};viewSize={{x:Math.abs(x1-x0),y:Math.abs(y1-y0)}}}}
 if(ev['xaxis.autorange']===true||ev['yaxis.autorange']===true){{viewState=null;viewSize=null}}
}}
function stopPlayback(){{if(playTimer!==null){{clearInterval(playTimer);playTimer=null}}playButton.textContent='▶ Play'}}
function togglePlayback(){{
 if(playTimer!==null){{stopPlayback();return}}
 if(+slider.value>=D.frames.length-1)slider.value=0;
 playButton.textContent='❚❚ Pause';
 playTimer=setInterval(()=>{{
  if(+slider.value>=D.frames.length-1){{stopPlayback();return}}
  slider.value=+slider.value+1;draw();
 }},100);
}}
function draw(){{
 const f=D.frames[+slider.value],traces=[],ep=f.ego_position||[0,0];
 if(document.getElementById('raw').checked)for(const r of D.raw_ld)if(r.pts.length>1)traces.push(traceLine(r.pts,`${{r.kind}} ${{r.id}}`,'#cbd5e1',1));
 const roles=new Map();if(f.ego_lane?.lane_id)roles.set(String(f.ego_lane.lane_id),'ego');if(f.left_lane?.lane_id)roles.set(String(f.left_lane.lane_id),'left');if(f.right_lane?.lane_id)roles.set(String(f.right_lane.lane_id),'right');
 if(document.getElementById('recon').checked)for(const l of D.lanes){{let role=roles.get(String(l.lane_id))||'other';if(role==='other'&&!document.getElementById('routes').checked)continue;traces.push(polygon(l,`${{role}} lane ${{l.lane_id}} / ${{l.logical_lane_id}}`,roleColor[role]));if(document.getElementById('ids').checked&&l.centerline_lcs_m?.length){{const q=l.centerline_lcs_m[Math.floor(l.centerline_lcs_m.length/2)];traces.push({{x:[q[0]],y:[q[1]],mode:'text',text:[String(l.lane_id)],textfont:{{size:10}},showlegend:false,hoverinfo:'skip'}})}}}}
 if(document.getElementById('trajectory').checked)traces.push(traceLine(D.frames.filter(x=>x.ego_position).map(x=>x.ego_position),'ego trajectory','#111827',2));
 traces.push({{x:[ep[0]],y:[ep[1]],mode:'markers+text',text:['EGO'],textposition:'top center',marker:{{size:13,color:roleColor.ego,symbol:'triangle-up'}},name:'ego',showlegend:false}});
 if(document.getElementById('objects').checked)for(const o of f.source_objects)if(o.p?.length>=2){{const isLead=f.lead&&String(f.lead.object_id)===o.id,base=o.dbg?.lead_base_candidate,color=isLead?roleColor.lead:(base?roleColor.candidate:'#334155');traces.push({{x:[o.p[0]],y:[o.p[1]],mode:'markers+text',text:[o.id],textposition:'top center',marker:{{size:isLead?14:9,color}},name:`${{o.class}} #${{o.id}}`,hovertext:JSON.stringify(o.dbg),hoverinfo:'name+text',showlegend:false}});if(document.getElementById('objHeading').checked&&o.heading!=null){{const L=4;traces.push(traceLine([o.p,[o.p[0]+L*Math.cos(o.heading),o.p[1]+L*Math.sin(o.heading)]],`heading ${{o.id}}`,color,2))}}}}
 const defaultHalfRange=55,followEgo=document.getElementById('followEgo').checked,spanX=viewSize?.x??defaultHalfRange*2,spanY=viewSize?.y??defaultHalfRange*2;
 const xr=followEgo?[ep[0]-spanX/2,ep[0]+spanX/2]:(viewState?.x||[ep[0]-defaultHalfRange,ep[0]+defaultHalfRange]);
 const yr=followEgo?[ep[1]-spanY/2,ep[1]+spanY/2]:(viewState?.y||[ep[1]-defaultHalfRange,ep[1]+defaultHalfRange]);
 Plotly.react(plot,traces,{{margin:{{l:40,r:15,t:15,b:40}},xaxis:{{scaleanchor:'y',scaleratio:1,range:xr}},yaxis:{{range:yr}},hovermode:'closest',uirevision:'lane-debug-v2'}},{{responsive:true,displaylogo:false}}).then(()=>{{if(!relayoutBound){{plot.on('plotly_relayout',rememberView);relayoutBound=true}}}});
 document.getElementById('frameLabel').textContent=`frame ${{f.frame_index}} · ${{Number(f.time_since_start_s).toFixed(2)}}s`;
 const panel={{run_id:D.run_id,frame_index:f.frame_index,follow_ego:followEgo,state:f.state,reason:f.reason,ego_lane:f.ego_lane,left_lane:f.left_lane,right_lane:f.right_lane,lead:f.lead,lead_candidates:f.lead_candidates_debug}};document.getElementById('panel').style.display=document.getElementById('debugText').checked?'block':'none';document.getElementById('panel').textContent=JSON.stringify(panel,null,2)
}}
for(const id of ['followEgo','raw','recon','ids','routes','egoLane','adj','objects','objHeading','leadCandidates','trajectory','debugText'])document.getElementById(id).onchange=draw;
slider.oninput=()=>{{stopPlayback();draw()}};document.getElementById('prev').onclick=()=>{{stopPlayback();slider.value=Math.max(0,+slider.value-1);draw()}};document.getElementById('next').onclick=()=>{{stopPlayback();slider.value=Math.min(D.frames.length-1,+slider.value+1);draw()}};playButton.onclick=togglePlayback;draw();
</script></body></html>'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
