import json
import math
from collections import Counter
from pathlib import Path

import numpy as np

DATA_ROOT = Path("../2600_MV2_OD_traj_annotations").resolve()
OUT_DIR = Path(".").resolve()
SCENES_DIR = OUT_DIR / "dataset_scene_explorers"

PALETTE = [
    "#2563eb", "#dc2626", "#16a34a", "#f97316", "#7c3aed", "#0f766e",
    "#be123c", "#0891b2", "#854d0e", "#4b5563", "#65a30d", "#9333ea",
    "#ea580c", "#047857", "#b45309", "#0f172a",
]


def quat_yaw(qx, qy, qz, qw):
    return math.atan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz))


def load_traj(path):
    arr = np.loadtxt(path)
    t = arr[:, 0]
    rel_t = t - t[0]
    x = arr[:, 1]
    y = arr[:, 2]
    q = arr[:, 4:8]
    yaw = np.unwrap(np.arctan2(
        2 * (q[:, 3] * q[:, 2] + q[:, 0] * q[:, 1]),
        1 - 2 * (q[:, 1] ** 2 + q[:, 2] ** 2),
    ))
    dt = np.diff(t)
    dx = np.diff(x)
    dy = np.diff(y)
    speed = np.concatenate([[0.0], np.sqrt(dx * dx + dy * dy) / dt])
    if len(speed) > 5:
        speed_s = np.convolve(speed, np.ones(5) / 5, mode="same")
    else:
        speed_s = speed
    accel = np.concatenate([[0.0], np.diff(speed_s) / np.diff(rel_t)])
    if len(accel) > 5:
        accel_s = np.convolve(accel, np.ones(5) / 5, mode="same")
    else:
        accel_s = accel
    jerk = np.concatenate([[0.0], np.diff(accel_s) / np.diff(rel_t)])
    yaw_rate = np.concatenate([[0.0], np.diff(yaw) / np.diff(rel_t)])
    return {
        "rel_t": rel_t.tolist(),
        "x": x.tolist(),
        "y": y.tolist(),
        "yaw_deg": np.degrees(yaw).tolist(),
        "speed": speed.tolist(),
        "accel": accel_s.tolist(),
        "jerk": jerk.tolist(),
        "yaw_rate": yaw_rate.tolist(),
    }


def compact_float(x, ndigits=4):
    if x is None:
        return None
    return round(float(x), ndigits)


def object_payload(obj):
    bbox = obj.get("bbox3d") or {}
    visible = obj.get("visible_frames") or []
    attributes = (obj.get("staticAttributes") or []) + (obj.get("dynamicAttributes") or [])
    is_parked = any(
        isinstance(attr, dict) and attr.get("key") == "parked_vehicle" and attr.get("value") is True
        for attr in attributes
    )
    frame_items = []
    for key, frame in (obj.get("frames") or {}).items():
        fb = frame.get("bbox3d")
        if not fb:
            continue
        idx = int(frame.get("frameIndex", key))
        frame_items.append((
            idx,
            compact_float(fb.get("x")),
            compact_float(fb.get("y")),
            compact_float(quat_yaw(
                fb.get("qx", 0.0), fb.get("qy", 0.0), fb.get("qz", 0.0), fb.get("qw", 1.0)
            ), 5),
            compact_float(fb.get("length")),
            compact_float(fb.get("width")),
            compact_float(fb.get("height")),
        ))
    frame_items.sort(key=lambda item: item[0])
    base_yaw = compact_float(quat_yaw(
        bbox.get("qx", 0.0), bbox.get("qy", 0.0), bbox.get("qz", 0.0), bbox.get("qw", 1.0)
    ), 5)
    out = {
        "objectId": obj.get("objectId"),
        "className": obj.get("className"),
        "type": obj.get("type"),
        "subclassName": obj.get("subclassName"),
        "x": compact_float(bbox.get("x")),
        "y": compact_float(bbox.get("y")),
        "yaw": base_yaw,
        "length": compact_float(bbox.get("length")),
        "width": compact_float(bbox.get("width")),
        "height": compact_float(bbox.get("height")),
        "visibleMin": int(min(visible)) if visible else 0,
        "visibleMax": int(max(visible)) if visible else 0,
        "frameCount": len(visible),
        "isParked": is_parked,
    }
    if frame_items:
        out["frames"] = [i[0] for i in frame_items]
        out["xs"] = [i[1] for i in frame_items]
        out["ys"] = [i[2] for i in frame_items]
        out["yaws"] = [i[3] for i in frame_items]
        out["lengths"] = [i[4] for i in frame_items]
        out["widths"] = [i[5] for i in frame_items]
        out["heights"] = [i[6] for i in frame_items]
    return out


