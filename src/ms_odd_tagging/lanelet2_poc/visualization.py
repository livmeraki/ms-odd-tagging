"""Standalone optional overlay following the existing heading-up LCS convention."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def render_html(result: dict[str, Any], path: Path) -> None:
    payload = json.dumps(result, ensure_ascii=True, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    html = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lanelet2 LCS POC</title><style>
:root{--bg:#f8fafc;--fg:#172033;--panel:#fff;--grid:#dbe3ef;--ego:#16a34a;--left:#38bdf8;--right:#f59e0b;--candidate:#94a3b8}
@media(prefers-color-scheme:dark){:root{--bg:#10141d;--fg:#eef2ff;--panel:#171d29;--grid:#334155;--candidate:#64748b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px system-ui,sans-serif}main{max-width:1240px;margin:auto;padding:18px}
.tools{display:flex;gap:12px;align-items:center;flex-wrap:wrap}input[type=range]{flex:1;min-width:300px}canvas{width:100%;background:var(--panel);border:1px solid var(--grid);border-radius:10px;margin-top:12px}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:12px}.card{padding:10px;background:var(--panel);border:1px solid var(--grid);border-top:4px solid var(--color);border-radius:8px}pre{white-space:pre-wrap;max-height:280px;overflow:auto}
</style></head><body><main><h1>Lanelet2 LCS POC — <span id="recording"></span></h1>
<div class="tools"><button id="prev">Previous</button><button id="next">Next</button><label>Frame <span id="label"></span></label><input id="frame" type="range" min="0" value="0"></div>
<canvas id="map" width="1180" height="680"></canvas>
<div class="cards"><div class="card" style="--color:var(--left)"><b>Left adjacent</b><pre id="left"></pre></div><div class="card" style="--color:var(--ego)"><b>Ego lane</b><pre id="ego"></pre></div><div class="card" style="--color:var(--right)"><b>Right adjacent</b><pre id="right"></pre></div></div>
<details><summary>Frame diagnostics</summary><pre id="debug"></pre></details>
<script id="payload" type="application/json">__PAYLOAD__</script><script>
const data=JSON.parse(document.getElementById('payload').textContent),frames=data.frames,slider=document.getElementById('frame'),canvas=document.getElementById('map'),ctx=canvas.getContext('2d');
document.getElementById('recording').textContent=data.recording_id||'input';slider.max=Math.max(0,frames.length-1);
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function local(p,f){const e=f.ego_pose_lcs,dx=p[0]-e.x,dy=p[1]-e.y,c=Math.cos(e.yaw),s=Math.sin(e.yaw);return[c*dx+s*dy,-s*dx+c*dy]}
function screen(p){const scale=Math.min(canvas.width/60,canvas.height/135),cx=canvas.width/2,cy=105*scale;return[cx-p[1]*scale,cy-p[0]*scale]}
function polygon(points,f,color,alpha,width){if(!points||points.length<3)return;ctx.beginPath();points.forEach((p,i)=>{const q=screen(local(p,f));i?ctx.lineTo(...q):ctx.moveTo(...q)});ctx.closePath();ctx.globalAlpha=alpha;ctx.fillStyle=color;ctx.strokeStyle=color;ctx.lineWidth=width;ctx.fill();ctx.stroke();ctx.globalAlpha=1}
function draw(){const f=frames[+slider.value];ctx.clearRect(0,0,canvas.width,canvas.height);ctx.strokeStyle=css('--grid');ctx.lineWidth=1;for(let y=-50;y<=50;y+=10){let a=screen([-30,y]),b=screen([105,y]);ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.stroke()}for(let x=-30;x<=100;x+=10){let a=screen([x,-30]),b=screen([x,30]);ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.stroke()}
const selected=new Set([f.ego_lane.lane_id,f.left_adjacent.lane_id,f.right_adjacent.lane_id]);for(const lane of f.candidate_lanelets||[]){if(!selected.has(lane.lane_id))polygon(lane.polygon_lcs_m,f,css('--candidate'),.07,1)}
polygon(f.left_adjacent.polygon_lcs_m,f,css('--left'),.18,2);polygon(f.right_adjacent.polygon_lcs_m,f,css('--right'),.18,2);polygon(f.ego_lane.polygon_lcs_m,f,css('--ego'),.42,5);
const e=screen([0,0]);ctx.fillStyle=css('--ego');ctx.beginPath();ctx.moveTo(e[0],e[1]-15);ctx.lineTo(e[0]-10,e[1]+11);ctx.lineTo(e[0]+10,e[1]+11);ctx.closePath();ctx.fill();
document.getElementById('label').textContent=f.frame_index;document.getElementById('left').textContent=JSON.stringify(f.left_adjacent,null,2);document.getElementById('ego').textContent=JSON.stringify(f.ego_lane,null,2);document.getElementById('right').textContent=JSON.stringify(f.right_adjacent,null,2);document.getElementById('debug').textContent=JSON.stringify({status:f.status,routing:f.routing,matching:f.matching,rejections:f.rejections},null,2)}
slider.oninput=draw;document.getElementById('prev').onclick=()=>{slider.value=Math.max(0,+slider.value-1);draw()};document.getElementById('next').onclick=()=>{slider.value=Math.min(frames.length-1,+slider.value+1);draw()};if(frames.length)draw();
</script></main></body></html>""".replace("__PAYLOAD__", payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
