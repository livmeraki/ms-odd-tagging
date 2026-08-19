"""Shared index, embedded-payload, and path utilities for ODLD explorer tools.

The event-tag and frame-tag generators intentionally keep separate tag adapters.
Only byte-identical presentation and manifest behavior belongs here.
"""

from __future__ import annotations

import gc
import html
import json
import re
from pathlib import Path

import generate_dataset_explorers as base
from ms_odd_tagging.common.progress import ProgressReporter
from ms_odd_tagging.scenarios.following_lane.explorer_visualization import (
    render_original_explorer_with_lane_tracker,
)
from ms_odd_tagging.tagger.rule_based.registry import RULE_BASED_SCENARIOS


EXPLORER_DATA_MARKER = re.compile(r"const DATA = (\{.*?\});\s*const ", re.DOTALL)
MANIFEST_SCHEMA_VERSION = "odld-animated-explorer-manifest-v1"
INDEX_ROW_KEYS = (
    "recording",
    "file",
    "frames",
    "duration",
    "objects",
    "lines",
    "boundaries",
    "roadmarks",
    "tagScenarios",
    "tagEvents",
    "tagScenarioList",
    "topClasses",
    "thumbnail",
)


def index_cards_html(rows: list[dict]) -> str:
    return "\n".join(
        f"""<a class="card" href="{html.escape(row['file'])}" data-recording="{html.escape(row['recording'])}">
  <div class="route">{row['thumbnail']}</div>
  <h2>{html.escape(row['recording'])}</h2>
  <div class="metrics"><span>{row['frames']} frames</span><span>{row['duration']:.1f}s</span><span>{row['objects']} objects</span></div>
  <div class="metrics"><span>{row['lines']} lane lines</span><span>{row['boundaries']} boundaries</span><span>{row['roadmarks']} roadmarks</span></div>
  <div class="metrics"><span>{row['tagScenarios']} tagged scenarios</span><span>{row['tagEvents']} tag intervals</span></div>
  <p>{html.escape(row['topClasses'])}</p>
</a>"""
        for row in rows
    )


