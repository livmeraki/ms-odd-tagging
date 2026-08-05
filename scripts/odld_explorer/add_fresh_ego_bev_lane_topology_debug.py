#!/usr/bin/env python3
"""Duplicate ODLD explorers with an ego-frame lane/topology debug BEV.

The existing ODLD explorer map is LCS/global.  This overlay adds a second
interactive Plotly panel that redraws the same LD/topology/object payload in a
frame-local, ego-heading-up coordinate system:

* x axis: ego-left/right, meters
* y axis: ego-forward/backward, meters
* ego stays fixed at (0, 0)

This is intended for debugging lane-change and topology behavior without
changing the model-facing PNG BEV renderer or the canonical ODLD data.
"""

from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
from typing import Any


STYLE = """
  .freshBevPanel { margin-top:14px; }
  #freshEgoBev { height:640px; }
  .freshBevControls { border-top:1px solid #d7deea; margin-top:14px; padding-top:12px; }
  .freshBevControls h3 { margin:0 0 8px; font-size:14px; }
  .freshBevControls label { display:flex; align-items:center; gap:8px; margin:8px 0; }
  .freshBevStatus { font-size:12px; color:#64748b; margin-top:8px; line-height:1.35; }
"""


CONTROLS = """
    <div class="freshBevControls">
      <h3>Fresh Ego-BEV Lane/Topology Debug</h3>
      <label><input id="showFreshEgoBev" type="checkbox" checked /> Show ego-frame debug BEV</label>
      <label><input id="freshShowLaneLines" type="checkbox" checked /> Lane lines</label>
      <label><input id="freshShowIntersectionLines" type="checkbox" checked /> Intersection=true lines</label>
      <label><input id="freshShowBoundaries" type="checkbox" checked /> Road boundaries</label>
      <label><input id="freshShowRoadmarks" type="checkbox" checked /> Roadmarks</label>
      <label><input id="freshShowDetectedTopology" type="checkbox" checked /> Detected topology polygons</label>
      <label><input id="freshShowObjects" type="checkbox" checked /> Current object footprints</label>
      <label><input id="freshShowTrajectory" type="checkbox" checked /> Ego trail and future path</label>
      <div id="freshBevStatus" class="freshBevStatus"></div>
    </div>
"""


PANEL = """
    <div class="panel freshBevPanel"><div id="freshEgoBev"></div></div>
"""