def html_escape_json(data):
    return json.dumps(data, separators=(",", ":")).replace("</", "<\\/")


def scene_html(data):
    payload = html_escape_json(data)
    title = data["summary"]["recording"]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title} Animated Trajectory/Object Explorer</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
body {{ margin:0; font-family:Arial,sans-serif; color:#17202a; background:#f6f8fb; }}
header {{ padding:14px 18px; background:#17324d; color:white; }}
.headerRow {{ display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }}
.backLink {{ color:white; border:1px solid rgba(255,255,255,.55); border-radius:6px; padding:7px 10px; font-size:12px; font-weight:700; text-decoration:none; }}
header h1 {{ margin:0 0 4px; font-size:18px; }} header p {{ margin:0; opacity:.9; font-size:12px; }}
.topPlayback {{ position:sticky; top:0; z-index:10; display:grid; grid-template-columns:auto minmax(240px,1fr) auto minmax(90px,120px); gap:10px; align-items:center; padding:10px 12px; background:#fff; border-bottom:1px solid #d7dee8; }}
.topPlayback button,.topPlayback select,.topPlayback input {{ margin-top:0; }} .topPlayback label {{ display:grid; grid-template-columns:auto minmax(0,1fr); gap:8px; align-items:center; margin-top:0; white-space:nowrap; }}
main {{ display:grid; grid-template-columns:320px 1fr; gap:12px; padding:12px; }} aside {{ background:white; border:1px solid #d7dee8; border-radius:8px; padding:14px; height:calc(100vh - 96px); overflow:auto; }}
.panel {{ background:white; border:1px solid #d7dee8; border-radius:8px; padding:8px; margin-bottom:12px; }} #map {{ height:590px; }} #timeline {{ height:520px; }}
label {{ display:block; margin-top:10px; font-size:13px; font-weight:700; }} select,input,button {{ width:100%; margin-top:4px; }} label input[type="checkbox"] {{ width:auto; margin-right:6px; }}
.stat {{ display:flex; justify-content:space-between; border-bottom:1px solid #edf1f5; padding:5px 0; font-size:13px; }} .classes {{ font-size:12px; line-height:1.45; }} #frameReadout {{ font-size:12px; color:#334155; }} .note {{ font-size:12px; color:#475569; line-height:1.4; margin-top:10px; }}
@media(max-width:900px) {{ .topPlayback {{ grid-template-columns:auto 1fr; }} main {{ grid-template-columns:1fr; }} aside {{ height:auto; }} }}
</style></head><body>
<header><div class="headerRow"><div><h1>{title}</h1><p>Animated ego trajectory with ALT object tracks. Uses per-frame bbox3d where available; static objects use object-level bbox3d.</p></div><a class="backLink" href="../index.html">Back to list</a></div></header>
<div id="animControls" class="topPlayback"><button id="playPause" type="button">Play</button><label for="frameSlider">Frame<input id="frameSlider" type="range" min="0" value="0" step="1" /></label><div id="frameReadout"></div><label for="playbackSpeed">Speed<select id="playbackSpeed"><option value="0.5">0.5x</option><option value="1" selected>1x</option><option value="2">2x</option><option value="4">4x</option><option value="8">8x</option><option value="16">16x</option></select></label></div>
<main><aside><div class="stat"><span>Frames</span><b id="statFrames"></b></div><div class="stat"><span>Duration</span><b id="statDuration"></b></div><div class="stat"><span>Objects</span><b id="statObjects"></b></div><div class="stat"><span>Per-frame tracks</span><b id="statTracks"></b></div><label for="classFilter">Object classes</label><select id="classFilter" multiple size="12"></select><label><input id="showFootprints" type="checkbox" checked /> Show bbox footprints</label><label><input id="showObjects" type="checkbox" checked /> Show object centers</label><label><input id="showEgoMarkers" type="checkbox" checked /> Show ego heading samples</label><label><input id="activeOnly" type="checkbox" checked /> Show active objects only</label><label id="persistStaticLabel"><input id="persistStatic" type="checkbox" checked /> Persist static / parked objects after first observation</label><label><input id="followEgo" type="checkbox" checked /> Follow ego with current zoom</label><h3>Class Counts</h3><div id="classCounts" class="classes"></div><div class="note">CDN version requires network access to Plotly. If plots are blank, check that cdn.plot.ly is reachable.</div></aside><section><div class="panel"><div id="map"></div></div><div class="panel"><div id="timeline"></div></div></section></main>
<script>
const DATA = {payload};
const palette = {json.dumps(PALETTE)};
const traj = DATA.trajectory; const objects = DATA.objects; const classes = Object.keys(DATA.summary.classCounts); const colorOf = Object.fromEntries(classes.map((c,i)=>[c,palette[i%palette.length]])); const filter=document.getElementById('classFilter');
document.getElementById('statFrames').textContent=DATA.summary.frames; document.getElementById('statDuration').textContent=DATA.summary.durationSec.toFixed(1)+'s'; document.getElementById('statObjects').textContent=DATA.summary.objects; document.getElementById('statTracks').textContent=DATA.summary.movingTracks;
classes.forEach(c=>{{const opt=document.createElement('option');opt.value=c;opt.textContent=c;opt.selected=true;filter.appendChild(opt);}}); document.getElementById('classCounts').innerHTML=classes.map(c=>`<div><b style="color:${{colorOf[c]}}">${{c}}</b>: ${{DATA.summary.classCounts[c]}}</div>`).join('');
const frameSlider=document.getElementById('frameSlider'), frameReadout=document.getElementById('frameReadout'), playPause=document.getElementById('playPause'), playbackSpeed=document.getElementById('playbackSpeed'), activeOnly=document.getElementById('activeOnly'), persistStatic=document.getElementById('persistStatic'), followEgo=document.getElementById('followEgo'); frameSlider.max=traj.rel_t.length-1; let currentIndex=0,playbackTimer=null;
function selectedClasses(){{return Array.from(filter.selectedOptions).map(o=>o.value)}} function lowerBound(arr,target){{let lo=0,hi=arr.length;while(lo<hi){{const mid=(lo+hi)>>1;if(arr[mid]<target)lo=mid+1;else hi=mid}}return lo}}
function isActiveObject(o){{if(!activeOnly.checked)return true;const mn=o.visibleMin??0,mx=o.visibleMax??traj.rel_t.length-1;if(mn<=currentIndex&&currentIndex<=mx)return true;return persistStatic.checked&&(o.type==='static'||o.isParked)&&currentIndex>=mn}}
function objectState(o,frameIndex){{if(o.frames&&o.frames.length){{const pos=lowerBound(o.frames,frameIndex);let idx=Math.min(pos,o.frames.length-1);if(o.frames[idx]!==frameIndex&&pos>0)idx=pos-1;return {{x:o.xs[idx],y:o.ys[idx],yaw:o.yaws[idx]??o.yaw,length:o.lengths?o.lengths[idx]:o.length,width:o.widths?o.widths[idx]:o.width,height:o.heights?o.heights[idx]:o.height}}}}return {{x:o.x,y:o.y,yaw:o.yaw,length:o.length,width:o.width,height:o.height}}}}
function cornersFor(st){{if(st.length==null||st.width==null||st.length<=0||st.width<=0)return null;const yaw=st.yaw||0,c=Math.cos(yaw),s=Math.sin(yaw),dx=st.length/2,dy=st.width/2;return [[dx,dy],[dx,-dy],[-dx,-dy],[-dx,dy],[dx,dy]].map(([px,py])=>[st.x+px*c-py*s,st.y+px*s+py*c])}}
function setFrame(index){{currentIndex=Math.max(0,Math.min(traj.rel_t.length-1,Number(index)));frameSlider.value=currentIndex;frameReadout.textContent=`frame ${{currentIndex}} / ${{traj.rel_t.length-1}} | t=${{traj.rel_t[currentIndex].toFixed(1)}}s | speed=${{traj.speed[currentIndex].toFixed(2)}} m/s`;render();updateTimelineCursor()}}
function headingTrace(){{const idx=[];for(let i=0;i<traj.x.length;i+=25)idx.push(i);return {{type:'scatter',mode:'markers',name:'ego heading samples',x:idx.map(i=>traj.x[i]),y:idx.map(i=>traj.y[i]),marker:{{symbol:'triangle-up',size:9,color:'#111827',angle:idx.map(i=>traj.yaw_deg[i])}}}}}}
function render(){{const selected=new Set(selectedClasses());const traces=[{{type:'scattergl',mode:'lines',name:'ego trajectory',x:traj.x,y:traj.y,line:{{color:'rgba(107,114,128,.45)',width:2}}}},{{type:'scattergl',mode:'lines',name:'ego path elapsed',x:traj.x.slice(0,currentIndex+1),y:traj.y.slice(0,currentIndex+1),line:{{color:'#2563eb',width:4}}}},{{type:'scattergl',mode:'markers',name:'ego current frame',x:[traj.x[currentIndex]],y:[traj.y[currentIndex]],marker:{{size:13,color:'#16a34a'}}}}];if(document.getElementById('showEgoMarkers').checked)traces.push(headingTrace());if(document.getElementById('showObjects').checked){{for(const c of classes){{if(!selected.has(c))continue;const active=objects.filter(o=>o.className===c&&isActiveObject(o));const states=active.map(o=>objectState(o,currentIndex));traces.push({{type:'scattergl',mode:'markers',name:c,x:states.map(st=>st.x),y:states.map(st=>st.y),marker:{{size:8,color:colorOf[c],opacity:.78}}}})}}}}if(document.getElementById('showFootprints').checked){{const fx=[],fy=[];for(const o of objects){{if(!selected.has(o.className)||!isActiveObject(o))continue;const st=objectState(o,currentIndex);if(st.x==null||st.y==null)continue;const corners=cornersFor(st);if(!corners)continue;for(const p of corners){{fx.push(p[0]);fy.push(p[1])}}fx.push(null);fy.push(null)}}traces.push({{type:'scattergl',mode:'lines',name:'selected bbox footprints',x:fx,y:fy,line:{{color:'rgba(31,41,55,.35)',width:1}}}})}}Plotly.react('map',traces,{{margin:{{l:55,r:270,t:20,b:50}},xaxis:{{title:'LCS x',scaleanchor:'y',scaleratio:1,zeroline:false}},yaxis:{{title:'LCS y',zeroline:false}},legend:{{orientation:'v',x:1.16,xanchor:'left',y:1,yanchor:'top',font:{{size:10}}}},hovermode:'closest',uirevision:'preserve-map-zoom'}},{{responsive:true}})}}
function renderTimeline(){{const traces=[{{type:'scattergl',mode:'lines',x:traj.rel_t,y:traj.speed,name:'speed m/s',line:{{color:'#2563eb'}}}},{{type:'scattergl',mode:'lines',x:traj.rel_t,y:traj.accel,name:'accel m/s2',yaxis:'y2',line:{{color:'#dc2626'}}}},{{type:'scattergl',mode:'lines',x:traj.rel_t,y:traj.jerk,name:'jerk m/s3',yaxis:'y3',line:{{color:'#16a34a'}}}},{{type:'scattergl',mode:'lines',x:traj.rel_t,y:traj.yaw_rate,name:'yaw rate rad/s',yaxis:'y4',line:{{color:'#9333ea'}}}}];Plotly.newPlot('timeline',traces,{{margin:{{l:72,r:78,t:26,b:86}},xaxis:{{title:'time since start (s)',domain:[0,1],anchor:'y4'}},yaxis:{{title:'speed m/s',domain:[.72,1]}},yaxis2:{{title:'accel m/s2',domain:[.36,.64]}},yaxis3:{{title:'jerk m/s3',overlaying:'y2',side:'right'}},yaxis4:{{title:'yaw rate rad/s',domain:[0,.28]}},legend:{{orientation:'h',x:.5,xanchor:'center',y:-.18}}}},{{responsive:true}})}}
function updateTimelineCursor(){{const t=traj.rel_t[currentIndex];Plotly.relayout('timeline',{{shapes:[{{type:'line',x0:t,x1:t,y0:0,y1:1,xref:'x',yref:'paper',line:{{color:'#111827',width:2,dash:'dot'}}}}]}})}}
filter.addEventListener('change',render);for(const id of ['showFootprints','showObjects','showEgoMarkers','activeOnly','persistStatic'])document.getElementById(id).addEventListener('change',render);frameSlider.addEventListener('input',e=>setFrame(e.target.value));playPause.addEventListener('click',()=>{{if(playbackTimer){{clearInterval(playbackTimer);playbackTimer=null;playPause.textContent='Play'}}else{{playPause.textContent='Pause';playbackTimer=setInterval(()=>setFrame((currentIndex+1)%traj.rel_t.length),100/(Number(playbackSpeed.value)||1))}}}});renderTimeline();setFrame(0);
</script></body></html>"""
