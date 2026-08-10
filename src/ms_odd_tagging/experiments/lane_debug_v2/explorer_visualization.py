"""Standalone Plotly explorer for lane-debug v2."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def _polyline_length(points: list[list[float]]) -> float:
    total = 0.0
    for a, b in zip(points, points[1:]):
        if len(a) >= 2 and len(b) >= 2:
            total += math.hypot(float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))
    return round(total, 3)


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

    edge_lookup: dict[str, dict[str, Any]] = {}
    raw = []
    for feat in store.get("lane_lines", []):
        edge_id = str(feat.get("line_id"))
        pts = [
            point_lookup[str(pid)]
            for pid in feat.get("point_ids", [])
            if str(pid) in point_lookup
        ]
        raw.append({"id": edge_id, "kind": "lane_line", "pts": pts})
        edge_lookup[edge_id] = {**feat, "edge_kind": "lane_line", "pts": pts}
    for feat in store.get("road_boundaries", []):
        edge_id = str(feat.get("road_boundary_id"))
        pts = [
            point_lookup[str(pid)]
            for pid in feat.get("point_ids", [])
            if str(pid) in point_lookup
        ]
        raw.append({"id": edge_id, "kind": "road_boundary", "pts": pts})
        edge_lookup[edge_id] = {**feat, "edge_kind": "road_boundary", "pts": pts}

    reconstructed_by_id = {
        str(lane.get("lane_id")): lane for lane in following.get("lane_geometry", [])
    }

    boundary_debug: dict[str, Any] = {}
    for lane in store.get("lanes", []):
        lane_id = str(lane.get("lane_id"))
        reconstructed = reconstructed_by_id.get(lane_id, {})
        sides: dict[str, Any] = {}
        for side in ("left", "right"):
            ref = (lane.get("boundaries") or {}).get(side) or {}
            edge_id = str(ref.get("edge_id")) if ref.get("edge_id") is not None else None
            edge = edge_lookup.get(edge_id or "")
            full_pts = list(edge.get("pts", [])) if edge else []
            selected_pts: list[list[float]] = []
            selected_orders: list[Any] = []
            if edge and ref.get("endpoint_order_valid"):
                elements = edge.get("elements") or []
                order_to_index = {item.get("order"): i for i, item in enumerate(elements)}
                start_index = order_to_index.get(ref.get("start_order"))
                end_index = order_to_index.get(ref.get("end_order"))
                if start_index is not None and end_index is not None:
                    step = 1 if end_index >= start_index else -1
                    selected_elements = [
                        elements[i] for i in range(start_index, end_index + step, step)
                    ]
                    selected_orders = [item.get("order") for item in selected_elements]
                    selected_pts = [
                        point_lookup[str(item.get("point_id"))]
                        for item in selected_elements
                        if str(item.get("point_id")) in point_lookup
                    ]
            used_pts = list(
                reconstructed.get(
                    "left_boundary_lcs_m" if side == "left" else "right_boundary_lcs_m",
                    [],
                )
                or []
            )
            sides[side] = {
                "edge_id": edge_id,
                "edge_kind": edge.get("edge_kind") if edge else None,
                "start_order": ref.get("start_order"),
                "end_order": ref.get("end_order"),
                "edge_reference_valid": ref.get("edge_reference_valid"),
                "endpoint_order_valid": ref.get("endpoint_order_valid"),
                "geometry_fallback": ref.get("geometry_fallback"),
                "full_edge_pts": full_pts,
                "canonical_range_pts": selected_pts,
                "canonical_range_orders": selected_orders,
                "detector_used_pts": used_pts,
                "full_edge_point_count": len(full_pts),
                "canonical_range_point_count": len(selected_pts),
                "detector_used_point_count": len(used_pts),
                "full_edge_length_m": _polyline_length(full_pts),
                "canonical_range_length_m": _polyline_length(selected_pts),
                "detector_used_length_m": _polyline_length(used_pts),
            }
        boundary_debug[lane_id] = {
            "lane_id": lane_id,
            "canonical_boundary_ranges_valid": (lane.get("validity") or {}).get("boundary_ranges_valid"),
            "detector_assignment_valid": reconstructed.get("assignment_valid"),
            "detector_invalid_reason": reconstructed.get("invalid_reason"),
            "geometry_recovered": reconstructed.get("geometry_recovered"),
            "recovery_method": reconstructed.get("recovery_method"),
            "recovery_evidence": reconstructed.get("recovery_evidence"),
            "left": sides["left"],
            "right": sides["right"],
        }

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
        "boundary_debug": boundary_debug,
        "frames": frames,
        "lane_changes": lane_changes,
    }
    data = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/")

    html = f'''<!doctype html><html><head><meta charset="utf-8"><title>Lane Debug v2</title><script>{plotly_js}</script><style>
body{{font:13px system-ui;margin:0;background:#f6f7fb;color:#172033}}header{{padding:10px 14px;background:#fff;border-bottom:1px solid #ddd;position:sticky;top:0;z-index:4}}#controls{{display:flex;flex-wrap:wrap;gap:10px;align-items:center}}#plot{{height:72vh}}#panel{{background:#fff;padding:10px 14px;white-space:pre-wrap;font-family:ui-monospace,monospace;max-height:24vh;overflow:auto;border-top:1px solid #ddd}}input[type=range]{{width:340px}}</style></head><body>
<header><b id="title"></b><div id="controls"><button id="prev">◀</button><button id="play">▶ Play</button><button id="next">▶</button><input id="frame" type="range" min="0" step="1"><span id="frameLabel"></span>
<label><input id="followEgo" type="checkbox" checked>follow ego</label><label><input id="raw" type="checkbox" checked>raw LD</label><label><input id="recon" type="checkbox" checked>reconstructed lanes</label><label><input id="ids" type="checkbox" checked>lane IDs</label><label><input id="routes" type="checkbox">logical routes</label><label><input id="egoLane" type="checkbox" checked>ego lane</label><label><input id="adj" type="checkbox" checked>adjacent lanes</label><label><input id="fullEdges" type="checkbox">full referenced edges</label><label><input id="canonicalRanges" type="checkbox" checked>canonical boundary ranges</label><label><input id="usedBoundaries" type="checkbox" checked>detector-used boundaries</label><label><input id="rangeEndpoints" type="checkbox" checked>range start/end</label><label><input id="objects" type="checkbox" checked>objects</label><label><input id="objHeading" type="checkbox" checked>object heading</label><label><input id="leadCandidates" type="checkbox" checked>lead candidates</label><label><input id="trajectory" type="checkbox" checked>ego trajectory</label><label><input id="debugText" type="checkbox" checked>debug text</label></div></header><div id="plot"></div><div id="panel"></div>
<script id="payload" type="application/json">{data}</script><script>
const D=JSON.parse(document.getElementById('payload').textContent),slider=document.getElementById('frame'),plot=document.getElementById('plot'),playButton=document.getElementById('play');slider.max=D.frames.length-1;document.getElementById('title').textContent=`${{D.recording_id}} — lane debug v2 — run ${{D.run_id}}`;
const roleColor={{ego:'#22c55e',left:'#06b6d4',right:'#f59e0b',other:'#94a3b8',lead:'#ef4444',candidate:'#a855f7'}};
let viewState=null,viewSize=null,relayoutBound=false,playTimer=null;
function traceLine(pts,name,color,width=1,dash='solid',showlegend=false){{return{{x:pts.map(p=>p[0]),y:pts.map(p=>p[1]),mode:'lines',name,line:{{color,width,dash}},hoverinfo:'name',showlegend}}}}
function polygon(l,name,color,fill='toself'){{const p=l.polygon_lcs_m||[];return{{x:p.map(q=>q[0]),y:p.map(q=>q[1]),mode:'lines',name,line:{{color,width:2}},fill,fillcolor:color+'22',hovertemplate:name+'<extra></extra>',showlegend:false}}}}
function endpointTrace(pts,text,color){{if(!pts||!pts.length)return null;const first=pts[0],last=pts[pts.length-1];return{{x:[first[0],last[0]],y:[first[1],last[1]],mode:'markers+text',text,textposition:['bottom center','top center'],textfont:{{size:10,color}},marker:{{size:9,color,symbol:['circle','diamond']}},showlegend:false,hoverinfo:'text'}}}}
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
function selectedLaneRoles(f){{const roles=new Map();if(f.ego_lane?.lane_id)roles.set(String(f.ego_lane.lane_id),'ego');if(f.left_lane?.lane_id)roles.set(String(f.left_lane.lane_id),'left');if(f.right_lane?.lane_id)roles.set(String(f.right_lane.lane_id),'right');return roles}}
function drawBoundaryDebug(traces,roles){{
 for(const [laneId,role] of roles.entries()){{
  const dbg=D.boundary_debug?.[laneId];if(!dbg)continue;const color=roleColor[role]||roleColor.other;
  for(const side of ['left','right']){{const b=dbg[side];if(!b)continue;
   if(document.getElementById('fullEdges').checked&&b.full_edge_pts?.length>1)traces.push(traceLine(b.full_edge_pts,`${{role}} ${{side}} FULL edge ${{b.edge_id}}`,'#475569',5,'dot'));
   if(document.getElementById('canonicalRanges').checked&&b.canonical_range_pts?.length>1)traces.push(traceLine(b.canonical_range_pts,`${{role}} ${{side}} canonical range ${{b.start_order}}→${{b.end_order}}`,color,5,'dash'));
   if(document.getElementById('usedBoundaries').checked&&b.detector_used_pts?.length>1)traces.push(traceLine(b.detector_used_pts,`${{role}} ${{side}} detector-used boundary`,color,2,'solid'));
   if(document.getElementById('rangeEndpoints').checked&&b.canonical_range_pts?.length){{const t=endpointTrace(b.canonical_range_pts,[`${{side[0].toUpperCase()}} start=${{b.start_order}}`,`${{side[0].toUpperCase()}} end=${{b.end_order}}`],color);if(t)traces.push(t)}}
  }}
 }}
}}
function draw(){{
 const f=D.frames[+slider.value],traces=[],ep=f.ego_position||[0,0];
 if(document.getElementById('raw').checked)for(const r of D.raw_ld)if(r.pts.length>1)traces.push(traceLine(r.pts,`${{r.kind}} ${{r.id}}`,'#cbd5e1',1));
 const roles=selectedLaneRoles(f);
 if(document.getElementById('recon').checked)for(const l of D.lanes){{let role=roles.get(String(l.lane_id))||'other';if(role==='other'&&!document.getElementById('routes').checked)continue;traces.push(polygon(l,`${{role}} lane ${{l.lane_id}} / ${{l.logical_lane_id}}`,roleColor[role]));if(document.getElementById('ids').checked&&l.centerline_lcs_m?.length){{const q=l.centerline_lcs_m[Math.floor(l.centerline_lcs_m.length/2)];traces.push({{x:[q[0]],y:[q[1]],mode:'text',text:[String(l.lane_id)],textfont:{{size:10}},showlegend:false,hoverinfo:'skip'}})}}}}
 drawBoundaryDebug(traces,roles);
 if(document.getElementById('trajectory').checked)traces.push(traceLine(D.frames.filter(x=>x.ego_position).map(x=>x.ego_position),'ego trajectory','#111827',2));
 traces.push({{x:[ep[0]],y:[ep[1]],mode:'markers+text',text:['EGO'],textposition:'top center',marker:{{size:13,color:roleColor.ego,symbol:'triangle-up'}},name:'ego',showlegend:false}});
 if(document.getElementById('objects').checked)for(const o of f.source_objects)if(o.p?.length>=2){{const isLead=f.lead&&String(f.lead.object_id)===o.id,base=o.dbg?.lead_base_candidate,color=isLead?roleColor.lead:(base?roleColor.candidate:'#334155');traces.push({{x:[o.p[0]],y:[o.p[1]],mode:'markers+text',text:[o.id],textposition:'top center',marker:{{size:isLead?14:9,color}},name:`${{o.class}} #${{o.id}}`,hovertext:JSON.stringify(o.dbg),hoverinfo:'name+text',showlegend:false}});if(document.getElementById('objHeading').checked&&o.heading!=null){{const L=4;traces.push(traceLine([o.p,[o.p[0]+L*Math.cos(o.heading),o.p[1]+L*Math.sin(o.heading)]],`heading ${{o.id}}`,color,2))}}}}
 const defaultHalfRange=55,followEgo=document.getElementById('followEgo').checked,spanX=viewSize?.x??defaultHalfRange*2,spanY=viewSize?.y??defaultHalfRange*2;
 const xr=followEgo?[ep[0]-spanX/2,ep[0]+spanX/2]:(viewState?.x||[ep[0]-defaultHalfRange,ep[0]+defaultHalfRange]);
 const yr=followEgo?[ep[1]-spanY/2,ep[1]+spanY/2]:(viewState?.y||[ep[1]-defaultHalfRange,ep[1]+defaultHalfRange]);
 Plotly.react(plot,traces,{{margin:{{l:40,r:15,t:15,b:40}},xaxis:{{scaleanchor:'y',scaleratio:1,range:xr}},yaxis:{{range:yr}},hovermode:'closest',uirevision:'lane-debug-v2'}},{{responsive:true,displaylogo:false}}).then(()=>{{if(!relayoutBound){{plot.on('plotly_relayout',rememberView);relayoutBound=true}}}});
 document.getElementById('frameLabel').textContent=`frame ${{f.frame_index}} · ${{Number(f.time_since_start_s).toFixed(2)}}s`;
 const selectedBoundaryDebug={{}};for(const laneId of roles.keys())if(D.boundary_debug?.[laneId])selectedBoundaryDebug[laneId]=D.boundary_debug[laneId];
 const panel={{run_id:D.run_id,frame_index:f.frame_index,follow_ego:followEgo,state:f.state,reason:f.reason,ego_lane:f.ego_lane,left_lane:f.left_lane,right_lane:f.right_lane,boundary_debug:selectedBoundaryDebug,lead:f.lead,lead_candidates:f.lead_candidates_debug}};document.getElementById('panel').style.display=document.getElementById('debugText').checked?'block':'none';document.getElementById('panel').textContent=JSON.stringify(panel,null,2)
}}
for(const id of ['followEgo','raw','recon','ids','routes','egoLane','adj','fullEdges','canonicalRanges','usedBoundaries','rangeEndpoints','objects','objHeading','leadCandidates','trajectory','debugText'])document.getElementById(id).onchange=draw;
slider.oninput=()=>{{stopPlayback();draw()}};document.getElementById('prev').onclick=()=>{{stopPlayback();slider.value=Math.max(0,+slider.value-1);draw()}};document.getElementById('next').onclick=()=>{{stopPlayback();slider.value=Math.min(D.frames.length-1,+slider.value+1);draw()}};playButton.onclick=togglePlayback;draw();
</script></body></html>'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
