#!/usr/bin/env python3
"""Duplicate ODLD explorers and overlay Lanelet2 POC lane results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ms_odd_tagging.lanelet2_poc.geometry import (
    filter_local_boundaries,
    merge_boundary_fragments,
)
from ms_odd_tagging.lanelet2_poc.runner import boundaries_from_recording


STYLE = """
  .lanelet2PocPanel { border-top:1px solid #d7deea; margin-top:14px; padding-top:12px; }
  .lanelet2PocPanel h3 { margin:0 0 8px; font-size:14px; }
  .lanelet2PocPanel label { display:flex; align-items:center; gap:8px; margin:8px 0; }
  .lanelet2PocLegend { display:grid; gap:5px; font-size:12px; color:#475569; }
  .lanelet2PocLegend span { display:inline-flex; align-items:center; gap:6px; }
  .lanelet2PocSwatch { width:18px; height:8px; border-radius:999px; display:inline-block; }
  .lanelet2PocStatus { font-size:12px; color:#64748b; margin-top:8px; line-height:1.35; }
"""


CONTROLS = """
    <div class="lanelet2PocPanel">
      <h3>Lanelet2 POC Overlay</h3>
      <label><input id="showLanelet2LcsLocal" type="checkbox" checked /> Show local/merged LCS boundaries</label>
      <label><input id="showLanelet2Poc" type="checkbox" checked /> Show Lanelet2 lanes</label>
      <label><input id="showLanelet2Candidates" type="checkbox" /> Show candidate lanes</label>
      <div class="lanelet2PocLegend">
        <span><i class="lanelet2PocSwatch" style="background:#7c3aed"></i>Local merged boundary used by POC</span>
        <span><i class="lanelet2PocSwatch" style="background:#16a34a"></i>Ego lane</span>
        <span><i class="lanelet2PocSwatch" style="background:#38bdf8"></i>Left adjacent</span>
        <span><i class="lanelet2PocSwatch" style="background:#f59e0b"></i>Right adjacent</span>
      </div>
      <div id="lanelet2PocStatus" class="lanelet2PocStatus"></div>
    </div>
"""


def _json_for_script(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/")


def _boundary_as_payload(boundary: Any) -> dict[str, Any]:
    return {
        "boundary_id": boundary.boundary_id,
        "source_kind": boundary.source_kind,
        "points_lcs_m": [list(point) for point in boundary.points],
        "attributes": boundary.attributes,
    }


def lcs_overlay_payload(
    recording: dict[str, Any] | None,
    result: dict[str, Any],
) -> dict[str, Any]:
    if recording is None:
        return {"frames": {}}
    config = result.get("config") or {}
    boundaries = boundaries_from_recording(recording, config)
    by_frame = {}
    for frame in result.get("frames", []):
        ego_source = frame.get("ego_pose_lcs") or {}
        ego = (
            float(ego_source.get("x", 0.0)),
            float(ego_source.get("y", 0.0)),
            float(ego_source.get("yaw", 0.0)),
        )
        merged = merge_boundary_fragments(boundaries, ego, config)
        local, _ = filter_local_boundaries(merged, ego, config)
        by_frame[str(frame.get("frame_index"))] = [
            _boundary_as_payload(boundary) for boundary in local
        ]
    return {"frames": by_frame}


def overlay_script(result: dict[str, Any], lcs_payload: dict[str, Any] | None = None) -> str:
    payload = _json_for_script(result)
    lcs_json = _json_for_script(lcs_payload or {"frames": {}})
    return f"""
const LANELET2_POC = {payload};
const LANELET2_LCS = {lcs_json};
const LANELET2_POC_FRAMES = Object.fromEntries((LANELET2_POC.frames || []).map(frame => [Number(frame.frame_index), frame]));

function lanelet2PocBoundaryLineTrace(boundaries, name, color, width, opacity) {{
  const xs = [], ys = [], labels = [];
  for (const boundary of boundaries || []) {{
    const points = boundary.points_lcs_m || [];
    if (points.length < 2) continue;
    for (const point of points) {{
      xs.push(point[0]);
      ys.push(point[1]);
      labels.push([boundary.boundary_id, boundary.source_kind, boundary.attributes?.pattern || boundary.attributes?.boundary_attribute || '']);
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
    hovertemplate: `${{name}}<br>id=%{{customdata[0]}}<br>kind=%{{customdata[1]}}<br>attr=%{{customdata[2]}}<extra></extra>`,
    customdata: labels
  }};
}}

function lanelet2PocPolygonTrace(lane, name, color, opacity, width) {{
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

function lanelet2PocCandidateTrace(frame) {{
  if (!document.getElementById('showLanelet2Candidates')?.checked) return null;
  const xs = [], ys = [], labels = [];
  const selected = new Set([
    frame.ego_lane?.lane_id,
    frame.left_adjacent?.lane_id,
    frame.right_adjacent?.lane_id
  ]);
  for (const lane of frame.candidate_lanelets || []) {{
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
    name: 'Lanelet2 candidates',
    x: xs,
    y: ys,
    line: {{color: 'rgba(100,116,139,0.35)', width: 1}},
    hovertemplate: 'candidate=%{{customdata}}<extra></extra>',
    customdata: labels
  }};
}}

function addLanelet2PocTraces(traces) {{
  const status = document.getElementById('lanelet2PocStatus');
  const enabled = document.getElementById('showLanelet2Poc')?.checked;
  const frame = LANELET2_POC_FRAMES[Number(currentIndex)];
  if (document.getElementById('showLanelet2LcsLocal')?.checked) {{
    const localTrace = lanelet2PocBoundaryLineTrace(LANELET2_LCS.frames?.[String(currentIndex)], 'Local LCS boundaries used by Lanelet2 POC', 'rgba(124,58,237,0.85)', 3, 0.95);
    if (localTrace) traces.push(localTrace);
  }}
  if (!enabled || !frame) {{
    if (status) status.textContent = frame ? 'Lanelet2 overlay hidden.' : `No Lanelet2 POC result for frame ${{currentIndex}}.`;
    return;
  }}
  const candidateTrace = lanelet2PocCandidateTrace(frame);
  if (candidateTrace) traces.push(candidateTrace);
  const left = lanelet2PocPolygonTrace(frame.left_adjacent, 'Lanelet2 left adjacent', 'rgba(56,189,248,OPACITY)', 0.18, 2);
  const right = lanelet2PocPolygonTrace(frame.right_adjacent, 'Lanelet2 right adjacent', 'rgba(245,158,11,OPACITY)', 0.18, 2);
  const ego = lanelet2PocPolygonTrace(frame.ego_lane, 'Lanelet2 ego lane', 'rgba(22,163,74,OPACITY)', 0.38, 5);
  for (const trace of [left, right, ego]) {{
    if (trace) traces.push(trace);
  }}
  if (status) {{
    const queries = frame.routing?.queries || {{}};
    const localCount = LANELET2_LCS.frames?.[String(currentIndex)]?.length || 0;
    status.textContent = `frame ${{frame.frame_index}} | ${{frame.status}} | backend=${{frame.routing?.backend || 'unknown'}} | local LCS=${{localCount}} | left=${{queries.left || queries.adjacentLeft || 'none'}} | right=${{queries.right || queries.adjacentRight || 'none'}}`;
  }}
}}
"""


def inject_overlay(
    page: str,
    result: dict[str, Any],
    lcs_payload: dict[str, Any] | None = None,
) -> str:
    markers = {
        "</style>": STYLE + "\n</style>",
        '    <label for="classFilter">Object classes</label>': CONTROLS + '    <label for="classFilter">Object classes</label>',
        "const DATA =": overlay_script(result, lcs_payload) + "\nconst DATA =",
        "  Plotly.react('map', traces, {": "  addLanelet2PocTraces(traces);\n  Plotly.react('map', traces, {",
        "filter.addEventListener('change', render);":
            "filter.addEventListener('change', render);\n"
            "for (const id of ['showLanelet2LcsLocal','showLanelet2Poc','showLanelet2Candidates']) document.getElementById(id)?.addEventListener('change', render);",
    }
    for old, new in markers.items():
        count = page.count(old)
        if count != 1:
            raise ValueError(f"Unable to inject Lanelet2 POC overlay: expected one marker {old!r}, found {count}")
        page = page.replace(old, new)
    return page


def output_name(source: Path) -> str:
    suffix = "_animated_odld_explorer.html"
    if source.name.endswith(suffix):
        return source.name[: -len(suffix)] + "_animated_odld_explorer_w_lanelet2_poc.html"
    return source.stem + "_w_lanelet2_poc.html"


def result_path_for(source: Path, result_dir: Path) -> Path:
    recording = source.name.split("_animated_odld_explorer.html", 1)[0]
    return result_dir / f"{recording}_lanelet2_poc.json"


def convert_one(
    source: Path,
    result_path: Path,
    output: Path,
    canonical_json: Path | None = None,
) -> None:
    result = json.loads(result_path.read_text(encoding="utf-8"))
    recording = (
        json.loads(canonical_json.read_text(encoding="utf-8"))
        if canonical_json is not None and canonical_json.is_file()
        else None
    )
    lcs_payload = lcs_overlay_payload(recording, result)
    page = source.read_text(encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(inject_overlay(page, result, lcs_payload), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-html", type=Path, help="One ODLD explorer HTML to duplicate")
    parser.add_argument("--lanelet2-result", type=Path, help="Lanelet2 POC JSON for --source-html")
    parser.add_argument("--canonical-json", type=Path, help="Canonical ODLD JSON used to add raw/local LCS lane traces")
    parser.add_argument("--output-html", type=Path, help="Output HTML for --source-html")
    parser.add_argument("--source-dir", type=Path, help="Directory of ODLD explorer HTML files")
    parser.add_argument("--result-dir", type=Path, default=Path("outputs/lanelet2_poc/results"))
    parser.add_argument("--canonical-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)

    if args.source_html:
        if not args.lanelet2_result:
            parser.error("--lanelet2-result is required with --source-html")
        output = args.output_html or args.source_html.with_name(output_name(args.source_html))
        convert_one(args.source_html, args.lanelet2_result, output, args.canonical_json)
        print(f"Wrote {output}")
        return 0

    if not args.source_dir or not args.output_dir:
        parser.error("provide either --source-html/--lanelet2-result or --source-dir/--output-dir")

    count = 0
    skipped = 0
    for source in sorted(args.source_dir.glob("*_animated_odld_explorer.html")):
        result_path = result_path_for(source, args.result_dir)
        if not result_path.is_file():
            skipped += 1
            continue
        recording = source.name.split("_animated_odld_explorer.html", 1)[0]
        canonical_json = (
            args.canonical_dir / f"{recording}_canonical_odld_frames.json"
            if args.canonical_dir
            else None
        )
        convert_one(source, result_path, args.output_dir / output_name(source), canonical_json)
        count += 1
    print(f"Wrote {count} Lanelet2 POC explorer overlays; skipped {skipped} without results")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
