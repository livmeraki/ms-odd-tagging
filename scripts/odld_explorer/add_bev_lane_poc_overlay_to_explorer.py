#!/usr/bin/env python3
"""Duplicate ODLD explorers and overlay BEV lane POC results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


STYLE = """
  .bevLanePocPanel { border-top:1px solid #d7deea; margin-top:14px; padding-top:12px; }
  .bevLanePocPanel h3 { margin:0 0 8px; font-size:14px; }
  .bevLanePocPanel label { display:flex; align-items:center; gap:8px; margin:8px 0; }
  .bevLanePocLegend { display:grid; gap:5px; font-size:12px; color:#475569; }
  .bevLanePocLegend span { display:inline-flex; align-items:center; gap:6px; }
  .bevLanePocSwatch { width:18px; height:8px; border-radius:999px; display:inline-block; }
  .bevLanePocStatus { font-size:12px; color:#64748b; margin-top:8px; line-height:1.35; }
"""


CONTROLS = """
    <div class="bevLanePocPanel">
      <h3>BEV Lane POC Overlay</h3>
      <label><input id="showBevLanePoc" type="checkbox" checked /> Show BEV-selected lanes</label>
      <label><input id="showBevLaneCandidates" type="checkbox" /> Show BEV candidate lanes</label>
      <div class="bevLanePocLegend">
        <span><i class="bevLanePocSwatch" style="background:#16a34a"></i>Ego lane</span>
        <span><i class="bevLanePocSwatch" style="background:#0284c7"></i>Left adjacent</span>
        <span><i class="bevLanePocSwatch" style="background:#d97706"></i>Right adjacent</span>
        <span><i class="bevLanePocSwatch" style="background:#94a3b8"></i>Other BEV candidates</span>
      </div>
      <div id="bevLanePocStatus" class="bevLanePocStatus"></div>
    </div>
"""


def _json_for_script(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/")


def overlay_script(result: dict[str, Any]) -> str:
    payload = _json_for_script(result)
    return f"""
const BEV_LANE_POC = {payload};
const BEV_LANE_POC_FRAMES = Object.fromEntries((BEV_LANE_POC.frames || []).map(frame => [Number(frame.frame_index), frame]));

function bevLanePocPolygonTrace(lane, name, color, opacity, width) {{
  const points = lane && lane.polygon_lcs_m ? lane.polygon_lcs_m : [];
  if (!points.length) return null;
  const closed = points.concat([points[0]]);
  return {{
    type: 'scatter',
    mode: 'lines',
    name,
    x: closed.map(p => p[0]),
    y: closed.map(p => p[1]),
    fill: 'toself',
    fillcolor: color.replace('OPACITY', String(opacity)),
    line: {{color: color.replace('OPACITY', '0.95'), width}},
    hovertemplate: `${{name}}<br>lane=%{{customdata[0]}}<br>confidence=%{{customdata[1]}}<extra></extra>`,
    customdata: closed.map(() => [lane.lane_id, lane.confidence ?? lane.pair_score ?? null])
  }};
}}

function bevLanePocCandidateTrace(frame) {{
  if (!document.getElementById('showBevLaneCandidates')?.checked) return null;
  const xs = [], ys = [], labels = [];
  const selected = new Set([
    frame.ego_lane?.lane_id,
    frame.left_adjacent?.lane_id,
    frame.right_adjacent?.lane_id
  ]);
  for (const lane of frame.candidate_lanes || []) {{
    if (selected.has(lane.lane_id) || !lane.polygon_lcs_m?.length) continue;
    const closed = lane.polygon_lcs_m.concat([lane.polygon_lcs_m[0]]);
    for (const point of closed) {{
      xs.push(point[0]);
      ys.push(point[1]);
      labels.push(lane.lane_id);
    }}
    xs.push(null);
    ys.push(null);
    labels.push(null);
  }}
  if (!xs.length) return null;
  return {{
    type: 'scatter',
    mode: 'lines',
    name: 'BEV lane candidates',
    x: xs,
    y: ys,
    line: {{color: 'rgba(100,116,139,0.35)', width: 1}},
    hovertemplate: 'candidate=%{{customdata}}<extra></extra>',
    customdata: labels
  }};
}}

function addBevLanePocTraces(traces) {{
  const status = document.getElementById('bevLanePocStatus');
  const enabled = document.getElementById('showBevLanePoc')?.checked;
  const frame = BEV_LANE_POC_FRAMES[Number(currentIndex)];
  if (!enabled || !frame) {{
    if (status) status.textContent = frame ? 'BEV lane overlay hidden.' : `No BEV lane POC result for frame ${{currentIndex}}.`;
    return;
  }}
  const candidateTrace = bevLanePocCandidateTrace(frame);
  if (candidateTrace) traces.push(candidateTrace);
  const left = bevLanePocPolygonTrace(frame.left_adjacent, 'BEV left adjacent', 'rgba(2,132,199,OPACITY)', 0.18, 2);
  const right = bevLanePocPolygonTrace(frame.right_adjacent, 'BEV right adjacent', 'rgba(217,119,6,OPACITY)', 0.18, 2);
  const ego = bevLanePocPolygonTrace(frame.ego_lane, 'BEV ego lane', 'rgba(22,163,74,OPACITY)', 0.38, 5);
  for (const trace of [left, right, ego]) {{
    if (trace) traces.push(trace);
  }}
  if (status) {{
    const candidateCount = (frame.candidate_lanes || []).length;
    const duplicateCount = (frame.rejections?.duplicates || []).length;
    const extensionCount = (frame.lane_extension?.boundaries || []).filter(item => item.extended).length;
    status.textContent = `frame ${{frame.frame_index}} | ${{frame.status}} | source=${{frame.matching_source || 'unknown'}} | extended=${{extensionCount}} | candidates=${{candidateCount}} | duplicate rejects=${{duplicateCount}} | ego=${{frame.ego_lane?.lane_id || 'none'}}`;
  }}
}}
"""


def inject_overlay(page: str, result: dict[str, Any]) -> str:
    markers = {
        "</style>": STYLE + "\n</style>",
        '    <label for="classFilter">Object classes</label>': CONTROLS + '    <label for="classFilter">Object classes</label>',
        "const DATA =": overlay_script(result) + "\nconst DATA =",
        "  Plotly.react('map', traces, {": "  addBevLanePocTraces(traces);\n  Plotly.react('map', traces, {",
        "filter.addEventListener('change', render);":
            "filter.addEventListener('change', render);\n"
            "for (const id of ['showBevLanePoc','showBevLaneCandidates']) document.getElementById(id)?.addEventListener('change', render);",
    }
    for old, new in markers.items():
        count = page.count(old)
        if count != 1:
            raise ValueError(f"Unable to inject BEV lane POC overlay: expected one marker {old!r}, found {count}")
        page = page.replace(old, new)
    return page


def output_name(source: Path) -> str:
    suffix = "_animated_odld_explorer.html"
    if source.name.endswith(suffix):
        return source.name[: -len(suffix)] + "_animated_odld_explorer_w_bev_lane_poc.html"
    return source.stem + "_w_bev_lane_poc.html"


def result_path_for(source: Path, result_dir: Path) -> Path:
    recording = source.name.split("_animated_odld_explorer.html", 1)[0]
    return result_dir / f"{recording}_bev_lane_poc.json"


def convert_one(source: Path, result_path: Path, output: Path) -> None:
    result = json.loads(result_path.read_text(encoding="utf-8"))
    page = source.read_text(encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(inject_overlay(page, result), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-html", type=Path, help="One ODLD explorer HTML to duplicate")
    parser.add_argument("--bev-lane-result", type=Path, help="BEV lane POC JSON for --source-html")
    parser.add_argument("--output-html", type=Path, help="Output HTML for --source-html")
    parser.add_argument("--source-dir", type=Path, help="Directory of ODLD explorer HTML files")
    parser.add_argument("--result-dir", type=Path, default=Path("outputs/bev_lane_poc/results"))
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)

    if args.source_html:
        if not args.bev_lane_result:
            parser.error("--bev-lane-result is required with --source-html")
        output = args.output_html or args.source_html.with_name(output_name(args.source_html))
        convert_one(args.source_html, args.bev_lane_result, output)
        print(f"Wrote {output}")
        return 0

    if not args.source_dir or not args.output_dir:
        parser.error("provide either --source-html/--bev-lane-result or --source-dir/--output-dir")

    count = 0
    skipped = 0
    for source in sorted(args.source_dir.glob("*_animated_odld_explorer.html")):
        result_path = result_path_for(source, args.result_dir)
        if not result_path.is_file():
            skipped += 1
            continue
        convert_one(source, result_path, args.output_dir / output_name(source))
        count += 1
    print(f"Wrote {count} BEV lane POC explorer overlays; skipped {skipped} without results")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
