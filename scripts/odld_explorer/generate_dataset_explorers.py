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
                fb.get("qx", 0.0),
                fb.get("qy", 0.0),
                fb.get("qz", 0.0),
                fb.get("qw", 1.0),
            ), 5),
            compact_float(fb.get("length")),
            compact_float(fb.get("width")),
            compact_float(fb.get("height")),
        ))
    frame_items.sort(key=lambda item: item[0])
    base_yaw = compact_float(quat_yaw(
        bbox.get("qx", 0.0),
        bbox.get("qy", 0.0),
        bbox.get("qz", 0.0),
        bbox.get("qw", 1.0),
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


def build_scene_data(scene_dir):
    ann_path = scene_dir / "annotations.json"
    traj_path = scene_dir / "traj_lcs.txt"
    with ann_path.open(encoding="utf-8") as f:
        ann = json.load(f)
    traj = load_traj(traj_path)
    objects = [object_payload(o) for o in ann.get("objects", [])]
    class_counts = Counter(o["className"] for o in objects)
    moving_tracks = sum(1 for o in objects if "frames" in o)
    summary = {
        "recording": ann.get("scene", {}).get("name", scene_dir.name),
        "scene": ann.get("scene", {}),
        "frames": len(traj["rel_t"]),
        "durationSec": traj["rel_t"][-1] if traj["rel_t"] else 0,
        "objects": len(objects),
        "movingTracks": moving_tracks,
        "classCounts": dict(class_counts.most_common()),
        "speedMinMeanMax": [
            float(np.min(traj["speed"])),
            float(np.mean(traj["speed"])),
            float(np.max(traj["speed"])),
        ],
    }
    return {"summary": summary, "trajectory": traj, "objects": objects}


def html_escape_json(data):
    return json.dumps(data, separators=(",", ":")).replace("</", "<\\/")


def scene_html(data):
    payload = html_escape_json(data)
    title = data["summary"]["recording"]
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title} Animated Trajectory/Object Explorer</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  body {{ margin: 0; font-family: Arial, sans-serif; color: #17202a; background: #f6f8fb; }}
  header {{ padding: 14px 18px; background: #17324d; color: white; }}
  .headerRow {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }}
  .backLink {{ flex: 0 0 auto; color: white; border: 1px solid rgba(255,255,255,.55); border-radius: 6px; padding: 7px 10px; font-size: 12px; font-weight: 700; text-decoration: none; background: rgba(255,255,255,.08); }}
  .backLink:hover {{ background: rgba(255,255,255,.16); }}
  header h1 {{ margin: 0 0 4px; font-size: 18px; }}
  header p {{ margin: 0; opacity: .9; font-size: 12px; }}
  .topPlayback {{ position: sticky; top: 0; z-index: 10; display: grid; grid-template-columns: auto minmax(240px, 1fr) auto minmax(90px, 120px); gap: 10px; align-items: center; padding: 10px 12px; background: #ffffff; border-bottom: 1px solid #d7dee8; box-shadow: 0 2px 8px rgba(15, 23, 42, .08); }}
  .topPlayback button, .topPlayback select, .topPlayback input {{ margin-top: 0; }}
  .topPlayback label {{ display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 8px; align-items: center; margin-top: 0; white-space: nowrap; }}
  .topPlayback .speedControl {{ grid-template-columns: auto minmax(72px, 1fr); }}
  .topPlayback #frameReadout {{ margin-top: 0; white-space: nowrap; }}
  main {{ display: grid; grid-template-columns: 320px 1fr; gap: 12px; padding: 12px; }}
  aside {{ background: white; border: 1px solid #d7dee8; border-radius: 8px; padding: 14px; height: calc(100vh - 96px); overflow: auto; }}
  .panel {{ background: white; border: 1px solid #d7dee8; border-radius: 8px; padding: 8px; margin-bottom: 12px; }}
  #map {{ height: 590px; }}
  #timeline {{ height: 520px; }}
  label {{ display: block; margin-top: 10px; font-size: 13px; font-weight: 700; }}
  select, input, button {{ width: 100%; margin-top: 4px; }}
  label input[type="checkbox"] {{ width: auto; margin-right: 6px; }}
  .stat {{ display: flex; justify-content: space-between; border-bottom: 1px solid #edf1f5; padding: 5px 0; font-size: 13px; }}
  .classes {{ font-size: 12px; line-height: 1.45; }}
  #animControls {{ margin: 0; }}
  #frameReadout {{ font-size: 12px; color: #334155; margin-top: 6px; }}
  .note {{ font-size: 12px; color: #475569; line-height: 1.4; margin-top: 10px; }}
  label.disabled {{ color: #94a3b8; }}
  .tagPanel {{ margin-top: 14px; padding-top: 12px; border-top: 1px solid #edf1f5; }}
  .tagPanel h3 {{ margin: 0 0 8px; font-size: 16px; }}
  .tagRow {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-top: 8px; }}
  textarea {{ width: 100%; min-height: 78px; margin-top: 4px; box-sizing: border-box; resize: vertical; font-family: Arial, sans-serif; }}
  .noteList {{ margin-top: 10px; display: grid; gap: 6px; }}
  .noteItem {{ border: 1px solid #d7dee8; border-radius: 6px; padding: 7px; background: #f8fafc; font-size: 12px; cursor: pointer; }}
  .noteItem strong {{ display: block; color: #0f172a; margin-bottom: 3px; }}
  .noteItem span {{ color: #475569; }}
  @media (max-width: 900px) {{ .topPlayback {{ grid-template-columns: auto 1fr; }} .topPlayback #frameReadout {{ grid-column: 1 / -1; }} main {{ grid-template-columns: 1fr; }} aside {{ height: auto; }} }}
</style>
</head>
<body>
<header>
  <div class="headerRow">
    <div>
      <h1>{title}</h1>
      <p>Animated ego trajectory with ALT object tracks. Uses per-frame bbox3d where available; static objects use object-level bbox3d.</p>
    </div>
    <a class="backLink" href="../dataset_trajectory_object_explorer_index.html">Back to list</a>
  </div>
</header>
<div id="animControls" class="topPlayback">
  <button id="playPause" type="button">Play</button>
  <label for="frameSlider">Frame
    <input id="frameSlider" type="range" min="0" value="0" step="1" />
  </label>
  <div id="frameReadout"></div>
  <label for="playbackSpeed" class="speedControl">Speed
    <select id="playbackSpeed">
      <option value="0.5">0.5x</option>
      <option value="1" selected>1x</option>
      <option value="2">2x</option>
      <option value="4">4x</option>
      <option value="8">8x</option>
      <option value="12">12x</option>
      <option value="16">16x</option>
      <option value="24">24x</option>
      <option value="32">32x</option>
    </select>
  </label>
</div>
<main>
  <aside>
    <div class="stat"><span>Frames</span><b id="statFrames"></b></div>
    <div class="stat"><span>Duration</span><b id="statDuration"></b></div>
    <div class="stat"><span>Objects</span><b id="statObjects"></b></div>
    <div class="stat"><span>Per-frame tracks</span><b id="statTracks"></b></div>
    <label for="classFilter">Object classes</label>
    <select id="classFilter" multiple size="12"></select>
    <label><input id="showFootprints" type="checkbox" checked /> Show bbox footprints</label>
    <label><input id="showObjects" type="checkbox" checked /> Show object centers</label>
    <label><input id="showEgoMarkers" type="checkbox" checked /> Show ego heading samples</label>
    <label><input id="activeOnly" type="checkbox" checked /> Show active objects only</label>
    <label id="persistStaticLabel"><input id="persistStatic" type="checkbox" checked /> Persist static / parked objects after first observation</label>
    <label><input id="followEgo" type="checkbox" checked /> Follow ego with current zoom</label>
    <div class="tagPanel">
      <h3>Situation Notes</h3>
      <label for="situationTag">Tag</label>
      <input id="situationTag" type="text" list="tagSuggestions" placeholder="cut-in, occlusion, stale track..." />
      <datalist id="tagSuggestions">
        <option value="cut-in"></option>
        <option value="near-collision"></option>
        <option value="stale-track"></option>
        <option value="missed-detection"></option>
        <option value="false-positive"></option>
        <option value="occlusion"></option>
        <option value="static-object"></option>
        <option value="complex-intersection"></option>
      </datalist>
      <label for="situationNote">Note</label>
      <textarea id="situationNote" placeholder="Describe what happens at this frame"></textarea>
      <div class="tagRow">
        <button id="saveNote" type="button">Save frame note</button>
        <button id="deleteNote" type="button">Delete frame note</button>
      </div>
      <button id="exportNotes" type="button">Export notes JSON</button>
      <button id="syncNotesToList" type="button">Sync notes to list</button>
      <div id="noteStatus" class="note"></div>
      <div id="noteList" class="noteList"></div>
    </div>
    <h3>Class Counts</h3>
    <div id="classCounts" class="classes"></div>
    <div class="note">CDN version requires network access to Plotly. If plots are blank, check that cdn.plot.ly is reachable.</div>
  </aside>
  <section>
    <div class="panel"><div id="map"></div></div>
    <div class="panel"><div id="timeline"></div></div>
  </section>
</main>
<script>
const DATA = {payload};
const palette = {json.dumps(PALETTE)};
const traj = DATA.trajectory;
const objects = DATA.objects;
const classes = Object.keys(DATA.summary.classCounts);
const colorOf = Object.fromEntries(classes.map((c, i) => [c, palette[i % palette.length]]));
const filter = document.getElementById('classFilter');
document.getElementById('statFrames').textContent = DATA.summary.frames;
document.getElementById('statDuration').textContent = DATA.summary.durationSec.toFixed(1) + 's';
document.getElementById('statObjects').textContent = DATA.summary.objects;
document.getElementById('statTracks').textContent = DATA.summary.movingTracks;
classes.forEach(c => {{
  const opt = document.createElement('option');
  opt.value = c;
  opt.textContent = c;
  opt.selected = true;
  filter.appendChild(opt);
}});
document.getElementById('classCounts').innerHTML = classes.map(c => `<div><b style="color:${{colorOf[c]}}">${{c}}</b>: ${{DATA.summary.classCounts[c]}}</div>`).join('');

const frameSlider = document.getElementById('frameSlider');
const frameReadout = document.getElementById('frameReadout');
const playPause = document.getElementById('playPause');
const playbackSpeed = document.getElementById('playbackSpeed');
const activeOnly = document.getElementById('activeOnly');
const persistStatic = document.getElementById('persistStatic');
const followEgo = document.getElementById('followEgo');
const situationTag = document.getElementById('situationTag');
const situationNote = document.getElementById('situationNote');
const noteStatus = document.getElementById('noteStatus');
const noteList = document.getElementById('noteList');
frameSlider.max = traj.rel_t.length - 1;
let currentIndex = 0;
let playbackTimer = null;
let playbackLastTickMs = null;
let playbackRemainderFrames = 0;
let mapReady = false;
let userMapRange = null;
let ignoreMapRelayout = false;
let mapRelayoutAttached = false;
const noteStorageKey = `mv2-situation-notes:${{DATA.summary.recording}}`;
let notes = loadNotes();
const speedMin = Math.min(...traj.speed);
const speedMax = Math.max(...traj.speed);

function loadNotes() {{
  try {{
    const raw = localStorage.getItem(noteStorageKey);
    return raw ? JSON.parse(raw) : {{}};
  }} catch (err) {{
    console.warn('Unable to load notes', err);
    return {{}};
  }}
}}

function persistNotes() {{
  localStorage.setItem(noteStorageKey, JSON.stringify(notes));
}}

function noteForFrame(frameIndex) {{
  return notes[String(frameIndex)] || null;
}}

function syncNoteEditor() {{
  const note = noteForFrame(currentIndex);
  situationTag.value = note ? note.tag : '';
  situationNote.value = note ? note.text : '';
  noteStatus.textContent = note ? `Saved note at frame ${{currentIndex}}.` : `No saved note at frame ${{currentIndex}}.`;
}}

function renderNoteList() {{
  const entries = Object.entries(notes).sort((a, b) => Number(a[0]) - Number(b[0]));
  if (!entries.length) {{
    noteList.innerHTML = '<div class="note">No situation notes yet.</div>';
    return;
  }}
  noteList.innerHTML = entries.map(([frame, note]) => {{
    const tag = note.tag || 'untagged';
    const text = note.text || '';
    return `<div class="noteItem" data-frame="${{frame}}"><strong>frame ${{frame}} | ${{Number(note.timeSec).toFixed(1)}}s | ${{tag}}</strong><span>${{escapeHtml(text).slice(0, 110)}}</span></div>`;
  }}).join('');
}}

function escapeHtml(value) {{
  return String(value).replace(/[&<>"']/g, ch => ({{'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}}[ch]));
}}

function saveCurrentNote() {{
  const tag = situationTag.value.trim();
  const text = situationNote.value.trim();
  if (!tag && !text) {{
    delete notes[String(currentIndex)];
  }} else {{
    notes[String(currentIndex)] = {{
      recording: DATA.summary.recording,
      frame: currentIndex,
      timeSec: traj.rel_t[currentIndex],
      ego: {{x: traj.x[currentIndex], y: traj.y[currentIndex], speed: traj.speed[currentIndex], yawDeg: traj.yaw_deg[currentIndex]}},
      tag,
      text,
      updatedAt: new Date().toISOString()
    }};
  }}
  persistNotes();
  renderNoteList();
  syncNoteEditor();
  updateTimelineCursor();
}}

function deleteCurrentNote() {{
  delete notes[String(currentIndex)];
  persistNotes();
  renderNoteList();
  syncNoteEditor();
  updateTimelineCursor();
}}

function exportNotesJson() {{
  const payload = {{
    recording: DATA.summary.recording,
    exportedAt: new Date().toISOString(),
    notes: Object.values(notes).sort((a, b) => a.frame - b.frame)
  }};
  const blob = new Blob([JSON.stringify(payload, null, 2)], {{type: 'application/json'}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${{DATA.summary.recording}}_situation_notes.json`;
  a.click();
  URL.revokeObjectURL(url);
}}

function encodeNotePayload(payload) {{
  const json = JSON.stringify(payload);
  return btoa(unescape(encodeURIComponent(json)));
}}

function syncNotesToList() {{
  const payload = {{
    recording: DATA.summary.recording,
    syncedAt: new Date().toISOString(),
    notes: Object.values(notes).sort((a, b) => a.frame - b.frame)
  }};
  const encoded = encodeNotePayload(payload);
  location.href = `../dataset_trajectory_object_explorer_index.html#importNotes=${{encoded}}`;
}}

function selectedClasses() {{
  return Array.from(filter.selectedOptions).map(o => o.value);
}}

function lowerBound(arr, target) {{
  let lo = 0, hi = arr.length;
  while (lo < hi) {{
    const mid = (lo + hi) >> 1;
    if (arr[mid] < target) lo = mid + 1; else hi = mid;
  }}
  return lo;
}}

function isActiveObject(o) {{
  if (!activeOnly.checked) return true;
  const visibleMin = o.visibleMin ?? 0;
  const visibleMax = o.visibleMax ?? traj.rel_t.length - 1;
  const visibleNow = visibleMin <= currentIndex && currentIndex <= visibleMax;
  if (visibleNow) return true;
  if (persistStatic.checked && (o.type === 'static' || o.isParked) && currentIndex >= visibleMin) return true;
  return false;
}}

function syncControlState() {{
  persistStatic.disabled = !activeOnly.checked;
  document.getElementById('persistStaticLabel').classList.toggle('disabled', persistStatic.disabled);
}}

function objectState(o, frameIndex) {{
  if (o.frames && o.frames.length) {{
    const pos = lowerBound(o.frames, frameIndex);
    let idx = pos;
    if (idx >= o.frames.length) idx = o.frames.length - 1;
    if (o.frames[idx] !== frameIndex && pos > 0) idx = pos - 1;
    return {{
      x: o.xs[idx],
      y: o.ys[idx],
      yaw: o.yaws[idx] ?? o.yaw,
      length: o.lengths ? o.lengths[idx] : o.length,
      width: o.widths ? o.widths[idx] : o.width,
      height: o.heights ? o.heights[idx] : o.height,
      source: 'per-frame bbox3d'
    }};
  }}
  return {{x: o.x, y: o.y, yaw: o.yaw, length: o.length, width: o.width, height: o.height, source: 'object-level bbox3d'}};
}}

function cornersFor(o, st) {{
  const length = st.length;
  const width = st.width;
  if (length == null || width == null || length <= 0 || width <= 0) return null;
  const yaw = st.yaw || 0;
  const c = Math.cos(yaw), s = Math.sin(yaw);
  const dx = length / 2, dy = width / 2;
  return [[dx, dy], [dx, -dy], [-dx, -dy], [-dx, dy], [dx, dy]].map(([px, py]) => [st.x + px * c - py * s, st.y + px * s + py * c]);
}}

function setFrame(index) {{
  currentIndex = Math.max(0, Math.min(traj.rel_t.length - 1, Number(index)));
  frameSlider.value = currentIndex;
  frameReadout.textContent = `frame ${{currentIndex}} / ${{traj.rel_t.length - 1}} | t=${{traj.rel_t[currentIndex].toFixed(1)}}s | speed=${{traj.speed[currentIndex].toFixed(2)}} m/s`;
  syncNoteEditor();
  render();
  applyFollowEgo();
  updateTimelineCursor();
}}

function currentMapRange() {{
  const gd = document.getElementById('map');
  const layout = gd._fullLayout;
  if (!layout || !layout.xaxis || !layout.yaxis) return null;
  return {{
    x: [layout.xaxis.range[0], layout.xaxis.range[1]],
    y: [layout.yaxis.range[0], layout.yaxis.range[1]]
  }};
}}

function applyFollowEgo() {{
  if (!followEgo.checked || !mapReady) return;
  const range = userMapRange || currentMapRange();
  if (!range) return;
  const xSpan = Math.abs(range.x[1] - range.x[0]);
  const ySpan = Math.abs(range.y[1] - range.y[0]);
  const cx = traj.x[currentIndex];
  const cy = traj.y[currentIndex];
  ignoreMapRelayout = true;
  Plotly.relayout('map', {{
    'xaxis.range': [cx - xSpan / 2, cx + xSpan / 2],
    'yaxis.range': [cy - ySpan / 2, cy + ySpan / 2]
  }}).finally(() => {{ ignoreMapRelayout = false; }});
}}

function resetMapView() {{
  userMapRange = null;
  ignoreMapRelayout = true;
  Plotly.relayout('map', {{'xaxis.autorange': true, 'yaxis.autorange': true}})
    .finally(() => {{ ignoreMapRelayout = false; }});
}}

function attachMapRelayoutHandler() {{
  if (mapRelayoutAttached) return;
  mapRelayoutAttached = true;
  document.getElementById('map').on('plotly_relayout', eventData => {{
    if (ignoreMapRelayout) return;
    if (eventData['xaxis.autorange'] || eventData['yaxis.autorange']) {{
      userMapRange = null;
      return;
    }}
    const hasDirectRange = eventData['xaxis.range[0]'] !== undefined && eventData['xaxis.range[1]'] !== undefined && eventData['yaxis.range[0]'] !== undefined && eventData['yaxis.range[1]'] !== undefined;
    const hasRangeArray = Array.isArray(eventData['xaxis.range']) && Array.isArray(eventData['yaxis.range']);
    if (hasDirectRange) {{
      userMapRange = {{
        x: [eventData['xaxis.range[0]'], eventData['xaxis.range[1]']],
        y: [eventData['yaxis.range[0]'], eventData['yaxis.range[1]']]
      }};
    }} else if (hasRangeArray) {{
      userMapRange = {{x: eventData['xaxis.range'].slice(), y: eventData['yaxis.range'].slice()}};
    }} else {{
      userMapRange = currentMapRange();
    }}
  }});
}}

function startPlayback() {{
  if (playbackTimer) return;
  playPause.textContent = 'Pause';
  playbackLastTickMs = performance.now();
  playbackRemainderFrames = 0;
  playbackTimer = setInterval(() => {{
    const now = performance.now();
    const elapsedMs = Math.max(0, now - playbackLastTickMs);
    playbackLastTickMs = now;
    const multiplier = Number(playbackSpeed.value) || 1;
    const frameRateHz = 10;
    playbackRemainderFrames += elapsedMs * frameRateHz * multiplier / 1000;
    const step = Math.max(1, Math.floor(playbackRemainderFrames));
    playbackRemainderFrames -= step;
    setFrame((currentIndex + step) % traj.rel_t.length);
  }}, 50);
}}

function stopPlayback() {{
  if (!playbackTimer) return;
  clearInterval(playbackTimer);
  playbackTimer = null;
  playbackLastTickMs = null;
  playbackRemainderFrames = 0;
  playPause.textContent = 'Play';
}}

function headingTrace() {{
  const idx = [];
  for (let i = 0; i < traj.x.length; i += 25) idx.push(i);
  return {{
    type: 'scatter', mode: 'markers', name: 'ego heading samples',
    x: idx.map(i => traj.x[i]), y: idx.map(i => traj.y[i]),
    marker: {{symbol: 'triangle-up', size: 9, color: '#111827', angle: idx.map(i => traj.yaw_deg[i])}},
    hovertemplate: 't=%{{customdata[0]:.1f}}s<br>yaw=%{{customdata[1]:.1f}} deg<extra></extra>',
    customdata: idx.map(i => [traj.rel_t[i], traj.yaw_deg[i]])
  }};
}}

function render() {{
  const selected = new Set(selectedClasses());
  const traces = [{{
    type: 'scattergl', mode: 'lines', name: 'ego trajectory',
    x: traj.x, y: traj.y,
    line: {{color: 'rgba(107,114,128,.45)', width: 2}},
    hoverinfo: 'skip'
  }}, {{
    type: 'scattergl', mode: 'lines', name: 'ego path elapsed',
    x: traj.x.slice(0, currentIndex + 1), y: traj.y.slice(0, currentIndex + 1),
    line: {{color: '#2563eb', width: 4}},
    hoverinfo: 'skip'
  }}, {{
    type: 'scattergl', mode: 'markers', name: 'ego current frame',
    x: [traj.x[currentIndex]], y: [traj.y[currentIndex]],
    marker: {{size: 13, color: '#16a34a', line: {{color: '#111827', width: 2}}}},
    hovertemplate: `frame ${{currentIndex}}<br>t=${{traj.rel_t[currentIndex].toFixed(1)}}s<br>x=%{{x:.2f}}, y=%{{y:.2f}}<br>speed=${{traj.speed[currentIndex].toFixed(2)}} m/s<extra></extra>`
  }}];
  if (document.getElementById('showEgoMarkers').checked) traces.push(headingTrace());
  if (document.getElementById('showObjects').checked) {{
    for (const c of classes) {{
      if (!selected.has(c)) continue;
      const active = objects.filter(o => o.className === c && isActiveObject(o));
      const states = active.map(o => objectState(o, currentIndex));
      traces.push({{
        type: 'scattergl', mode: 'markers', name: c,
        x: states.map(st => st.x), y: states.map(st => st.y),
        marker: {{size: 8, color: colorOf[c], opacity: 0.78}},
        customdata: active.map((o, i) => [o.objectId, o.type, o.subclassName || '', states[i].length, states[i].width, o.visibleMin, o.visibleMax, states[i].source]),
        hovertemplate: `${{c}} #%{{customdata[0]}}<br>x=%{{x:.2f}}, y=%{{y:.2f}}<br>type=%{{customdata[1]}} %{{customdata[2]}}<br>LxW=%{{customdata[3]:.1f}} x %{{customdata[4]:.1f}}<br>visible=%{{customdata[5]}}-%{{customdata[6]}}<br>source=%{{customdata[7]}}<extra></extra>`
      }});
    }}
  }}
  if (document.getElementById('showFootprints').checked) {{
    const fx = [], fy = [];
    for (const o of objects) {{
      if (!selected.has(o.className) || !isActiveObject(o)) continue;
      const st = objectState(o, currentIndex);
      if (st.x == null || st.y == null) continue;
      const corners = cornersFor(o, st);
      if (!corners) continue;
      for (const p of corners) {{ fx.push(p[0]); fy.push(p[1]); }}
      fx.push(null); fy.push(null);
    }}
    traces.push({{type: 'scattergl', mode: 'lines', name: 'selected bbox footprints', x: fx, y: fy, line: {{color: 'rgba(31,41,55,.35)', width: 1}}, hoverinfo: 'skip'}});
  }}
  Plotly.react('map', traces, {{
    margin: {{l: 55, r: 270, t: 20, b: 50}},
    xaxis: {{title: 'LCS x', scaleanchor: 'y', scaleratio: 1, zeroline: false}},
    yaxis: {{title: 'LCS y', zeroline: false}},
    legend: {{orientation: 'v', x: 1.16, xanchor: 'left', y: 1, yanchor: 'top', font: {{size: 10}}, itemsizing: 'constant'}},
    hovermode: 'closest',
    uirevision: 'preserve-map-zoom'
  }}, {{responsive: true}}).then(() => {{
    mapReady = true;
    attachMapRelayoutHandler();
    applyFollowEgo();
  }});
}}

function renderTimeline() {{
  const traces = [
    {{type: 'scattergl', mode: 'lines', x: traj.rel_t, y: traj.speed, name: 'speed m/s', line: {{color: '#2563eb'}}}},
    {{type: 'scattergl', mode: 'lines', x: traj.rel_t, y: traj.accel, name: 'accel m/s2', yaxis: 'y2', line: {{color: '#dc2626'}}}},
    {{type: 'scattergl', mode: 'lines', x: traj.rel_t, y: traj.jerk, name: 'jerk m/s3', yaxis: 'y3', line: {{color: '#16a34a'}}}},
    {{type: 'scattergl', mode: 'lines', x: traj.rel_t, y: traj.yaw_rate, name: 'yaw rate rad/s', yaxis: 'y4', line: {{color: '#9333ea'}}}}
  ];
  Plotly.newPlot('timeline', traces, {{
    margin: {{l: 72, r: 78, t: 26, b: 86}},
    xaxis: {{title: 'time since start (s)', domain: [0, 1], anchor: 'y4'}},
    yaxis: {{
      title: {{text: 'speed m/s', standoff: 8}},
      domain: [0.72, 1.0],
      tickfont: {{size: 10}},
      titlefont: {{size: 12}},
      zeroline: false
    }},
    yaxis2: {{
      title: {{text: 'accel m/s2', standoff: 8}},
      domain: [0.36, 0.64],
      tickfont: {{size: 10}},
      titlefont: {{size: 12}},
      zeroline: false
    }},
    yaxis3: {{
      title: {{text: 'jerk m/s3', standoff: 8}},
      overlaying: 'y2',
      side: 'right',
      tickfont: {{size: 10}},
      titlefont: {{size: 12}},
      showgrid: false,
      zeroline: false
    }},
    yaxis4: {{
      title: {{text: 'yaw rate rad/s', standoff: 8}},
      domain: [0.0, 0.28],
      tickfont: {{size: 10}},
      titlefont: {{size: 12}},
      zeroline: false
    }},
    legend: {{orientation: 'h', x: 0.5, xanchor: 'center', y: -0.18, yanchor: 'top', font: {{size: 11}}}}
  }}, {{responsive: true}});
}}

function updateTimelineCursor() {{
  const t = traj.rel_t[currentIndex];
  const noteShapes = Object.values(notes).map(note => ({{
    type: 'line',
    x0: note.timeSec,
    x1: note.timeSec,
    y0: 0,
    y1: 1,
    xref: 'x',
    yref: 'paper',
    line: {{color: '#f97316', width: 1, dash: 'dash'}}
  }}));
  Plotly.relayout('timeline', {{
    shapes: [...noteShapes, {{type: 'line', x0: t, x1: t, y0: 0, y1: 1, xref: 'x', yref: 'paper', line: {{color: '#111827', width: 2, dash: 'dot'}}}}]
  }});
}}

filter.addEventListener('change', render);
for (const id of ['showFootprints','showObjects','showEgoMarkers','persistStatic']) document.getElementById(id).addEventListener('change', render);
activeOnly.addEventListener('change', () => {{
  syncControlState();
  render();
}});
followEgo.addEventListener('change', () => {{
  if (followEgo.checked) userMapRange = currentMapRange();
  applyFollowEgo();
}});
document.getElementById('map').addEventListener('dblclick', resetMapView);
document.getElementById('saveNote').addEventListener('click', saveCurrentNote);
document.getElementById('deleteNote').addEventListener('click', deleteCurrentNote);
document.getElementById('exportNotes').addEventListener('click', exportNotesJson);
document.getElementById('syncNotesToList').addEventListener('click', syncNotesToList);
noteList.addEventListener('click', e => {{
  const item = e.target.closest('.noteItem');
  if (item) setFrame(Number(item.dataset.frame));
}});
frameSlider.addEventListener('input', e => {{ stopPlayback(); setFrame(e.target.value); }});
playbackSpeed.addEventListener('change', () => {{ if (playbackTimer) {{ stopPlayback(); startPlayback(); }} }});
playPause.addEventListener('click', () => playbackTimer ? stopPlayback() : startPlayback());
renderTimeline();
syncControlState();
renderNoteList();
setFrame(0);
</script>
</body>
</html>
"""


def thumbnail_svg(data, width=122, height=78):
    points = [(float(x), float(y), "#2563eb", 1.0) for x, y in zip(data["trajectory"]["x"], data["trajectory"]["y"])]
    class_colors = {c: PALETTE[i % len(PALETTE)] for i, c in enumerate(data["summary"]["classCounts"].keys())}
    object_points = []
    for obj in data["objects"]:
        color = class_colors.get(obj["className"], "#64748b")
        if obj.get("x") is not None and obj.get("y") is not None:
            object_points.append((float(obj["x"]), float(obj["y"]), color, 1.15))
        elif obj.get("xs") and obj.get("ys"):
            idxs = sorted({0, len(obj["xs"]) // 2, len(obj["xs"]) - 1})
            for idx in idxs:
                x = obj["xs"][idx]
                y = obj["ys"][idx]
                if x is not None and y is not None:
                    object_points.append((float(x), float(y), color, 0.9))
    points.extend(object_points)
    if not points:
        return f'<svg class="thumb" viewBox="0 0 {width} {height}" aria-label="empty thumbnail"></svg>'

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    pad = 5
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    scale = min((width - 2 * pad) / span_x, (height - 2 * pad) / span_y)
    draw_w = span_x * scale
    draw_h = span_y * scale
    off_x = (width - draw_w) / 2
    off_y = (height - draw_h) / 2

    def tx(x):
        return off_x + (x - min_x) * scale

    def ty(y):
        return height - (off_y + (y - min_y) * scale)

    step = max(1, len(data["trajectory"]["x"]) // 80)
    path_points = [
        f"{tx(float(x)):.1f},{ty(float(y)):.1f}"
        for x, y in zip(data["trajectory"]["x"][::step], data["trajectory"]["y"][::step])
    ]
    object_markup = "\n".join(
        f'<circle cx="{tx(x):.1f}" cy="{ty(y):.1f}" r="{r:.1f}" fill="{color}" opacity="0.72" />'
        for x, y, color, r in object_points[:900]
    )
    return (
        f'<svg class="thumb" viewBox="0 0 {width} {height}" role="img" aria-label="scene overview thumbnail">'
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="3" fill="#f8fafc" stroke="#d7dee8" />'
        f'<polyline points="{" ".join(path_points)}" fill="none" stroke="#2563eb" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" opacity="0.95" />'
        f'{object_markup}'
        f'</svg>'
    )


def index_html(rows):
    row_html = "\n".join(
        f"<tr data-recording=\"{r['recording']}\"><td class=\"thumbCell\"><a href=\"dataset_scene_explorers/{r['file']}\">{r['thumbnail']}</a></td>"
        f"<td><a href=\"dataset_scene_explorers/{r['file']}\">{r['recording']}</a></td>"
        f"<td>{r['frames']}</td><td>{r['duration']:.1f}s</td><td>{r['objects']}</td>"
        f"<td>{r['movingTracks']}</td><td>{r['topClasses']}</td><td class=\"manualNotes\" data-recording=\"{r['recording']}\"></td></tr>"
        for r in rows
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>MV2 OD Trajectory Dataset Explorer Index</title>
<style>
body {{ margin: 0; font-family: Arial, sans-serif; color: #17202a; background: #f6f8fb; }}
header {{ padding: 18px 22px; background: #17324d; color: white; }}
main {{ padding: 18px 22px; }}
table {{ border-collapse: collapse; width: 100%; background: white; border: 1px solid #d7dee8; }}
th, td {{ padding: 8px 10px; border-bottom: 1px solid #e5eaf0; text-align: left; font-size: 13px; vertical-align: top; }}
th {{ background: #eef3f8; position: sticky; top: 0; }}
a {{ color: #0f4c81; font-weight: 700; text-decoration: none; }}
.note {{ margin: 10px 0 16px; color: #475569; font-size: 13px; }}
.thumbCell {{ width: 132px; padding: 5px 7px; }}
.thumb {{ display: block; width: 122px; height: 78px; }}
.manualNotes {{ min-width: 190px; max-width: 280px; color: #334155; }}
.noteSummary {{ display: grid; gap: 4px; }}
.noteCount {{ font-weight: 700; color: #0f172a; }}
.tagPill {{ display: inline-block; margin: 2px 3px 0 0; padding: 2px 6px; border-radius: 999px; background: #eef3f8; color: #17324d; font-size: 11px; }}
.noteFrames {{ font-size: 11px; color: #64748b; }}
.emptyNotes {{ color: #94a3b8; font-size: 12px; }}
</style>
</head>
<body>
<header>
<h1>MV2 OD Trajectory Dataset Explorer</h1>
<p>{len(rows)} animated scene explorers generated from annotations.json + traj_lcs.txt.</p>
</header>
<main>
<div class="note">Each scene page loads Plotly from CDN. Use the embedded/static page only when offline; animated CDN pages need network access to cdn.plot.ly.</div>
<table>
<thead><tr><th>Preview</th><th>Recording</th><th>Frames</th><th>Duration</th><th>Objects</th><th>Per-frame tracks</th><th>Top classes</th><th>Manual tags / notes</th></tr></thead>
<tbody>
{row_html}
</tbody>
</table>
</main>
<script>
function escapeHtml(value) {{
  return String(value).replace(/[&<>"']/g, ch => ({{'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}}[ch]));
}}

function loadSceneNotes(recording) {{
  try {{
    const raw = localStorage.getItem(`mv2-situation-notes:${{recording}}`);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Object.values(parsed).sort((a, b) => Number(a.frame) - Number(b.frame));
  }} catch (err) {{
    console.warn('Unable to read notes for', recording, err);
    return [];
  }}
}}

function decodeNotePayload(encoded) {{
  const json = decodeURIComponent(escape(atob(encoded)));
  return JSON.parse(json);
}}

function importNotesFromHash() {{
  if (!location.hash.startsWith('#importNotes=')) return;
  try {{
    const encoded = location.hash.slice('#importNotes='.length);
    const payload = decodeNotePayload(encoded);
    if (!payload || !payload.recording || !Array.isArray(payload.notes)) return;
    const byFrame = {{}};
    for (const note of payload.notes) {{
      if (note && note.frame !== undefined) byFrame[String(note.frame)] = note;
    }}
    localStorage.setItem(`mv2-situation-notes:${{payload.recording}}`, JSON.stringify(byFrame));
    const message = document.createElement('div');
    message.className = 'note';
    message.textContent = `Imported ${{payload.notes.length}} manual note${{payload.notes.length === 1 ? '' : 's'}} for ${{payload.recording}}.`;
    document.querySelector('main').insertBefore(message, document.querySelector('table'));
    history.replaceState(null, document.title, location.pathname + location.search);
  }} catch (err) {{
    console.warn('Unable to import notes from hash', err);
  }}
}}

function renderManualNotes() {{
  document.querySelectorAll('.manualNotes').forEach(cell => {{
    const recording = cell.dataset.recording;
    const notes = loadSceneNotes(recording);
    if (!notes.length) {{
      cell.innerHTML = '<span class="emptyNotes">No notes</span>';
      return;
    }}
    const tagCounts = new Map();
    for (const note of notes) {{
      const tag = (note.tag || 'untagged').trim() || 'untagged';
      tagCounts.set(tag, (tagCounts.get(tag) || 0) + 1);
    }}
    const tags = Array.from(tagCounts.entries())
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .slice(0, 5)
      .map(([tag, count]) => `<span class="tagPill">${{escapeHtml(tag)}}${{count > 1 ? ' x' + count : ''}}</span>`)
      .join('');
    const frames = notes.slice(0, 8).map(note => Number(note.frame)).join(', ');
    const more = notes.length > 8 ? ` +${{notes.length - 8}} more` : '';
    cell.innerHTML = `<div class="noteSummary"><div class="noteCount">${{notes.length}} note${{notes.length === 1 ? '' : 's'}}</div><div>${{tags}}</div><div class="noteFrames">frames: ${{frames}}${{more}}</div></div>`;
  }});
}}

importNotesFromHash();
renderManualNotes();
window.addEventListener('storage', renderManualNotes);
window.addEventListener('focus', renderManualNotes);
</script>
</body>
</html>
"""


def main():
    SCENES_DIR.mkdir(parents=True, exist_ok=True)
    scene_dirs = sorted(p.parent for p in DATA_ROOT.rglob("annotations.json") if (p.parent / "traj_lcs.txt").exists())
    rows = []
    for i, scene_dir in enumerate(scene_dirs, 1):
        data = build_scene_data(scene_dir)
        recording = data["summary"]["recording"]
        out_name = f"{recording}_animated_explorer.html"
        (SCENES_DIR / out_name).write_text(scene_html(data), encoding="utf-8")
        top_classes = ", ".join(f"{k}:{v}" for k, v in list(data["summary"]["classCounts"].items())[:5])
        rows.append({
            "recording": recording,
            "file": out_name,
            "frames": data["summary"]["frames"],
            "duration": data["summary"]["durationSec"],
            "objects": data["summary"]["objects"],
            "movingTracks": data["summary"]["movingTracks"],
            "topClasses": top_classes,
            "thumbnail": thumbnail_svg(data),
        })
        print(f"[{i}/{len(scene_dirs)}] {recording}: {data['summary']['objects']} objects, {data['summary']['movingTracks']} per-frame tracks")
    (OUT_DIR / "dataset_trajectory_object_explorer_index.html").write_text(index_html(rows), encoding="utf-8")
    print(f"Wrote index: {OUT_DIR / 'dataset_trajectory_object_explorer_index.html'}")


if __name__ == "__main__":
    main()