SCRIPT = r"""
function freshEgoPose() {
  return {
    x: Number(traj.x[currentIndex] || 0),
    y: Number(traj.y[currentIndex] || 0),
    yaw: Number(traj.yaw_deg[currentIndex] || 0) * Math.PI / 180
  };
}

function freshLocalPoint(x, y, pose) {
  const dx = Number(x) - pose.x;
  const dy = Number(y) - pose.y;
  return [
    -Math.sin(pose.yaw) * dx + Math.cos(pose.yaw) * dy,
     Math.cos(pose.yaw) * dx + Math.sin(pose.yaw) * dy
  ];
}

function freshTransformSeries(xs, ys, pose) {
  const outX = [], outY = [];
  for (let i = 0; i < xs.length; i++) {
    if (xs[i] == null || ys[i] == null) {
      outX.push(null); outY.push(null);
      continue;
    }
    const p = freshLocalPoint(xs[i], ys[i], pose);
    outX.push(p[0]); outY.push(p[1]);
  }
  return [outX, outY];
}

function freshFeatureTrace(features, name, color, width, opacity, dash='solid') {
  const pose = freshEgoPose();
  const xs = [], ys = [], custom = [];
  for (const feature of features || []) {
    const [lx, ly] = freshTransformSeries(feature.x || [], feature.y || [], pose);
    let visible = false;
    for (let i = 0; i < lx.length; i++) {
      if (lx[i] == null || ly[i] == null) continue;
      if (Math.abs(lx[i]) <= 45 && ly[i] >= -45 && ly[i] <= 110) visible = true;
      xs.push(lx[i]); ys.push(ly[i]);
      custom.push([String(feature.id), feature.pattern || feature.attribute || feature.class || feature.subclass || '']);
    }
    xs.push(null); ys.push(null); custom.push(null);
    if (!visible) {
      for (let i = 0; i < lx.length + 1; i++) {
        xs.pop(); ys.pop(); custom.pop();
      }
    }
  }
  if (!xs.length) return null;
  return {
    type: 'scattergl', mode: 'lines', name,
    x: xs, y: ys,
    line: {color, width, dash},
    opacity,
    customdata: custom,
    hovertemplate: `${name}<br>id=%{customdata[0]}<br>detail=%{customdata[1]}<br>ego-left=%{x:.2f} m<br>ego-forward=%{y:.2f} m<extra></extra>`
  };
}

function freshTopologyPolygonTrace(component) {
  if (!component || !component.polygon || component.polygon.length < 3) return null;
  const pose = freshEgoPose();
  const local = component.polygon.map(point => freshLocalPoint(point[0], point[1], pose));
  const closed = local.concat([local[0]]);
  const cls = component.class || 'normal';
  const colors = {
    roundabout: ['rgba(124,58,237,0.22)', '#7c3aed'],
    'x-intersection': ['rgba(220,38,38,0.20)', '#dc2626'],
    't-intersection': ['rgba(234,88,12,0.20)', '#ea580c'],
    'y-intersection': ['rgba(217,70,239,0.20)', '#d946ef'],
    intersection_unknown: ['rgba(8,145,178,0.18)', '#0891b2'],
    normal: ['rgba(100,116,139,0.12)', '#64748b']
  }[cls] || ['rgba(100,116,139,0.12)', '#64748b'];
  return {
    type: 'scatter', mode: 'lines', fill: 'toself',
    name: `detected topology: ${cls}`,
    x: closed.map(point => point[0]),
    y: closed.map(point => point[1]),
    fillcolor: colors[0],
    line: {color: colors[1], width: cls === 'normal' ? 2 : 4},
    customdata: closed.map(() => [
      component.id, cls, component.confidence || 0,
      component.externalCorridorCandidateCount || 0,
      component.physicalArmCandidateCount || 0,
      component.decisionReason || ''
    ]),
    hovertemplate: 'topology %{customdata[0]}<br>class=%{customdata[1]}<br>confidence=%{customdata[2]:.2f}<br>external corridors=%{customdata[3]} · physical arms=%{customdata[4]}<br>%{customdata[5]}<extra></extra>'
  };
}

function freshEgoTrace() {
  const halfW = 1.0, front = 2.4, rear = -2.4;
  return [
    {
      type: 'scatter', mode: 'lines', fill: 'toself', name: 'ego footprint',
      x: [-halfW, halfW, halfW, -halfW, -halfW],
      y: [rear, rear, front, front, rear],
      fillcolor: 'rgba(22,163,74,0.26)',
      line: {color: '#16a34a', width: 3},
      hovertemplate: 'ego fixed local frame<extra></extra>'
    },
    {
      type: 'scattergl', mode: 'lines+markers+text', name: 'ego forward',
      x: [0, 0], y: [0, 12],
      text: ['', 'forward'],
      textposition: 'top center',
      marker: {size: [6, 10], color: '#16a34a'},
      line: {color: '#16a34a', width: 3},
      hoverinfo: 'skip'
    }
  ];
}

function freshTrajectoryTrace() {
  if (!document.getElementById('freshShowTrajectory')?.checked) return [];
  const pose = freshEgoPose();
  const start = Math.max(0, currentIndex - 40);
  const end = Math.min(traj.x.length - 1, currentIndex + 80);
  const pastX = [], pastY = [], futureX = [], futureY = [];
  for (let i = start; i <= currentIndex; i++) {
    const p = freshLocalPoint(traj.x[i], traj.y[i], pose);
    pastX.push(p[0]); pastY.push(p[1]);
  }
  for (let i = currentIndex; i <= end; i++) {
    const p = freshLocalPoint(traj.x[i], traj.y[i], pose);
    futureX.push(p[0]); futureY.push(p[1]);
  }
  return [
    {type: 'scattergl', mode: 'lines', name: 'ego past in current BEV', x: pastX, y: pastY, line: {color: 'rgba(37,99,235,0.9)', width: 4}, hoverinfo: 'skip'},
    {type: 'scattergl', mode: 'lines', name: 'ego future in current BEV', x: futureX, y: futureY, line: {color: 'rgba(37,99,235,0.55)', width: 3, dash: 'dash'}, hoverinfo: 'skip'}
  ];
}

function freshObjectFootprintTrace(selectedClasses) {
  if (!document.getElementById('freshShowObjects')?.checked) return null;
  const pose = freshEgoPose();
  const xs = [], ys = [], labels = [];
  for (const object of objects) {
    if (!selectedClasses.has(object.className) || !isActiveObject(object)) continue;
    const state = objectState(object, currentIndex);
    if (state.x == null || state.y == null) continue;
    const corners = cornersFor(object, state);
    if (!corners) continue;
    for (const point of corners) {
      const p = freshLocalPoint(point[0], point[1], pose);
      xs.push(p[0]); ys.push(p[1]); labels.push([object.objectId, object.className]);
    }
    xs.push(null); ys.push(null); labels.push(null);
  }
  if (!xs.length) return null;
  return {
    type: 'scattergl', mode: 'lines', name: 'objects in ego BEV',
    x: xs, y: ys,
    line: {color: 'rgba(17,24,39,0.42)', width: 1.4},
    customdata: labels,
    hovertemplate: 'object #%{customdata[0]}<br>%{customdata[1]}<extra></extra>'
  };
}

function freshGridTraces() {
  const traces = [];
  for (const x of [-20, -10, 10, 20]) {
    traces.push({type: 'scattergl', mode: 'lines', name: `lateral ${x}m`, showlegend: false, x: [x, x], y: [-30, 90], line: {color: 'rgba(148,163,184,0.25)', width: 1, dash: 'dot'}, hoverinfo: 'skip'});
  }
  for (const y of [0, 20, 40, 60, 80]) {
    traces.push({type: 'scattergl', mode: 'lines', name: `forward ${y}m`, showlegend: false, x: [-30, 30], y: [y, y], line: {color: 'rgba(148,163,184,0.22)', width: 1, dash: 'dot'}, hoverinfo: 'skip'});
  }
  return traces;
}

function renderFreshEgoBevDebug() {
  const target = document.getElementById('freshEgoBev');
  const status = document.getElementById('freshBevStatus');
  if (!target) return;
  if (!document.getElementById('showFreshEgoBev')?.checked) {
    target.style.display = 'none';
    if (status) status.textContent = 'Ego-frame debug BEV hidden.';
    return;
  }
  target.style.display = '';
  const selected = new Set(selectedClasses());
  const traces = [...freshGridTraces(), ...freshTrajectoryTrace(), ...freshEgoTrace()];
  if (document.getElementById('freshShowDetectedTopology')?.checked) {
    const frameComponentId = ldFrames.topologyComponentId[currentIndex];
    const components = frameComponentId
      ? (ldTopology.components || []).filter(component => component.id === frameComponentId)
      : (ldTopology.components || []);
    for (const component of components) {
      const trace = freshTopologyPolygonTrace(component);
      if (trace) traces.push(trace);
    }
  }
  if (document.getElementById('freshShowLaneLines')?.checked) {
    const regular = ld.laneLines.filter(feature => feature.intersection !== true);
    const trace = freshFeatureTrace(regular, 'lane lines ego BEV', '#0ea5e9', 1.4, 0.78);
    if (trace) traces.push(trace);
  }
  if (document.getElementById('freshShowIntersectionLines')?.checked) {
    const trace = freshFeatureTrace(ld.laneLines.filter(feature => feature.intersection === true), 'intersection=true lines ego BEV', '#d946ef', 2.5, 0.9);
    if (trace) traces.push(trace);
  }
  if (document.getElementById('freshShowBoundaries')?.checked) {
    const trace = freshFeatureTrace(ld.boundaries || [], 'road boundaries ego BEV', '#f59e0b', 2.0, 0.72);
    if (trace) traces.push(trace);
  }
  if (document.getElementById('freshShowRoadmarks')?.checked) {
    const trace = freshFeatureTrace((ld.roadmarks || []).filter(feature => !feature.ignored), 'roadmarks ego BEV', '#e11d48', 2.2, 0.78);
    if (trace) traces.push(trace);
  }
  const objectTrace = freshObjectFootprintTrace(selected);
  if (objectTrace) traces.push(objectTrace);

  Plotly.react('freshEgoBev', traces, {
    margin: {l: 58, r: 250, t: 22, b: 50},
    xaxis: {title: 'ego-left / ego-right (m)', range: [-30, 30], zeroline: true, zerolinecolor: '#111827', scaleanchor: 'y', scaleratio: 1},
    yaxis: {title: 'ego-forward (m)', range: [-30, 90], zeroline: true, zerolinecolor: '#111827'},
    legend: {orientation: 'v', x: 1.04, xanchor: 'left', y: 1, yanchor: 'top', font: {size: 10}},
    hovermode: 'closest',
    uirevision: 'fresh-ego-bev-fixed'
  }, {responsive: true});

  if (status) {
    const topologyClass = ldFrames.topologyClass[currentIndex] || 'normal';
    const subtype = ldFrames.activeTopologySubtype[currentIndex] || ldFrames.topologySubtype[currentIndex] || topologyClass;
    const confidence = Number(ldFrames.topologyConfidence[currentIndex] || 0).toFixed(2);
    const roundabout = ldFrames.laneGeometryRoundabout && ldFrames.laneGeometryRoundabout[currentIndex];
    const roundaboutText = roundabout ? ` | roundabout source=${roundabout.source} radius=${roundabout.radius_m}m coverage=${roundabout.angular_coverage_deg}deg` : '';
    status.textContent = `frame ${currentIndex} | ego-frame BEV | topology=${topologyClass}/${subtype} conf=${confidence} | nearby lines=${ldFrames.lineCount[currentIndex]} | intersection lines=${ldFrames.intersectionLineCount[currentIndex]}${roundaboutText}`;
  }
}
"""


