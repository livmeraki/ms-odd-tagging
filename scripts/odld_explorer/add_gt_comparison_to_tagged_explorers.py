#!/usr/bin/env python3
"""Duplicate tagged ODLD explorers and add synchronized GT comparison plots."""

from __future__ import annotations

import argparse
import csv
import html
import json
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

from ms_odd_tagging.common.config import DATA_GT, GT_COMPARISON, OUTPUT_ROOT

DEFAULT_SOURCE_DIR = OUTPUT_ROOT / "scenarios" / "following_lane_tagged" / "04_visualization"
DEFAULT_OUTPUT_DIR = OUTPUT_ROOT / "07_odld_scenario_explorers_gt_comparison"
DEFAULT_DETAILS = GT_COMPARISON / "rule_based_gt_details.csv"
DEFAULT_SUMMARY = GT_COMPARISON / "rule_based_gt_summary.json"
DEFAULT_GT_DIR = DATA_GT


GT_STYLE = """
  .gtComparisonHeader { display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin-bottom:8px; }
  .gtComparisonHeader h2 { margin:0 auto 0 0; font-size:17px; }
  .gtMetrics { display:flex; gap:7px; flex-wrap:wrap; }
  .gtMetric { padding:4px 8px; border-radius:999px; background:#eef2ff; color:#312e81; font-size:12px; font-weight:700; }
  .gtWarning { background:#fff7ed; color:#9a3412; }
  #gtComparisonTimeline { min-height:650px; }
  #gtComparisonReadout { margin-top:8px; padding:8px; border-radius:6px; background:#f8fafc; color:#334155; font-size:12px; line-height:1.45; }
"""


def comparison_panel(recording_summary: dict, quality: dict) -> str:
    status = quality.get("status", "unknown")
    exact = recording_summary.get("exact_match_accuracy")
    exact_text = "n/a" if exact is None else f"{100 * exact:.1f}%"
    warning_class = " gtWarning" if status != "valid" else ""
    return f"""
    <div class="panel" id="gtComparisonPanel">
      <div class="gtComparisonHeader">
        <h2>GT comparison</h2>
        <label>Scenario
          <select id="gtScenarioFilter"><option value="all" selected>all scored scenarios</option></select>
        </label>
        <label><input id="gtMismatchOnly" type="checkbox" /> Mismatches only</label>
        <div class="gtMetrics">
          <span class="gtMetric">exact frame match {exact_text}</span>
          <span class="gtMetric{warning_class}">GT {html.escape(status)}</span>
          <span class="gtMetric">frames 0-4 excluded</span>
        </div>
      </div>
      <div id="gtComparisonTimeline"></div>
      <div id="gtComparisonReadout">Click a GT or prediction marker to inspect that source frame.</div>
    </div>"""


