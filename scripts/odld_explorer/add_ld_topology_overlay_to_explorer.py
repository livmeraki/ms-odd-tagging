#!/usr/bin/env python3
"""Duplicate ODLD explorers and overlay LD topology detection results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


STYLE = """
  .ldTopologyPanel { border-top:1px solid #d7deea; margin-top:14px; padding-top:12px; }
  .ldTopologyPanel h3 { margin:0 0 8px; font-size:14px; }
  .ldTopologyPanel label { display:flex; align-items:center; gap:8px; margin:8px 0; }
  .ldTopologyLegend { display:grid; gap:5px; font-size:12px; color:#475569; }
  .ldTopologyLegend span { display:inline-flex; align-items:center; gap:6px; }
  .ldTopologySwatch { width:18px; height:8px; border-radius:999px; display:inline-block; }
  .ldTopologyStatus { font-size:12px; color:#64748b; margin-top:8px; line-height:1.35; }
"""


CONTROLS = """
    <div class="ldTopologyPanel">
      <h3>LD Topology Overlay</h3>
      <label><input id="showLdTopology" type="checkbox" checked /> Show detected topology</label>
      <label><input id="showLdTopologyAllComponents" type="checkbox" checked /> Show all components</label>
      <label><input id="showLdTopologyLanes" type="checkbox" checked /> Show reconstructed topology lanes</label>
      <label><input id="showLdTopologyRawIntersection" type="checkbox" checked /> Show raw intersection=true lines</label>
      <label><input id="showLdTopologyRawOther" type="checkbox" /> Show raw not intersection=true lines</label>
      <div class="ldTopologyLegend">
        <span><i class="ldTopologySwatch" style="background:#dc2626"></i>Raw intersection=true line</span>
        <span><i class="ldTopologySwatch" style="background:#94a3b8"></i>Raw not intersection=true line</span>
        <span><i class="ldTopologySwatch" style="background:#ef4444"></i>Strong evidence lane</span>
        <span><i class="ldTopologySwatch" style="background:#f59e0b"></i>Partial evidence lane</span>
        <span><i class="ldTopologySwatch" style="background:#2563eb"></i>Core polygon and physical arms</span>
      </div>
      <div id="ldTopologyStatus" class="ldTopologyStatus"></div>
    </div>
"""


def _json_for_script(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/")


def raw_line_payload(recording: dict[str, Any] | None) -> dict[str, Any]:
    if recording is None:
        return {"lines": []}
    store = recording.get("ld_feature_store") or {}
    points = {
        str(point.get("point_id")): point.get("position_lcs_m", [])[:2]
        for point in store.get("points", [])
        if len(point.get("position_lcs_m") or []) >= 2
    }
    lines = []
    for line in store.get("lane_lines", []):
        attrs = line.get("attributes") or {}
        line_points = [
            points[str(point_id)]
            for point_id in line.get("point_ids", [])
            if str(point_id) in points
        ]
        if len(line_points) >= 2:
            lines.append(
                {
                    "line_id": str(line.get("line_id")),
                    "intersection": bool(attrs.get("intersection") is True),
                    "pattern": attrs.get("pattern"),
                    "points_lcs_m": line_points,
                }
            )
    return {"lines": lines}


def overlay_script(result: dict[str, Any], raw_lines: dict[str, Any]) -> str:
    payload = _json_for_script(result)
    raw_payload = _json_for_script(raw_lines)
    return f"""
const LD_TOPOLOGY = {payload};
const LD_TOPOLOGY_RAW = {raw_payload};
const LD_TOPOLOGY_FRAMES = Object.fromEntries((LD_TOPOLOGY.frames || []).map(frame => [Number(frame.frame_index), frame]));
const LD_TOPOLOGY_COMPONENTS = Object.fromEntries((LD_TOPOLOGY.components || []).map(component => [component.component_id, component]));
const LD_TOPOLOGY_LANES = Object.fromEntries((LD_TOPOLOGY.lanes || []).map(lane => [lane.lane_id, lane]));

function ldTopologyLineCollectionTrace(items, name, color, width, opacity) {{
  const xs = [], ys = [], labels = [];
  for (const item of items || []) {{
    const points = item.points_lcs_m || item.centerline_lcs_m || [];
    if (points.length < 2) continue;
    for (const point of points) {{
      xs.push(point[0]);
      ys.push(point[1]);
      labels.push([item.line_id || item.lane_id || item.arm_id || '', item.intersection ?? '', item.pattern || item.intersection_evidence || '']);
    }}
    xs.push(null);
    ys.push(null);
    labels.push(null);
  }}
  if (!xs.length) return null;
  return {{
    type: 'scattergl',
    mode: 'lines',
    name,
    x: xs,
    y: ys,
    line: {{color, width}},
    opacity,
    hovertemplate: `${{name}}<br>id=%{{customdata[0]}}<br>intersection=%{{customdata[1]}}<br>detail=%{{customdata[2]}}<extra></extra>`,
    customdata: labels
  }};
}}

function ldTopologyPolygonTrace(points, name, color, fillOpacity, width, customdata) {{
  if (!points || points.length < 3) return null;
  const closed = points.concat([points[0]]);
  return {{
    type: 'scatter',
    mode: 'lines',
    name,
    x: closed.map(p => p[0]),
    y: closed.map(p => p[1]),
    fill: 'toself',
    fillcolor: color.replace('OPACITY', String(fillOpacity)),
    line: {{color: color.replace('OPACITY', '0.95'), width}},
    hovertemplate: `${{name}}<br>%{{customdata}}<extra></extra>`,
    customdata: closed.map(() => customdata || '')
  }};
}}

function ldTopologyArmTraces(component) {{
  const traces = [];
  if (!component) return traces;
  const xs = [], ys = [], labels = [];
  for (const arm of component.arms || []) {{
    const center = component.center_lcs_m;
    const point = arm.crossing_point_lcs_m;
    xs.push(center[0], point[0], null);
    ys.push(center[1], point[1], null);
    labels.push(arm.arm_id, arm.arm_id, null);
  }}
  if (xs.length) {{
    traces.push({{
      type: 'scatter',
      mode: 'lines',
      name: 'LD topology physical arms',
      x: xs,
      y: ys,
      line: {{color: 'rgba(37,99,235,0.95)', width: 3}},
      hovertemplate: 'arm=%{{customdata}}<extra></extra>',
      customdata: labels
    }});
  }}
  const ax = [], ay = [], text = [], labels2 = [];
  for (const arm of component.arms || []) {{
    ax.push(arm.crossing_point_lcs_m[0]);
    ay.push(arm.crossing_point_lcs_m[1]);
    text.push(`${{Math.round(arm.angle_deg)}}°`);
    labels2.push(`${{arm.arm_id}} | lanes=${{(arm.lane_ids || []).join(',')}}`);
  }}
  if (ax.length) {{
    traces.push({{
      type: 'scatter',
      mode: 'markers+text',
      name: 'LD topology arm crossings',
      x: ax,
      y: ay,
      text,
      textposition: 'top center',
      marker: {{color: '#2563eb', size: 9}},
      hovertemplate: '%{{customdata}}<extra></extra>',
      customdata: labels2
    }});
  }}
  return traces;
}}

function ldTopologyLaneTraces(component) {{
  if (!document.getElementById('showLdTopologyLanes')?.checked || !component) return [];
  const traces = [];
  const laneIds = component.lane_ids || [];
  for (const laneId of laneIds) {{
    const lane = LD_TOPOLOGY_LANES[laneId];
    if (!lane) continue;
    const strong = lane.intersection_evidence === 'strong';
    const partial = lane.intersection_evidence === 'partial';
    const color = strong ? 'rgba(239,68,68,OPACITY)' : partial ? 'rgba(245,158,11,OPACITY)' : 'rgba(148,163,184,OPACITY)';
    const trace = ldTopologyPolygonTrace(
      lane.polygon_lcs_m,
      `LD ${{lane.intersection_evidence}} lane`,
      color,
      strong ? 0.24 : 0.18,
      strong ? 2 : 1,
      `lane=${{lane.lane_id}} | left=${{lane.left_boundary_intersection}} | right=${{lane.right_boundary_intersection}}`
    );
    if (trace) traces.push(trace);
  }}
  return traces;
}}

function addLdTopologyTraces(traces) {{
  const status = document.getElementById('ldTopologyStatus');
  const frame = LD_TOPOLOGY_FRAMES[Number(currentIndex)];
  const enabled = document.getElementById('showLdTopology')?.checked;
  if (document.getElementById('showLdTopologyRawOther')?.checked) {{
    const rawOther = ldTopologyLineCollectionTrace((LD_TOPOLOGY_RAW.lines || []).filter(line => !line.intersection), 'Raw LD not intersection=true lines', 'rgba(148,163,184,0.35)', 1, 0.8);
    if (rawOther) traces.push(rawOther);
  }}
  if (document.getElementById('showLdTopologyRawIntersection')?.checked) {{
    const rawTrue = ldTopologyLineCollectionTrace((LD_TOPOLOGY_RAW.lines || []).filter(line => line.intersection), 'Raw LD intersection=true lines', 'rgba(220,38,38,0.80)', 2, 0.95);
    if (rawTrue) traces.push(rawTrue);
  }}
  if (!enabled || !frame) {{
    if (status) status.textContent = frame ? 'LD topology overlay hidden.' : `No LD topology result for frame ${{currentIndex}}.`;
    return;
  }}
  const components = document.getElementById('showLdTopologyAllComponents')?.checked
    ? (LD_TOPOLOGY.components || [])
    : [LD_TOPOLOGY_COMPONENTS[frame.topology_component_id]].filter(Boolean);
  for (const component of components) {{
    for (const trace of ldTopologyLaneTraces(component)) traces.push(trace);
    const cls = component.classification || {{}};
    const core = ldTopologyPolygonTrace(
      component.core_polygon_lcs_m,
      `LD core ${{cls.topology_class || ''}}`,
      'rgba(37,99,235,OPACITY)',
      0.16,
      4,
      `component=${{component.component_id}} | class=${{cls.topology_class}} | arms=${{cls.arm_count}} | conf=${{cls.topology_confidence}}`
    );
    if (core) traces.push(core);
    traces.push(...ldTopologyArmTraces(component));
    if (component.center_lcs_m) {{
      traces.push({{
        type: 'scatter',
        mode: 'markers',
        name: 'LD topology component center',
        x: [component.center_lcs_m[0]],
        y: [component.center_lcs_m[1]],
        marker: {{color: '#111827', size: 10, symbol: 'x'}},
        hovertemplate: `component=${{component.component_id}}<extra></extra>`
      }});
    }}
  }}
  if (status) {{
    const reason = frame.decision_reason || '';
    status.textContent = `frame ${{frame.frame_index}} | ${{frame.topology_class}} | conf=${{frame.topology_confidence}} | inside=${{frame.ego_inside_topology_polygon}} | dist=${{frame.distance_to_topology_polygon_m ?? 'n/a'}}m | arms=${{frame.arm_count}} | ${{reason}}`;
  }}
}}
"""


def inject_overlay(page: str, result: dict[str, Any], raw_lines: dict[str, Any]) -> str:
    markers = {
        "</style>": STYLE + "\n</style>",
        '    <label for="classFilter">Object classes</label>': CONTROLS + '    <label for="classFilter">Object classes</label>',
        "const DATA =": overlay_script(result, raw_lines) + "\nconst DATA =",
        "  Plotly.react('map', traces, {": "  addLdTopologyTraces(traces);\n  Plotly.react('map', traces, {",
        "filter.addEventListener('change', render);":
            "filter.addEventListener('change', render);\n"
            "for (const id of ['showLdTopology','showLdTopologyAllComponents','showLdTopologyLanes','showLdTopologyRawIntersection','showLdTopologyRawOther']) document.getElementById(id)?.addEventListener('change', render);",
    }
    for old, new in markers.items():
        count = page.count(old)
        if count != 1:
            raise ValueError(f"Unable to inject LD topology overlay: expected one marker {old!r}, found {count}")
        page = page.replace(old, new, 1)
    return page


def output_name(source: Path) -> str:
    suffix = "_animated_odld_explorer.html"
    if source.name.endswith(suffix):
        return source.name[: -len(suffix)] + "_animated_odld_explorer_w_ld_topology.html"
    return source.stem + "_w_ld_topology.html"


def result_path_for(source: Path, result_dir: Path) -> Path:
    recording = source.name.split("_animated_odld_explorer", 1)[0]
    return result_dir / f"{recording}_ld_topology.json"


def convert_one(source: Path, result_path: Path, output: Path, canonical_json: Path | None = None) -> None:
    result = json.loads(result_path.read_text(encoding="utf-8"))
    recording = (
        json.loads(canonical_json.read_text(encoding="utf-8"))
        if canonical_json is not None and canonical_json.is_file()
        else None
    )
    page = source.read_text(encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(inject_overlay(page, result, raw_line_payload(recording)), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-html", type=Path, help="One ODLD explorer HTML to duplicate")
    parser.add_argument("--ld-topology-result", type=Path, help="LD topology JSON for --source-html")
    parser.add_argument("--canonical-json", type=Path, help="Canonical ODLD JSON used to add raw line traces")
    parser.add_argument("--output-html", type=Path, help="Output HTML for --source-html")
    parser.add_argument("--source-dir", type=Path, help="Directory of ODLD explorer HTML files")
    parser.add_argument("--result-dir", type=Path, default=Path("outputs/ld_topology/results"))
    parser.add_argument("--canonical-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)

    if args.source_html:
        if not args.ld_topology_result:
            parser.error("--ld-topology-result is required with --source-html")
        output = args.output_html or args.source_html.with_name(output_name(args.source_html))
        convert_one(args.source_html, args.ld_topology_result, output, args.canonical_json)
        print(f"Wrote {output}")
        return 0

    if not args.source_dir or not args.output_dir:
        parser.error("provide either --source-html/--ld-topology-result or --source-dir/--output-dir")

    count = 0
    skipped = 0
    for source in sorted(args.source_dir.glob("*_animated_odld_explorer.html")):
        result_path = result_path_for(source, args.result_dir)
        if not result_path.is_file():
            skipped += 1
            continue
        recording = source.name.split("_animated_odld_explorer", 1)[0]
        canonical_json = (
            args.canonical_dir / f"{recording}_canonical_odld_frames.json"
            if args.canonical_dir
            else None
        )
        convert_one(source, result_path, args.output_dir / output_name(source), canonical_json)
        count += 1
    print(f"Wrote {count} LD topology explorer overlays; skipped {skipped} without results")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