def inject(page: str) -> str:
    replacements = [
        ("</style>", STYLE + "\n</style>"),
        (
            '    <label for="classFilter">Object classes</label>',
            CONTROLS + '    <label for="classFilter">Object classes</label>',
        ),
        (
            '    <div class="panel"><div id="map"></div></div>',
            '    <div class="panel"><div id="map"></div></div>\n' + PANEL,
        ),
        ("function render() {\n", SCRIPT + "\nfunction render() {\n"),
        ("  Plotly.react('map', traces, {", "  renderFreshEgoBevDebug();\n  Plotly.react('map', traces, {"),
        (
            "filter.addEventListener('change', render);",
            "filter.addEventListener('change', render);\n"
            "for (const id of ['showFreshEgoBev','freshShowLaneLines','freshShowIntersectionLines','freshShowBoundaries','freshShowRoadmarks','freshShowDetectedTopology','freshShowObjects','freshShowTrajectory']) document.getElementById(id)?.addEventListener('change', render);",
        ),
    ]
    for old, new in replacements:
        count = page.count(old)
        if count != 1:
            raise ValueError(f"expected one marker {old!r}, found {count}")
        page = page.replace(old, new, 1)
    return page


def output_name(source: Path) -> str:
    suffix = "_animated_odld_explorer.html"
    if source.name.endswith(suffix):
        return source.name[: -len(suffix)] + "_animated_odld_explorer_fresh_ego_bev_debug.html"
    return source.stem + "_fresh_ego_bev_debug.html"