GT_SCRIPT = r"""
function gtComparisonRows() {
  const selected = gtScenarioFilter.value;
  const mismatchOnly = document.getElementById('gtMismatchOnly').checked;
  return GT_COMPARE.rows.filter(row =>
    (selected === 'all' || row.label === selected) &&
    (!mismatchOnly || row.expected !== row.actual)
  );
}

function gtMarkerTrace(rows, source) {
  const isGt = source === 'gt';
  return {
    type: 'scattergl',
    mode: 'markers',
    name: isGt ? 'Ground truth' : 'Tagged prediction',
    x: rows.map(row => row.time),
    y: rows.map(row => `${isGt ? 'GT' : 'Tag'} · ${row.label.replaceAll('_', ' ')}`),
    marker: {
      size: 8,
      symbol: rows.map(row => {
        const value = isGt ? row.expected : row.actual;
        if (row.expected !== row.actual) return 'x';
        return value ? (isGt ? 'square' : 'circle') : (isGt ? 'square-open' : 'circle-open');
      }),
      color: rows.map(row => row.expected !== row.actual ? '#dc2626' : (isGt ? '#059669' : '#2563eb')),
      line: {width: 1}
    },
    customdata: rows.map(row => [row.frameIndex, row.label, row.expected, row.actual, row.outcome]),
    hovertemplate: `${isGt ? 'GT' : 'tag'}<br>%{customdata[1]}<br>frame %{customdata[0]} · t=%{x:.2f}s<br>GT=%{customdata[2]} · tag=%{customdata[3]}<br>%{customdata[4]}<extra></extra>`
  };
}

function renderGtComparison() {
  const rows = gtComparisonRows();
  const labels = [...new Set(rows.map(row => row.label))];
  const traces = rows.length ? [gtMarkerTrace(rows, 'gt'), gtMarkerTrace(rows, 'tag')] : [];
  const height = Math.max(300, 125 + labels.length * 68);
  const element = document.getElementById('gtComparisonTimeline');
  element.style.height = `${height}px`;
  Plotly.newPlot(element, traces, {
    margin: {...SHARED_TIMELINE_MARGIN, l: 225},
    xaxis: sharedTimelineXAxis(),
    yaxis: {title: '', automargin: false, categoryorder: 'array',
      categoryarray: labels.flatMap(label => [`Tag · ${label.replaceAll('_', ' ')}`, `GT · ${label.replaceAll('_', ' ')}`])},
    hovermode: 'closest',
    legend: {orientation: 'h', x: 0.5, xanchor: 'center', y: -0.16},
    shapes: [{type:'line', x0:traj.rel_t[currentIndex], x1:traj.rel_t[currentIndex],
      y0:0, y1:1, yref:'paper', line:{color:'#111827', width:2, dash:'dot'}}],
    annotations: rows.length ? [] : [{text:'No comparison rows match this filter', showarrow:false, x:0.5, y:0.5, xref:'paper', yref:'paper'}]
  }, {responsive:true});
  attachSharedTimeAxis('gtComparisonTimeline');
  if (!element._gtClickAttached) {
    element._gtClickAttached = true;
    element.on('plotly_click', eventData => {
      const point = eventData.points && eventData.points[0];
      if (!point || !point.customdata) return;
      setFrame(point.customdata[0]);
      const [frame, label, expected, actual, outcome] = point.customdata;
      document.getElementById('gtComparisonReadout').textContent =
        `frame ${frame} · ${label.replaceAll('_',' ')} · GT=${expected} · tag=${actual} · ${outcome}`;
    });
  }
}

function updateGtComparisonCursor() {
  const element = document.getElementById('gtComparisonTimeline');
  if (!element || !element.data) return;
  Plotly.relayout(element, {shapes:[{type:'line', x0:traj.rel_t[currentIndex], x1:traj.rel_t[currentIndex],
    y0:0, y1:1, yref:'paper', line:{color:'#111827', width:2, dash:'dot'}}]});
}
"""


def load_rows(path: Path, gt_dir: Path) -> dict[str, list[dict]]:
    time_by_frame = {}
    for gt_path in gt_dir.glob("*_frame_gt.json"):
        payload = json.loads(gt_path.read_text(encoding="utf-8"))
        recording = payload["recording_id"]
        for frame in payload.get("frames", {}).values():
            time_by_frame[(recording, int(frame["frame_index"]))] = float(
                frame["time_since_start_s"]
            )
    grouped: dict[str, list[dict]] = defaultdict(list)
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            recording = row["recording_id"]
            frame_index = int(row["frame_index"])
            grouped[row["recording_id"]].append(
                {
                    "frameIndex": frame_index,
                    "time": round(time_by_frame[(recording, frame_index)], 4),
                    "label": row["label"],
                    "expected": row["expected"].lower() == "true",
                    "actual": row["actual"].lower() == "true",
                    "outcome": row["outcome"],
                }
            )
    return grouped


def inject(
    page: str,
    recording: str,
    rows: list[dict],
    recording_summary: dict,
    quality: dict,
    source_dir: Path,
) -> str:
    markers = {
        "</style>": GT_STYLE + "\n</style>",
        '    <div class="panel"><div id="tagTimeline"></div></div>':
            '    <div class="panel"><div id="tagTimeline"></div></div>\n'
            + comparison_panel(recording_summary, quality),
        "const DATA =": "const GT_COMPARE = "
            + json.dumps(
                {
                    "recordingId": recording,
                    "scoredLabels": recording_summary.get("label_metrics")
                    and [row["label"] for row in recording_summary["label_metrics"]]
                    or sorted({row["label"] for row in rows}),
                    "rows": rows,
                },
                ensure_ascii=True,
                separators=(",", ":"),
            )
            + ";\n"
            + GT_SCRIPT
            + "\nconst DATA =",
        "  updateTagTimelineCursor();\n}":
            "  updateTagTimelineCursor();\n  updateGtComparisonCursor();\n}",
        "renderTagTimeline();\n":
            "renderTagTimeline();\n"
            "const gtScenarioFilter = document.getElementById('gtScenarioFilter');\n"
            "for (const label of GT_COMPARE.scoredLabels) {\n"
            "  const option = document.createElement('option');\n"
            "  option.value = label;\n"
            "  option.textContent = label.replaceAll('_', ' ');\n"
            "  gtScenarioFilter.appendChild(option);\n"
            "}\n"
            "if (!SHARED_TIME_PLOT_IDS.includes('gtComparisonTimeline')) SHARED_TIME_PLOT_IDS.push('gtComparisonTimeline');\n"
            "if (document.getElementById('laneTrackerTimeline')) {\n"
            "  if (!SHARED_TIME_PLOT_IDS.includes('laneTrackerTimeline')) SHARED_TIME_PLOT_IDS.push('laneTrackerTimeline');\n"
            "  attachSharedTimeAxis('laneTrackerTimeline');\n"
            "}\n"
            "renderGtComparison();\n"
            "document.getElementById('gtScenarioFilter').addEventListener('change', renderGtComparison);\n"
            "document.getElementById('gtMismatchOnly').addEventListener('change', renderGtComparison);\n",
    }
    for old, new in markers.items():
        if page.count(old) != 1:
            raise ValueError(f"{recording}: expected one marker {old!r}, found {page.count(old)}")
        page = page.replace(old, new, 1)
    source_debug = (source_dir / "debug").resolve().as_uri()
    page = page.replace(
        "const DEBUG_BASE = `debug/${encodeURIComponent(DATA.summary.recording)}`;",
        f"const DEBUG_BASE = `{source_debug}/${{encodeURIComponent(DATA.summary.recording)}}`;",
        1,
    )
    return page.replace("<title>", "<title>GT comparison - ", 1)


