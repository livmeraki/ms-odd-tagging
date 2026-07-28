"""CLI pipeline for inspecting following-lane tagging one stage at a time."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ms_odd_tagging.common.config import CANONICAL, FOLLOWING_LANE

from .detector import run_following_lane
from .explorer_visualization import render_original_explorer_with_lane_tracker


STAGES = ("lane-geometry", "assignments", "tags", "visualization")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=True, indent=2)


def render_html(
    recording: dict[str, Any],
    result: dict[str, Any],
    path: Path,
    base_explorer_path: Path | None = None,
) -> None:
    if base_explorer_path is not None:
        render_original_explorer_with_lane_tracker(
            base_explorer_path,
            result,
            path,
        )
        return
    frames_by_index = {frame["frame_index"]: frame for frame in recording["frames"]}
    store = recording.get("ld_feature_store") or {}
    point_lookup = {
        str(point["point_id"]): point["position_lcs_m"][:2]
        for point in store.get("points", [])
        if len(point.get("position_lcs_m") or []) >= 2
    }
    raw_ld_features = []
    for feature in store.get("lane_lines", []):
        raw_ld_features.append(
            {
                "feature_id": str(feature["line_id"]),
                "source_kind": "lane_line",
                "points_lcs_m": [
                    point_lookup[str(point_id)]
                    for point_id in feature.get("point_ids", [])
                    if str(point_id) in point_lookup
                ],
                "attributes": feature.get("attributes") or {},
            }
        )
    for feature in store.get("road_boundaries", []):
        if feature.get("boundary_attribute") != "drivable":
            continue
        raw_ld_features.append(
            {
                "feature_id": str(feature["road_boundary_id"]),
                "source_kind": "drivable_road_boundary",
                "points_lcs_m": [
                    point_lookup[str(point_id)]
                    for point_id in feature.get("point_ids", [])
                    if str(point_id) in point_lookup
                ],
                "attributes": {
                    **(feature.get("attributes") or {}),
                    "pattern": "solid",
                    "boundary_attribute": "drivable",
                },
            }
        )
    payload_frames = []
    for tag in result["frames"]:
        source = frames_by_index[tag["frame_index"]]
        payload_frames.append({
            **tag,
            "ego_position": (source.get("ego") or {}).get("position_lcs_m"),
            "ego_heading": (source.get("ego") or {}).get("heading_lcs_rad"),
            "source_objects": [
                {
                    "object_id": str(obj.get("object_id")), "class": obj.get("class"),
                    "annotation_type": obj.get("annotation_type"),
                    "position_lcs_m": obj.get("position_lcs_m"),
                }
                for obj in source.get("objects", [])
                if obj.get("annotation_type") == "dynamic"
            ],
        })
    payload = {
        "recording_id": result["recording_id"], "lanes": result["lane_geometry"],
        "bridges": result.get("probable_lane_bridges", []),
        "raw_ld_features": raw_ld_features,
        "frames": payload_frames, "intervals": result["intervals"],
    }
    payload_json = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/")
    html = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Following-lane frame debugger</title>
<style>
:root{color-scheme:light dark;--bg:#f7f9fc;--panel:#fff;--fg:#172033;--muted:#5b6578;--border:#d8deea;--ego:#22c55e;--left:#06b6d4;--right:#f59e0b;--other:#94a3b8;--unknown:#a855f7;--lead:#ef4444} @media(prefers-color-scheme:dark){:root{--bg:#10141d;--panel:#171d29;--fg:#eef2ff;--muted:#aab3c5;--border:#30394a;--other:#667085}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px system-ui,sans-serif}main{max-width:1180px;margin:auto;padding:18px}.toolbar{display:flex;gap:14px;align-items:center;flex-wrap:wrap}.toolbar input{flex:1;min-width:260px}button{padding:7px 12px}canvas{display:block;width:100%;background:var(--panel);border:1px solid var(--border);border-radius:10px}.map{margin-top:12px}.timeline{margin-top:12px;height:84px}.legend{display:flex;gap:14px;flex-wrap:wrap;margin:10px 0;color:var(--muted)}.sw{display:inline-block;width:12px;height:12px;margin-right:5px;border-radius:3px}.details{margin-top:12px;padding:12px;border:1px solid var(--border);border-radius:10px;background:var(--panel);display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px}.details b{display:block;color:var(--muted);font-weight:500;margin-bottom:2px}.state{font-weight:600}code{font-family:ui-monospace,monospace}h1{font-size:20px;margin:0 0 12px}
</style></head><body><main><h1 id="title"></h1>
<div class="toolbar"><button id="play" type="button">Play</button><button id="prev" type="button">Previous frame</button><button id="next" type="button">Next frame</button><label><input id="showRawLd" type="checkbox"> Show source LD lanes</label><label for="frame">Frame <span id="frameLabel"></span></label><input id="frame" type="range" min="0" value="0" step="1"></div>
<div class="legend"><span><i class="sw" style="background:var(--ego)"></i>Ego route lane</span><span><i class="sw" style="background:var(--left)"></i>Left route lane</span><span><i class="sw" style="background:var(--right)"></i>Right route lane</span><span><i class="sw" style="background:var(--other)"></i>Other lane</span><span><i class="sw" style="background:var(--lead)"></i>Lead vehicle</span><span>dashed translucent box = probable lane extension</span><span style="color:var(--unknown)">purple dashed boundary = intersection attribute</span><span>drivable road boundaries act as solid lane lines</span><span>explicit non-drivable boundaries are excluded</span><span>only dynamic objects are displayed</span></div>
<canvas id="map" class="map" width="1140" height="620" aria-label="Heading-up lane and object map, 95 meters ahead and 25 meters behind"></canvas>
<canvas id="timeline" class="timeline" width="1140" height="84" aria-label="Frame-level following-lane state timeline"></canvas>
<div class="details"><div><b>Scenario state</b><span class="state" id="state"></span></div><div><b>Time / speed</b><span id="motion"></span></div><div><b>Lane IDs</b><span id="lanes"></span></div><div><b>Lead</b><span id="lead"></span></div><div><b>Assignment evidence</b><span id="evidence"></span></div></div>
<script id="payload" type="application/json">__PAYLOAD__</script><script>
const data=JSON.parse(document.getElementById('payload').textContent), map=document.getElementById('map'), ctx=map.getContext('2d'), timeline=document.getElementById('timeline'), tx=timeline.getContext('2d'), slider=document.getElementById('frame'),showRawLd=document.getElementById('showRawLd');
slider.max=Math.max(0,data.frames.length-1); document.getElementById('title').textContent=data.recording_id+' — following-lane debugger';
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim(), laneById=new Map(data.lanes.map(x=>[x.lane_id,x]));
function egoXY(p,f){const dx=p[0]-f.ego_position[0],dy=p[1]-f.ego_position[1],c=Math.cos(f.ego_heading),s=Math.sin(f.ego_heading);return [c*dx+s*dy,-s*dx+c*dy]}
function screen(p){const scale=Math.min(map.width/90,map.height/120),cx=map.width/2,cy=95*scale;return[cx-p[1]*scale,cy-p[0]*scale]}
function path(points,f){ctx.beginPath();points.forEach((p,i)=>{const q=screen(egoXY(p,f));i?ctx.lineTo(q[0],q[1]):ctx.moveTo(q[0],q[1])});ctx.closePath()}
function boundary(points,attributes,f,role){if(!points||points.length<2)return;ctx.beginPath();points.forEach((p,i)=>{const q=screen(egoXY(p,f));i?ctx.lineTo(q[0],q[1]):ctx.moveTo(q[0],q[1])});const intersection=attributes&&attributes.intersection===true,pattern=attributes&&attributes.pattern;ctx.strokeStyle=intersection?css('--unknown'):(role?css(role):css('--other'));ctx.lineWidth=intersection?3:(role?2:1);ctx.setLineDash(intersection||pattern==='virtual'||pattern==='dashed'||pattern==='broken'?[8,6]:[]);ctx.stroke();ctx.setLineDash([])}
function rawLdFeature(feature,f){if(!feature.points_lcs_m||feature.points_lcs_m.length<2)return;const transformed=feature.points_lcs_m.map(p=>egoXY(p,f)),near=transformed.some(q=>q[0]>=-30&&q[0]<=100&&Math.abs(q[1])<=50);if(!near)return;ctx.beginPath();transformed.forEach((p,i)=>{const q=screen(p);i?ctx.lineTo(q[0],q[1]):ctx.moveTo(q[0],q[1])});const pattern=feature.attributes&&feature.attributes.pattern;ctx.strokeStyle=feature.source_kind==='drivable_road_boundary'?css('--right'):css('--unknown');ctx.lineWidth=feature.source_kind==='drivable_road_boundary'?3:2;ctx.setLineDash(pattern==='virtual'||pattern==='dashed'||pattern==='broken'?[7,5]:[]);ctx.stroke();ctx.setLineDash([]);const visible=transformed.find(q=>q[0]>=-25&&q[0]<=95&&Math.abs(q[1])<=42);if(visible){const label=screen(visible);ctx.fillStyle=css('--fg');ctx.fillText((feature.source_kind==='lane_line'?'LD line ':'drivable boundary ')+feature.feature_id,label[0]+4,label[1]-4)}}
function draw(){const f=data.frames[+slider.value];ctx.clearRect(0,0,map.width,map.height);ctx.strokeStyle=css('--border');ctx.lineWidth=1;for(let x=-40;x<=40;x+=10){let a=screen([-25,x]),b=screen([95,x]);ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.stroke()}for(let y=-20;y<=90;y+=10){let a=screen([y,-45]),b=screen([y,45]);ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.stroke()}
const roles=new Map(),segments=new Map();if(f.right_lane.logical_lane_id)roles.set(f.right_lane.logical_lane_id,'--right');if(f.left_lane.logical_lane_id)roles.set(f.left_lane.logical_lane_id,'--left');if(f.ego_lane.logical_lane_id)roles.set(f.ego_lane.logical_lane_id,'--ego');if(f.right_lane.lane_id)segments.set(f.right_lane.lane_id,'right');if(f.left_lane.lane_id)segments.set(f.left_lane.lane_id,'left');if(f.ego_lane.lane_id)segments.set(f.ego_lane.lane_id,'ego');if(showRawLd.checked){for(const feature of data.raw_ld_features)rawLdFeature(feature,f)}for(const bridge of data.bridges){const role=roles.get(bridge.logical_lane_id);if(!role)continue;const near=bridge.polygon_lcs_m.some(p=>{const q=egoXY(p,f);return q[0]>=-30&&q[0]<=100&&Math.abs(q[1])<=50});if(!near)continue;path(bridge.polygon_lcs_m,f);ctx.fillStyle=css(role)+'20';ctx.strokeStyle=css(role);ctx.lineWidth=2;ctx.setLineDash([10,7]);ctx.fill();ctx.stroke();ctx.setLineDash([])}for(const lane of data.lanes){if(!lane.polygon_lcs_m.length)continue;const role=roles.get(lane.logical_lane_id);if(!role&&!showRawLd.checked)continue;const near=lane.polygon_lcs_m.some(p=>{const q=egoXY(p,f);return q[0]>=-30&&q[0]<=100&&Math.abs(q[1])<=50});if(!near)continue;path(lane.polygon_lcs_m,f);ctx.fillStyle=role?css(role)+'38':css('--other')+'10';ctx.strokeStyle=role?css(role):css('--other');ctx.lineWidth=role?3:1;ctx.fill();ctx.stroke();boundary(lane.left_boundary_lcs_m,lane.left_boundary_attributes,f,role);boundary(lane.right_boundary_lcs_m,lane.right_boundary_attributes,f,role);if(segments.has(lane.lane_id)||showRawLd.checked){const q=screen(egoXY(lane.centerline_lcs_m[Math.floor(lane.centerline_lcs_m.length/2)],f));ctx.fillStyle=css('--fg');ctx.fillText((segments.get(lane.lane_id)?segments.get(lane.lane_id)+' ':'physical lane ')+lane.lane_id+(segments.has(lane.lane_id)?' / '+lane.logical_lane_id:''),q[0]+5,q[1]-5)}}
for(const o of f.source_objects){if(!o.position_lcs_m)continue;const p=screen(egoXY(o.position_lcs_m,f)),isLead=f.lead&&String(f.lead.object_id)===String(o.object_id),dynamic=o.annotation_type==='dynamic';ctx.strokeStyle=isLead?css('--lead'):css('--fg');ctx.fillStyle=isLead?css('--lead'):css('--fg');ctx.lineWidth=isLead?4:2;if(dynamic){ctx.beginPath();ctx.arc(p[0],p[1],isLead?8:5,0,Math.PI*2);ctx.fill()}else{ctx.strokeRect(p[0]-6,p[1]-6,12,12);ctx.beginPath();ctx.moveTo(p[0]-5,p[1]-5);ctx.lineTo(p[0]+5,p[1]+5);ctx.moveTo(p[0]+5,p[1]-5);ctx.lineTo(p[0]-5,p[1]+5);ctx.stroke()}}
if(f.lead&&!f.source_objects.some(o=>String(o.object_id)===String(f.lead.object_id))){const p=screen([f.lead.longitudinal_m,f.lead.lateral_m]);ctx.strokeStyle=css('--lead');ctx.lineWidth=3;ctx.setLineDash([5,4]);ctx.beginPath();ctx.arc(p[0],p[1],9,0,Math.PI*2);ctx.stroke();ctx.setLineDash([])}
const ep=screen([0,0]);ctx.fillStyle=css('--ego');ctx.beginPath();ctx.moveTo(ep[0],ep[1]-14);ctx.lineTo(ep[0]-9,ep[1]+10);ctx.lineTo(ep[0]+9,ep[1]+10);ctx.closePath();ctx.fill();
slider.setAttribute('aria-valuetext','frame '+f.frame_index);document.getElementById('frameLabel').textContent=f.frame_index+' / '+data.frames.at(-1).frame_index;document.getElementById('state').textContent=f.state;document.getElementById('motion').textContent=f.time_since_start_s.toFixed(2)+' s · '+(f.speed_mps==null?'invalid':f.speed_mps.toFixed(2)+' m/s');document.getElementById('lanes').textContent='left '+(f.left_lane.lane_id??'—')+' / '+(f.left_lane.logical_lane_id??'—')+' · ego '+(f.ego_lane.lane_id??'—')+' / '+(f.ego_lane.logical_lane_id??'—')+' · right '+(f.right_lane.lane_id??'—')+' / '+(f.right_lane.logical_lane_id??'—');document.getElementById('lead').textContent=f.lead?'#'+f.lead.object_id+' '+f.lead.class+' at '+f.lead.longitudinal_m.toFixed(1)+' m · '+(f.lead.ego_lane_area_source??'invalid area')+' · '+(f.lead.tracking_status??'untracked'):'none';document.getElementById('evidence').textContent=f.reason+' · '+f.ego_lane.confidence+' / '+f.ego_lane.method+' · drivable '+(f.ego_lane.drivable_status??'unknown')+(f.ego_lane.nearest_boundary_normalized_as_lane_line?' · nearest boundary: drivable road boundary normalized as lane line':'')+(f.ego_lane.intersection_connector?' · intersection connector':'');drawTimeline(+slider.value)}
function drawTimeline(selected){tx.clearRect(0,0,timeline.width,timeline.height);const w=timeline.width/data.frames.length,colors={following_lane_with_lead:'--lead',following_lane_without_lead:'--ego',unknown:'--unknown',not_applicable:'--other'};data.frames.forEach((f,i)=>{tx.fillStyle=css(colors[f.state]||'--other');tx.fillRect(i*w,20,Math.max(1,w),34)});tx.strokeStyle=css('--fg');tx.lineWidth=2;tx.strokeRect(selected*w,16,Math.max(3,w),42);tx.fillStyle=css('--fg');tx.fillText('shared frame/time axis',4,12);tx.fillText('0 s',4,72);tx.fillText(data.frames.at(-1).time_since_start_s.toFixed(1)+' s',timeline.width-50,72)}
let timer=null;const play=document.getElementById('play');function stop(){if(timer!==null){clearInterval(timer);timer=null}play.textContent='Play';play.setAttribute('aria-pressed','false')}function togglePlay(){if(timer!==null){stop();return}play.textContent='Pause';play.setAttribute('aria-pressed','true');timer=setInterval(()=>{if(+slider.value>=data.frames.length-1){stop();return}slider.value=+slider.value+1;draw()},100)}slider.addEventListener('input',()=>{stop();draw()});showRawLd.addEventListener('change',draw);play.addEventListener('click',togglePlay);document.getElementById('prev').onclick=()=>{stop();slider.value=Math.max(0,+slider.value-1);draw()};document.getElementById('next').onclick=()=>{stop();slider.value=Math.min(data.frames.length-1,+slider.value+1);draw()};draw();
</script></main></body></html>""".replace("__PAYLOAD__", payload_json)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def run_one(
    canonical_path: Path,
    output_root: Path,
    config: dict[str, Any],
    stop_after: str,
    base_explorer_dir: Path | None = None,
) -> list[Path]:
    recording = json.loads(canonical_path.read_text(encoding="utf-8"))
    result = run_following_lane(recording, config)
    recording_id = result["recording_id"]
    outputs = []
    stage1 = output_root / "01_lane_geometry" / f"{recording_id}_lane_geometry.json"
    write_json(stage1, {"schema_version": "following-lane-geometry-v1", "recording_id": recording_id, "lanes": result["lane_geometry"]})
    outputs.append(stage1)
    if stop_after == "lane-geometry": return outputs
    stage2 = output_root / "02_frame_assignments" / f"{recording_id}_frame_assignments.json"
    write_json(stage2, {"schema_version": "following-lane-assignments-v1", "recording_id": recording_id, "frames": [{key: value for key, value in frame.items() if key != "state"} for frame in result["frames"]]})
    outputs.append(stage2)
    if stop_after == "assignments": return outputs
    stage3 = output_root / "03_tags" / f"{recording_id}_following_lane_tags.json"
    write_json(stage3, {key: value for key, value in result.items() if key != "lane_geometry"})
    outputs.append(stage3)
    if stop_after == "tags": return outputs
    stage4 = output_root / "04_visualization" / f"{recording_id}_following_lane_explorer.html"
    base_explorer_path = None
    if base_explorer_dir is not None:
        base_explorer_path = (
            base_explorer_dir / f"{recording_id}_animated_odld_explorer.html"
        )
        if not base_explorer_path.is_file():
            raise FileNotFoundError(
                f"missing original ODLD explorer: {base_explorer_path}"
            )
    render_html(recording, result, stage4, base_explorer_path)
    outputs.append(stage4)
    return outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recordings", nargs="*", help="Recording IDs; omit to run every canonical ODLD recording")
    parser.add_argument("--canonical-dir", type=Path, default=CANONICAL)
    parser.add_argument("--output-root", type=Path, default=FOLLOWING_LANE)
    parser.add_argument("--config", type=Path, default=Path("configs/following_lane.json"))
    parser.add_argument(
        "--base-explorer-dir",
        type=Path,
        default=Path("C:" + "\\path")
        / "to"
        / "quick_exploration_outputs"
        / "dataset_scene_explorers_odld",
        help="Directory containing the original *_animated_odld_explorer.html files",
    )
    parser.add_argument("--stop-after", choices=STAGES, default="visualization")
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8")) if args.config.is_file() else {}
    if args.recordings:
        inputs = [args.canonical_dir / f"{recording}_canonical_odld_frames.json" for recording in args.recordings]
    else:
        inputs = sorted(args.canonical_dir.glob("*_canonical_odld_frames.json"))
    if not inputs:
        parser.error(f"no canonical ODLD recordings found in {args.canonical_dir}")
    for input_path in inputs:
        if not input_path.is_file(): parser.error(f"missing canonical recording: {input_path}")
        for output in run_one(
            input_path,
            args.output_root,
            config,
            args.stop_after,
            args.base_explorer_dir,
        ):
            print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