def index_html(rows: list[dict[str, Any]]) -> str:
    payload = json.dumps(rows, ensure_ascii=True, separators=(",", ":"))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fresh Ego-BEV Lane/Topology Debug Explorers</title>
<style>
body{{margin:0;font-family:Arial,sans-serif;background:#eef2f6;color:#17202a}}header{{padding:18px 24px;background:#17324d;color:white}}h1{{font-size:21px;margin:0 0 6px}}p{{margin:0;color:#dbeafe;font-size:13px}}.toolbar{{position:sticky;top:0;background:#f8fafc;border-bottom:1px solid #cbd5e1;padding:12px 18px;display:flex;gap:10px;align-items:center;z-index:3}}input,select{{height:34px;border:1px solid #cbd5e1;border-radius:6px;background:white;padding:0 9px}}main{{padding:16px 18px;display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:12px}}a.card{{display:block;background:white;border:1px solid #d7dee8;border-radius:8px;padding:12px;color:inherit;text-decoration:none}}a.card:hover{{border-color:#2563eb;box-shadow:0 4px 14px rgba(37,99,235,.12)}}h2{{font-size:14px;margin:0 0 8px;overflow-wrap:anywhere}}.metrics{{display:flex;gap:6px;flex-wrap:wrap}}.metrics span{{background:#edf2f7;border-radius:999px;padding:3px 7px;font-size:11px;color:#334155}}.empty{{padding:20px;color:#64748b}}
</style></head><body>
<header><h1>Fresh Ego-BEV Lane/Topology Debug Explorers</h1><p>Duplicated ODLD explorers with ego-heading-up lane and topology debug BEV.</p></header>
<div class="toolbar"><input id="q" placeholder="recording search"><select id="topology"><option value="all">all topology classes</option></select><span id="count"></span></div>
<main id="cards"></main>
<script>
const ROWS={payload};
const q=document.getElementById('q');const topology=document.getElementById('topology');const cards=document.getElementById('cards');const count=document.getElementById('count');
for (const cls of [...new Set(ROWS.flatMap(row => row.topologyClasses || []))].sort()) {{ const opt=document.createElement('option'); opt.value=cls; opt.textContent=cls; topology.appendChild(opt); }}
function render() {{
  const term=q.value.toLowerCase(); const cls=topology.value;
  const rows=ROWS.filter(row => (!term || row.recording.toLowerCase().includes(term)) && (cls==='all' || (row.topologyClasses || []).includes(cls)));
  count.textContent=`${{rows.length}} / ${{ROWS.length}}`;
  cards.innerHTML=rows.length ? rows.map(row => `<a class="card" href="${{row.file}}"><h2>${{row.recording}}</h2><div class="metrics"><span>${{row.frames}} frames</span><span>${{row.tagEvents}} tag events</span><span>${{(row.topologyClasses || []).join(', ') || 'normal'}}</span></div></a>`).join('') : '<div class="empty">No matching explorers.</div>';
}}
q.addEventListener('input', render); topology.addEventListener('change', render); render();
</script></body></html>"""


def embedded_data_summary(page: str) -> dict[str, Any]:
    marker = "const DATA = "
    start = page.find(marker)
    if start < 0:
        return {}
    start += len(marker)
    end = page.find(";\nconst palette", start)
    if end < 0:
        return {}
    data = json.loads(page[start:end])
    tag_events = ((data.get("tags") or {}).get("events") or [])
    topology_classes = sorted(
        {
            item
            for item in (((data.get("ldTopology") or {}).get("summary") or {}).get("classes") or [])
            if item
        }
    )
    return {
        "recording": (data.get("summary") or {}).get("recording"),
        "frames": (data.get("summary") or {}).get("frames"),
        "tagEvents": len(tag_events),
        "topologyClasses": topology_classes,
    }


def convert_one(source: Path, output: Path) -> dict[str, Any]:
    page = source.read_text(encoding="utf-8")
    summary = embedded_data_summary(page)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(inject(page), encoding="utf-8")
    return {
        **summary,
        "file": output.name,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-html", type=Path, help="One ODLD explorer HTML to duplicate")
    parser.add_argument("--output-html", type=Path)
    parser.add_argument("--source-dir", type=Path, help="Directory of ODLD explorer HTML files")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--index-path", type=Path)
    parser.add_argument("recordings", nargs="*", help="Optional recording IDs when using --source-dir")
    args = parser.parse_args(argv)

    if args.source_html:
        output = args.output_html or args.source_html.with_name(output_name(args.source_html))
        convert_one(args.source_html, output)
        print(f"Wrote {output}")
        return 0

    if not args.source_dir or not args.output_dir:
        parser.error("provide --source-html or --source-dir/--output-dir")

    selected = set(args.recordings)
    rows = []
    for source in sorted(args.source_dir.glob("*_animated_odld_explorer.html")):
        recording = source.name.split("_animated_odld_explorer.html", 1)[0]
        if selected and recording not in selected:
            continue
        rows.append(convert_one(source, args.output_dir / output_name(source)))

    index_path = args.index_path or args.output_dir.with_name(args.output_dir.name + "_index.html")
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(index_html(rows), encoding="utf-8")
    manifest = {
        "schema_version": "fresh-ego-bev-lane-topology-debug-v1",
        "source_dir": str(args.source_dir),
        "output_dir": str(args.output_dir),
        "index_path": str(index_path),
        "recording_count": len(rows),
        "coordinate_frame": "ego_heading_up_local_frame",
        "x_axis": "ego_left_m",
        "y_axis": "ego_forward_m",
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(rows)} fresh ego-BEV debug explorer(s)")
    print(f"Wrote index: {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