def index_html(records: list[dict]) -> str:
    links = "\n".join(
        f'<li><a href="{quote(row["file"])}">{html.escape(row["recording"])}</a>'
        f'<span>{row["frames"]} compared frames · {100 * row["exact"]:.1f}% exact frame match</span></li>'
        for row in records
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tagged scenario GT comparison explorers</title>
<style>body{{font:15px system-ui,sans-serif;max-width:1000px;margin:auto;padding:24px;background:#f8fafc;color:#172033}}
h1{{font-size:23px}}ul{{list-style:none;padding:0}}li{{display:flex;justify-content:space-between;gap:20px;padding:13px 4px;border-bottom:1px solid #d8deea}}
a{{font-weight:650;color:#2458c6}}span{{color:#657087}}</style></head>
<body><h1>Tagged scenario GT comparison explorers</h1><ul>{links}</ul></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--details", type=Path, default=DEFAULT_DETAILS)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--gt-dir", type=Path, default=DEFAULT_GT_DIR)
    parser.add_argument(
        "--skip-index",
        action="store_true",
        help="Regenerate matching recording pages without replacing the existing index and manifest.",
    )
    parser.add_argument(
        "--merge-index",
        action="store_true",
        help="Update matching entries in an existing index and manifest while preserving other recordings.",
    )
    args = parser.parse_args()

    grouped = load_rows(args.details, args.gt_dir)
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    summaries = {row["recording_id"]: row for row in summary["recordings"]}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for recording, rows in sorted(grouped.items()):
        source = args.source_dir / f"{recording}_following_lane_explorer.html"
        if not source.is_file():
            raise FileNotFoundError(source)
        recording_summary = summaries[recording]
        output_name = f"{recording}_animated_odld_explorer_w_gt_comparison.html"
        output = args.output_dir / output_name
        output.write_text(
            inject(
                source.read_text(encoding="utf-8"),
                recording,
                rows,
                recording_summary,
                summary["gt_quality"],
                args.source_dir,
            ),
            encoding="utf-8",
        )
        records.append(
            {
                "recording": recording,
                "file": output_name,
                "frames": recording_summary["reviewed_frames_scored"],
                "exact": recording_summary["exact_match_accuracy"],
            }
        )
        print(f"Wrote {output}")
    if args.skip_index and args.merge_index:
        parser.error("--skip-index and --merge-index are mutually exclusive")
    if args.merge_index:
        manifest_path = args.output_dir / "manifest.json"
        existing = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.is_file()
            else {"recordings": []}
        )
        merged = {
            row["recording"]: row for row in existing.get("recordings", [])
        }
        merged.update({row["recording"]: row for row in records})
        merged_records = [merged[key] for key in sorted(merged)]
        manifest = {
            **existing,
            "schema_version": "tagged-scenario-gt-comparison-explorers-v1",
            "source_dir": str(args.source_dir),
            "minimum_frame_index": summary["minimum_scored_frame_index"],
            "recordings": merged_records,
        }
        (args.output_dir / "index.html").write_text(
            index_html(merged_records), encoding="utf-8"
        )
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Updated {args.output_dir / 'index.html'}")
    elif not args.skip_index:
        (args.output_dir / "index.html").write_text(index_html(records), encoding="utf-8")
        (args.output_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "tagged-scenario-gt-comparison-explorers-v1",
                    "source_dir": str(args.source_dir),
                    "minimum_frame_index": summary["minimum_scored_frame_index"],
                    "recordings": records,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {args.output_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
