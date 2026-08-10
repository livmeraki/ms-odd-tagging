"""Standalone Plotly explorer for lane-debug v2.

Continuous tracks remain the primary detection representation, but the explorer
never draws the synthetic track corridor polygon. A selected continuous lane is
visualized by filling its actual reconstructed member lane polygons plus any
accepted inferred-gap polygons. Original per-lane boundaries remain visible so
track continuity does not hide where physical LD lane segments begin/end.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def _polyline_length(points: list[list[float]]) -> float:
    return round(
        sum(
            math.hypot(float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))
            for a, b in zip(points, points[1:])
            if len(a) >= 2 and len(b) >= 2
        ),
        3,
    )


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
    for collection, id_key, kind in (
        ("lane_lines", "line_id", "lane_line"),
        ("road_boundaries", "road_boundary_id", "road_boundary"),
    ):
        for feat in store.get(collection, []):
            edge_id = str(feat.get(id_key))
            pts = [
                point_lookup[str(pid)]
                for pid in feat.get("point_ids", [])
                if str(pid) in point_lookup
            ]
            raw.append({"id": edge_id, "kind": kind, "pts": pts})
            edge_lookup[edge_id] = {**feat, "edge_kind": kind, "pts": pts}

    reconstructed = {
        str(l.get("lane_id")): l for l in following.get("lane_geometry", [])
    }

    boundary_debug = {}
    for lane in store.get("lanes", []):
        lane_id = str(lane.get("lane_id"))
        rec = reconstructed.get(lane_id, {})
        sides = {}
        for side in ("left", "right"):
            ref = (lane.get("boundaries") or {}).get(side) or {}
            edge_id = (
                str(ref.get("edge_id")) if ref.get("edge_id") is not None else None
            )
            edge = edge_lookup.get(edge_id or "")
            full = list(edge.get("pts", [])) if edge else []
            selected = []
            if edge and ref.get("endpoint_order_valid"):
                elements = edge.get("elements") or []
                order_to_index = {item.get("order"): i for i, item in enumerate(elements)}
                start_index = order_to_index.get(ref.get("start_order"))
                end_index = order_to_index.get(ref.get("end_order"))
                if start_index is not None and end_index is not None:
                    step = 1 if end_index >= start_index else -1
                    selected = [
                        point_lookup[str(elements[i].get("point_id"))]
                        for i in range(start_index, end_index + step, step)
                        if str(elements[i].get("point_id")) in point_lookup
                    ]
            used = list(
                rec.get(
                    "left_boundary_lcs_m" if side == "left" else "right_boundary_lcs_m",
                    [],
                )
                or []
            )
            sides[side] = {
                "edge_id": edge_id,
                "start_order": ref.get("start_order"),
                "end_order": ref.get("end_order"),
                "endpoint_order_valid": ref.get("endpoint_order_valid"),
                "geometry_fallback": ref.get("geometry_fallback"),
                "full_edge_pts": full,
                "canonical_range_pts": selected,
                "detector_used_pts": used,
                "full_edge_length_m": _polyline_length(full),
                "canonical_range_length_m": _polyline_length(selected),
                "detector_used_length_m": _polyline_length(used),
            }
        boundary_debug[lane_id] = {
            "lane_id": lane_id,
            "detector_assignment_valid": rec.get("assignment_valid"),
            "detector_invalid_reason": rec.get("invalid_reason"),
            "geometry_recovered": rec.get("geometry_recovered"),
            "recovery_method": rec.get("recovery_method"),
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
            object_id = str(obj.get("object_id"))
            dbg = by_id.get(object_id, {})
            objects.append(
                {
                    "id": object_id,
                    "class": obj.get("class"),
                    "p": obj.get("position_lcs_m"),
                    "heading": dbg.get("object_motion_heading_rad"),
                    "dbg": dbg,
                }
            )
        frames.append(
            {
                **item,
                "ego_position": ego.get("position_lcs_m"),
                "ego_heading": ego.get("heading_lcs_rad"),
                "source_objects": objects,
            }
        )

    payload = {
        "run_id": run_id,
        "recording_id": following.get("recording_id"),
        "lanes": following.get("lane_geometry", []),
        "tracks": following.get("continuous_lane_tracks", []),
        "connections": following.get("continuous_track_connection_debug", []),
        "raw_ld": raw,
        "boundary_debug": boundary_debug,
        "frames": frames,
        "lane_changes": lane_changes,
    }
    data = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace(
        "</", "<\\/"
    )

    html = f'''<!doctype html><html><head><meta charset="utf-8"><title>Lane Debug v2</title><script>{plotly_js}</script><style>
body{{font:13px system-ui;margin:0;background:#f6f7fb;color:#172033}}header{{padding:10px 14px;background:#fff;border-bottom:1px solid #ddd;position:sticky;top:0;z-index:4}}#controls{{display:flex;flex-wrap:wrap;gap:9px;align-items:center}}#plot{{height:72vh}}#panel{{background:#fff;padding:10px 14px;white-space:pre-wrap;font-family:ui-monospace,monospace;max-height:24vh;overflow:auto;border-top:1px solid #ddd}}input[type=range]{{width:320px}}</style></head><body>
<header><b id="title"></b><div id="controls"><button id="prev">◀</button><button id="play">▶ Play</button><button id="next">▶</button><input id="frame" type="range" min="0" step="1"><span id="frameLabel"></span>
<label><input id="followEgo" type="checkbox" checked>follow ego</label><label><input id="raw" type="checkbox">raw LD</label><label><input id="lanes" type="checkbox" checked>detected lanes</label><label><input id="laneIds" type="checkbox" checked>lane IDs</label><label><input id="inferredGaps" type="checkbox" checked>inferred gaps</label><label><input id="segmentComparison" type="checkbox">all reconstructed segments</label><label><input id="fullEdges" type="checkbox">full referenced edges</label><label><input id="canonicalRanges" type="checkbox">canonical ranges</label><label><input id="usedBoundaries" type="checkbox">detector boundaries</label><label><input id="objects" type="checkbox" checked>objects</label><label><input id="trajectory" type="checkbox" checked>ego trajectory</label><label><input id="debugText" type="checkbox" checked>debug text</label></div></header>
<div id="plot"></div><div id="panel"></div><script id="payload" type="application/json">{data}</script><script>
const D=JSON.parse(document.getElementById('payload').textContent),slider=document.getElementById('frame'),plot=document.getElementById('plot'),playButton=document.getElementById('play');slider.max=D.frames.length-1;document.getElementById('title').textContent=`${{D.recording_id}} — lane debug v2 — run ${{D.run_id}}`;let viewState=null,viewSize=null,bound=false,timer=null;
const C={{ego:'#22c55e',left:'#06b6d4',right:'#f59e0b',other:'#94a3b8',gap:'#dc2626',segment:'#a78bfa'}};
const laneById=new Map(D.lanes.map(l=>[String(l.lane_id),l]));
const trackById=new Map(D.tracks.map(t=>[String(t.track_id),t]));
function line(pts,name,color,width=1.5,dash='solid'){{return{{x:(pts||[]).map(p=>p[0]),y:(pts||[]).map(p=>p[1]),mode:'lines',name,line:{{color,width,dash}},showlegend:false,hoverinfo:'name'}}}}
function filledPolygon(pts,name,color,dash='solid'){{return{{x:(pts||[]).map(p=>p[0]),y:(pts||[]).map(p=>p[1]),mode:'lines',name,line:{{color,width:2,dash}},fill:'toself',fillcolor:color+'22',showlegend:false,hoverinfo:'name'}}}}
function remember(ev){{const x0=ev['xaxis.range[0]'],x1=ev['xaxis.range[1]'],y0=ev['yaxis.range[0]'],y1=ev['yaxis.range[1]'];if([x0,x1,y0,y1].every(Number.isFinite)){{viewState={{x:[x0,x1],y:[y0,y1]}};viewSize={{x:Math.abs(x1-x0),y:Math.abs(y1-y0)}}}}if(ev['xaxis.autorange']===true||ev['yaxis.autorange']===true){{viewState=null;viewSize=null}}}}
function stop(){{if(timer!==null){{clearInterval(timer);timer=null}}playButton.textContent='▶ Play'}}
function play(){{if(timer!==null){{stop();return}}if(+slider.value>=D.frames.length-1)slider.value=0;playButton.textContent='❚❚ Pause';timer=setInterval(()=>{{if(+slider.value>=D.frames.length-1){{stop();return}}slider.value=+slider.value+1;draw()}},100)}}
function trackRoles(f){{const m=new Map();if(f.continuous_ego_track?.track_id)m.set(String(f.continuous_ego_track.track_id),'ego');if(f.continuous_adjacency?.left?.track_id)m.set(String(f.continuous_adjacency.left.track_id),'left');if(f.continuous_adjacency?.right?.track_id)m.set(String(f.continuous_adjacency.right.track_id),'right');return m}}
function drawTrackAsLane(traces,track,role){{const color=C[role]||C.other;for(const memberId of track.member_lane_ids||[]){{const lane=laneById.get(String(memberId));if(!lane)continue;traces.push(filledPolygon(lane.polygon_lcs_m,`${{role}} lane ${{memberId}} · ${{track.track_id}}`,color));traces.push(line(lane.left_boundary_lcs_m,`${{role}} lane ${{memberId}} left boundary`,color,2));traces.push(line(lane.right_boundary_lcs_m,`${{role}} lane ${{memberId}} right boundary`,color,2));if(document.getElementById('laneIds').checked&&lane.centerline_lcs_m?.length){{const q=lane.centerline_lcs_m[Math.floor(lane.centerline_lcs_m.length/2)];traces.push({{x:[q[0]],y:[q[1]],mode:'text',text:[String(memberId)],textfont:{{size:10,color}},showlegend:false,hoverinfo:'skip'}})}}}}if(document.getElementById('inferredGaps').checked)for(const piece of track.pieces||[]){{if(piece.kind!=='inferred_gap'||!(piece.polygon_lcs_m||[]).length)continue;traces.push(filledPolygon(piece.polygon_lcs_m,`${{role}} inferred gap ${{piece.source_lane_id}}→${{piece.destination_lane_id}}`,color,'dash'))}}}}
function draw(){{const f=D.frames[+slider.value],t=[],ep=f.ego_position||[0,0],roles=trackRoles(f);if(document.getElementById('raw').checked)for(const r of D.raw_ld)if(r.pts.length>1)t.push(line(r.pts,`${{r.kind}} ${{r.id}}`,'#cbd5e1',0.8));
if(document.getElementById('lanes').checked)for(const [trackId,role] of roles.entries()){{const tr=trackById.get(trackId);if(tr)drawTrackAsLane(t,tr,role)}}
if(document.getElementById('segmentComparison').checked)for(const l of D.lanes){{if((l.centerline_lcs_m||[]).length>1)t.push(line(l.centerline_lcs_m,`reconstructed segment ${{l.lane_id}}`,C.segment,0.8,'dot'))}}
if(document.getElementById('trajectory').checked)t.push(line(D.frames.filter(x=>x.ego_position).map(x=>x.ego_position),'ego trajectory','#111827',1.2));
for(const [trackId,role] of roles.entries()){{const tr=trackById.get(trackId);if(!tr)continue;for(const memberId of tr.member_lane_ids||[]){{const dbg=D.boundary_debug?.[String(memberId)];if(!dbg)continue;for(const side of ['left','right']){{const b=dbg[side];if(document.getElementById('fullEdges').checked)t.push(line(b.full_edge_pts,`${{memberId}} ${{side}} full edge ${{b.edge_id}}`,'#475569',1.5,'dot'));if(document.getElementById('canonicalRanges').checked)t.push(line(b.canonical_range_pts,`${{memberId}} ${{side}} range ${{b.start_order}}→${{b.end_order}}`,C[role],1.5,'dash'));if(document.getElementById('usedBoundaries').checked)t.push(line(b.detector_used_pts,`${{memberId}} ${{side}} detector used`,C[role],1.5))}}}}}}
t.push({{x:[ep[0]],y:[ep[1]],mode:'markers+text',text:['EGO'],textposition:'top center',marker:{{size:13,color:C.ego,symbol:'triangle-up'}},showlegend:false}});if(document.getElementById('objects').checked)for(const o of f.source_objects)if(o.p?.length>=2)t.push({{x:[o.p[0]],y:[o.p[1]],mode:'markers+text',text:[o.id],textposition:'top center',marker:{{size:9}},showlegend:false,hovertext:JSON.stringify(o.dbg),hoverinfo:'text'}});
const half=55,follow=document.getElementById('followEgo').checked,sx=viewSize?.x??half*2,sy=viewSize?.y??half*2,xr=follow?[ep[0]-sx/2,ep[0]+sx/2]:(viewState?.x||[ep[0]-half,ep[0]+half]),yr=follow?[ep[1]-sy/2,ep[1]+sy/2]:(viewState?.y||[ep[1]-half,ep[1]+half]);Plotly.react(plot,t,{{margin:{{l:40,r:15,t:15,b:40}},xaxis:{{scaleanchor:'y',scaleratio:1,range:xr}},yaxis:{{range:yr}},uirevision:'lane-debug-v2-exact-polygons'}},{{responsive:true,displaylogo:false}}).then(()=>{{if(!bound){{plot.on('plotly_relayout',remember);bound=true}}}});document.getElementById('frameLabel').textContent=`frame ${{f.frame_index}} · ${{Number(f.time_since_start_s).toFixed(2)}}s`;const panel={{frame_index:f.frame_index,continuous_ego_track:f.continuous_ego_track,continuous_adjacency:f.continuous_adjacency,primary_ego_lane:f.ego_lane,primary_left_lane:f.left_lane,primary_right_lane:f.right_lane,segment_ego_lane:f.segment_ego_lane,segment_left_lane:f.segment_left_lane,segment_right_lane:f.segment_right_lane}};document.getElementById('panel').style.display=document.getElementById('debugText').checked?'block':'none';document.getElementById('panel').textContent=JSON.stringify(panel,null,2)}}
for(const id of ['followEgo','raw','lanes','laneIds','inferredGaps','segmentComparison','fullEdges','canonicalRanges','usedBoundaries','objects','trajectory','debugText'])document.getElementById(id).onchange=draw;slider.oninput=()=>{{stop();draw()}};document.getElementById('prev').onclick=()=>{{stop();slider.value=Math.max(0,+slider.value-1);draw()}};document.getElementById('next').onclick=()=>{{stop();slider.value=Math.min(D.frames.length-1,+slider.value+1);draw()}};playButton.onclick=play;draw();
</script></body></html>'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