def index_html(rows: list[dict]) -> str:
    cards = index_cards_html(rows)
    scenario_options = sorted(
        {
            scenario
            for row in rows
            for scenario in row.get("tagScenarioList", [])
        }
        | set(RULE_BASED_SCENARIOS)
    )
    scenario_items = "".join(
        f'<label class="scenarioChoice"><input type="checkbox" value="{html.escape(scenario)}"><span>{html.escape(scenario)}</span></label>'
        for scenario in scenario_options
    )
    row_json = json.dumps(rows, ensure_ascii=True, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OD + LD + Ego Trajectory Explorers</title>
<style>
body{{margin:0;font-family:Arial,sans-serif;background:#eef2f6;color:#17202a}}header{{padding:20px 28px 18px;background:#17324d;color:white}}header h1{{margin:0 0 5px;font-size:22px;font-weight:700}}header p{{margin:0;opacity:.84;font-size:13px}}.toolbar{{position:sticky;top:0;z-index:5;background:#f8fafc;border-bottom:1px solid #cbd5e1;padding:14px 22px 12px;box-shadow:0 6px 18px rgba(15,23,42,.06)}}.controlRow{{display:grid;grid-template-columns:minmax(260px,2fr) minmax(110px,.7fr) minmax(130px,.8fr) minmax(150px,1fr) minmax(130px,.8fr) auto auto;gap:10px;align-items:end}}label{{display:grid;gap:5px;font-size:11px;font-weight:700;color:#475569;text-transform:uppercase}}input,select{{height:34px;border:1px solid #cbd5e1;border-radius:6px;background:white;color:#17202a;padding:0 9px;font-size:13px}}button{{height:34px;border:1px solid #94a3b8;border-radius:6px;background:#ffffff;color:#334155;padding:0 12px;font-size:13px;cursor:pointer}}button:hover{{border-color:#2563eb;color:#1d4ed8}}.count{{font-size:13px;color:#334155;white-space:nowrap;padding-bottom:9px}}.scenarioPanel{{margin-top:11px;border:1px solid #d7dee8;border-radius:8px;background:white}}.scenarioHeader{{display:flex;justify-content:space-between;gap:12px;padding:8px 10px;border-bottom:1px solid #e2e8f0;color:#475569;font-size:12px}}.scenarioHeader strong{{color:#334155}}.scenarioChoices{{max-height:82px;overflow:auto;padding:8px;display:flex;gap:6px;flex-wrap:wrap;align-content:flex-start}}.scenarioChoice{{display:flex;align-items:center;gap:5px;border:1px solid #cbd5e1;border-radius:999px;padding:4px 8px;font-size:12px;font-weight:400;color:#17202a;text-transform:none;white-space:nowrap;background:#f8fafc}}.scenarioChoice:has(input:checked){{background:#dbeafe;border-color:#60a5fa;color:#1e3a8a}}.scenarioChoice input{{width:13px;height:13px;padding:0;margin:0}}main{{padding:18px 22px 24px;display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px}}.card{{display:block;background:white;border:1px solid #d7dee8;border-radius:8px;padding:12px;text-decoration:none;color:inherit;box-shadow:0 1px 4px rgba(15,23,42,.05)}}.card:hover{{border-color:#2563eb;box-shadow:0 5px 16px rgba(37,99,235,.12)}}h2{{font-size:15px;margin:9px 0 8px;overflow-wrap:anywhere;line-height:1.25}}.route{{height:96px;background:#f8fafc;border-radius:6px;overflow:hidden;border:1px solid #eef2f7}}.route svg{{width:100%;height:100%}}.metrics{{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}}.metrics span{{background:#edf2f7;border-radius:999px;padding:3px 7px;font-size:11px;color:#334155}}p{{font-size:12px;color:#64748b;line-height:1.4;margin:8px 0 0}}.empty{{padding:28px;color:#64748b}}@media (max-width:1060px){{.controlRow{{grid-template-columns:1fr 1fr 1fr}}.count{{padding-bottom:0}}}}@media (max-width:680px){{header{{padding:16px}}.toolbar{{padding:12px}}.controlRow{{grid-template-columns:1fr}}main{{grid-template-columns:1fr;padding:12px}}}}
</style></head><body><header><h1>OD + LD + Ego Trajectory Explorers</h1><p>Synchronized scene viewers with OD tracks, complete LD map layers, scenario-tag intervals, frame-local context, playback, timelines, and notes.</p></header>
<section class="toolbar">
  <div class="controlRow">
    <label>Search<input id="recordingSearch" type="search" autocomplete="off"></label>
    <label>Min objects<input id="minObjectsFilter" type="number" min="0" step="1"></label>
    <label>Min tag events<input id="minTagEventsFilter" type="number" min="0" step="1"></label>
    <label>Sort<select id="sortField"><option value="recording">Recording</option><option value="frames">Frames</option><option value="duration">Duration</option><option value="objects">Objects</option><option value="tagEvents">Tag intervals</option><option value="tagScenarios">Tagged scenarios</option></select></label>
    <label>Order<select id="sortDirection"><option value="asc">Ascending</option><option value="desc">Descending</option></select></label>
    <button id="clearFilters" type="button">Clear</button>
    <div id="resultCount" class="count"></div>
  </div>
  <div class="scenarioPanel">
    <div class="scenarioHeader"><strong>Scenario tags</strong><span>matches all selected</span></div>
    <div id="scenarioFilter" class="scenarioChoices">{scenario_items}</div>
  </div>
</section>
<main id="recordingGrid">{cards}</main>
<script>
const INDEX_ROWS = {row_json};
const grid = document.getElementById('recordingGrid');
const count = document.getElementById('resultCount');
const controls = ['recordingSearch','scenarioFilter','minObjectsFilter','minTagEventsFilter','sortField','sortDirection'].map(id => document.getElementById(id));
function escapeHtml(value) {{
  return String(value ?? '').replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
}}
function numericValue(id) {{
  const value = Number(document.getElementById(id).value);
  return Number.isFinite(value) ? value : 0;
}}
function cardHtml(row) {{
  return `<a class="card" href="${{escapeHtml(row.file)}}" data-recording="${{escapeHtml(row.recording)}}">
  <div class="route">${{row.thumbnail || ''}}</div>
  <h2>${{escapeHtml(row.recording)}}</h2>
  <div class="metrics"><span>${{row.frames}} frames</span><span>${{Number(row.duration).toFixed(1)}}s</span><span>${{row.objects}} objects</span></div>
  <div class="metrics"><span>${{row.lines}} lane lines</span><span>${{row.boundaries}} boundaries</span><span>${{row.roadmarks}} roadmarks</span></div>
  <div class="metrics"><span>${{row.tagScenarios}} tagged scenarios</span><span>${{row.tagEvents}} tag intervals</span></div>
  <p>${{escapeHtml(row.topClasses)}}</p>
</a>`;
}}
function applyIndexFilters() {{
  const query = document.getElementById('recordingSearch').value.trim().toLowerCase();
  const selectedScenarios = [...document.querySelectorAll('#scenarioFilter input:checked')].map(input => input.value);
  const minObjects = numericValue('minObjectsFilter');
  const minTagEvents = numericValue('minTagEventsFilter');
  const sortField = document.getElementById('sortField').value;
  const direction = document.getElementById('sortDirection').value === 'desc' ? -1 : 1;
  const filtered = INDEX_ROWS.filter(row => {{
    if (query && !String(row.recording).toLowerCase().includes(query)) return false;
    if (selectedScenarios.length && !selectedScenarios.every(scenario => (row.tagScenarioList || []).includes(scenario))) return false;
    if (Number(row.objects) < minObjects) return false;
    if (Number(row.tagEvents) < minTagEvents) return false;
    return true;
  }}).sort((a, b) => {{
    const av = a[sortField];
    const bv = b[sortField];
    if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * direction;
    return String(av).localeCompare(String(bv), undefined, {{numeric: true}}) * direction;
  }});
  grid.innerHTML = filtered.length ? filtered.map(cardHtml).join('') : '<div class="empty">No matching recordings</div>';
  count.textContent = `${{filtered.length}} / ${{INDEX_ROWS.length}} recordings`;
}}
for (const control of controls) control.addEventListener('input', applyIndexFilters);
for (const control of controls) control.addEventListener('change', applyIndexFilters);
document.getElementById('clearFilters').addEventListener('click', () => {{
  document.getElementById('recordingSearch').value = '';
  document.getElementById('minObjectsFilter').value = '';
  document.getElementById('minTagEventsFilter').value = '';
  document.getElementById('sortField').value = 'recording';
  document.getElementById('sortDirection').value = 'asc';
  for (const input of document.querySelectorAll('#scenarioFilter input')) input.checked = false;
  applyIndexFilters();
}});
applyIndexFilters();
</script></body></html>"""


def inject_lane_tracker(output_path: Path, following_lane_result: dict) -> None:
    render_original_explorer_with_lane_tracker(
        output_path, following_lane_result, output_path
    )
    # The generated explorer and the generated OD+LD index live in the same
    # output directory in the current handover flow. Older templates pointed
    # one directory up to a legacy index filename, which breaks the button.
    page = output_path.read_text(encoding="utf-8")
    page = page.replace(
        '../dataset_odld_explorer_w_scenario_tag_index.html',
        'index.html',
    )
    page = page.replace(
        '../dataset_trajectory_object_explorer_index.html',
        'index.html',
    )
    output_path.write_text(page, encoding="utf-8")


def row_from_explorer(output_path: Path) -> dict:
    match = EXPLORER_DATA_MARKER.search(output_path.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"Unable to read explorer payload: {output_path}")
    data = json.loads(match.group(1))
    try:
        return {
            "recording": data["summary"]["recording"],
            "file": output_path.name,
            "frames": data["summary"]["frames"],
            "duration": data["summary"]["durationSec"],
            "objects": data["summary"]["objects"],
            "lines": data["ld"]["summary"]["laneLines"],
            "boundaries": data["ld"]["summary"]["roadBoundaries"],
            "roadmarks": data["ld"]["summary"]["roadmarks"],
            "tagScenarios": len(data["tags"]["scenarios"]),
            "tagEvents": len(data["tags"]["events"]),
            "tagScenarioList": data["tags"]["scenarios"],
            "topClasses": ", ".join(
                f"{key}:{value}"
                for key, value in list(data["summary"]["classCounts"].items())[:6]
            ),
            "thumbnail": base.thumbnail_svg(data),
        }
    finally:
        del data


def explorer_output_name(recording: str) -> str:
    return f"{recording}_animated_odld_explorer.html"


def format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remaining_seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m {remaining_seconds:.1f}s"
    hours, remaining_minutes = divmod(minutes, 60)
    return f"{int(hours)}h {int(remaining_minutes)}m {remaining_seconds:.1f}s"


def recording_from_canonical_path(canonical_path: Path) -> str:
    return canonical_path.name.removesuffix("_canonical_odld_frames.json")


def select_canonical_paths(
    canonical_dir: Path,
    recordings: list[str] | tuple[str, ...] = (),
) -> list[Path]:
    paths = sorted(canonical_dir.glob("*_canonical_odld_frames.json"))
    if not recordings:
        return paths
    requested = set(recordings)
    return [
        path
        for path in paths
        if recording_from_canonical_path(path) in requested
    ]


def row_has_valid_manifest_metadata(row: object) -> bool:
    return isinstance(row, dict) and all(key in row for key in INDEX_ROW_KEYS)


def read_manifest_rows(output_dir: Path) -> dict[str, dict]:
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.is_file():
        return {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        return {}
    rows = {}
    for row in manifest.get("recordings", []):
        if not row_has_valid_manifest_metadata(row):
            continue
        recording = row["recording"]
        output_path = output_dir / row["file"]
        if output_path.is_file():
            rows[recording] = row
    return rows


def existing_rows_by_recording(
    output_dir: Path,
    row_parser=row_from_explorer,
) -> dict[str, dict]:
    rows = {}
    output_paths = sorted(output_dir.glob("*_animated_odld_explorer.html"))
    progress = ProgressReporter("explorer-index", len(output_paths), "recording")
    progress.start()
    for output_path in output_paths:
        row = row_parser(output_path)
        rows[row["recording"]] = row
        progress.advance(row["recording"])
        gc.collect()
    return rows


def rebuild_rows_from_outputs(
    output_dir: Path,
    rows_by_recording: dict[str, dict],
    row_parser=row_from_explorer,
) -> list[dict]:
    rows = dict(rows_by_recording)
    output_paths = sorted(output_dir.glob("*_animated_odld_explorer.html"))
    progress = ProgressReporter("explorer-index", len(output_paths), "recording")
    progress.start()
    for output_path in output_paths:
        recording = output_path.name.removesuffix("_animated_odld_explorer.html")
        if row_has_valid_manifest_metadata(rows.get(recording)):
            progress.advance(f"{recording}: manifest")
            continue
        row = row_parser(output_path)
        rows[row["recording"]] = row
        progress.advance(f"{row['recording']}: parsed")
        gc.collect()
    return sorted(rows.values(), key=lambda row: row["recording"])


def row_from_generated_data(recording: str, output_name: str, data: dict) -> dict:
    return {
        "recording": recording,
        "file": output_name,
        "frames": data["summary"]["frames"],
        "duration": data["summary"]["durationSec"],
        "objects": data["summary"]["objects"],
        "lines": data["ld"]["summary"]["laneLines"],
        "boundaries": data["ld"]["summary"]["roadBoundaries"],
        "roadmarks": data["ld"]["summary"]["roadmarks"],
        "tagScenarios": len(data["tags"]["scenarios"]),
        "tagEvents": len(data["tags"]["events"]),
        "tagScenarioList": data["tags"]["scenarios"],
        "topClasses": ", ".join(
            f"{key}:{value}"
            for key, value in list(data["summary"]["classCounts"].items())[:6]
        ),
        "thumbnail": base.thumbnail_svg(data),
    }