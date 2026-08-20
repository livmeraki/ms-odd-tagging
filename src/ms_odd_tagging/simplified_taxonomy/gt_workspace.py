from __future__ import annotations

import argparse
import json
import mimetypes
from copy import deepcopy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from .input_frame_gt import discover_completed_rows
from .input_frame_gt_server import _blank_gt, _existing_gt_by_frame, _inject_bulk_yes_no
from .manual_gt import _html
from .mapper import map_scenario_labels

FRAME_TAG_DIRNAME = "recording_frame_tags_1fps"


def _gt_path(gt_root: Path, recording: str) -> Path:
    return gt_root / f"{recording}_manual_gt.json"


def _frame_tag_records(recording_dir: Path) -> list[dict]:
    directory = recording_dir / FRAME_TAG_DIRNAME
    if not directory.is_dir():
        return []

    records: list[dict] = []
    for path in sorted(directory.glob("frame_*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(document, dict):
            continue

        frame_index = document.get("frame", document.get("frame_index"))
        if not isinstance(frame_index, int):
            continue

        timestamp = document.get("timestamp_s")
        if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool):
            timestamp = None

        motional = ((document.get("tags") or {}).get("motional_scenarios") or {})
        if not isinstance(motional, dict):
            motional = {}
        labels = sorted(str(name) for name, active in motional.items() if active is True)

        records.append(
            {
                "frame_index": frame_index,
                "timestamp": float(timestamp) if timestamp is not None else None,
                "labels": labels,
                "prediction": map_scenario_labels(labels).to_dict(),
            }
        )
    return records


def _prediction_tags(recording_dir: Path) -> list[str]:
    tags: set[str] = set()
    for record in _frame_tag_records(recording_dir):
        tags.update(record["labels"])
    return sorted(tags)


def _prepare_rows(rows: list[dict], recording_dir: Path, gt_path: Path, sample_hz: float) -> int:
    existing_gt = _existing_gt_by_frame(gt_path)
    records = _frame_tag_records(recording_dir)
    by_index = {record["frame_index"]: record for record in records}
    timed = [record for record in records if isinstance(record.get("timestamp"), float)]
    tolerance_s = 0.5 / sample_hz if sample_hz > 0 else 0.5

    matched = 0
    for row in rows:
        frame_index = row["frame_index"]
        record = by_index.get(frame_index)

        if record is None and timed:
            row_timestamp = row.get("timestamp")
            if isinstance(row_timestamp, (int, float)) and not isinstance(row_timestamp, bool):
                candidate = min(
                    timed,
                    key=lambda item: abs(float(item["timestamp"]) - float(row_timestamp)),
                )
                if abs(float(candidate["timestamp"]) - float(row_timestamp)) <= tolerance_s + 1e-9:
                    record = candidate

        prediction = record["prediction"] if record is not None else {}
        row["prediction"] = prediction
        if record is not None:
            matched += 1
            row["prediction_source_frame_index"] = record["frame_index"]
            row["prediction_source_timestamp"] = record.get("timestamp")

        if frame_index in existing_gt:
            row["gt"] = existing_gt[frame_index]
            row["reviewed"] = True
        else:
            row["gt"] = deepcopy(prediction) if prediction else _blank_gt()
            row["reviewed"] = False

    return matched


def _gt_finished(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(document, dict) and document.get("gt_finished") is True


def _recording_summary(recording_dir: Path, gt_root: Path, source_hz: float, sample_hz: float) -> dict:
    recording = recording_dir.name
    try:
        rows = discover_completed_rows(recording_dir, source_hz=source_hz, sample_hz=sample_hz)
    except ValueError:
        rows = []
    gt_path = _gt_path(gt_root, recording)
    gt_by_frame = _existing_gt_by_frame(gt_path)
    reviewed = sum(1 for row in rows if row["frame_index"] in gt_by_frame)
    total = len(rows)
    status = "done" if total and reviewed >= total else "in_progress" if reviewed else "not_started"
    prediction_dir = recording_dir / FRAME_TAG_DIRNAME
    return {
        "recording": recording,
        "total": total,
        "reviewed": reviewed,
        "remaining": max(0, total - reviewed),
        "percent": round(100.0 * reviewed / total, 1) if total else 0.0,
        "status": status,
        "gt_finished": _gt_finished(gt_path),
        "prediction": prediction_dir.is_dir(),
        "object_tags": _prediction_tags(recording_dir),
    }


def _dashboard_html() -> str:
    return r'''<!doctype html>
<html><head><meta charset="utf-8"><title>GT Workspace</title>
<style>
*{box-sizing:border-box}html,body{height:100%;margin:0;font-family:Arial,sans-serif;background:#0b1020;color:#e5e7eb}
#app{height:100%;display:grid;grid-template-columns:300px 1fr;overflow:hidden}
aside{min-height:0;background:#111827;border-right:1px solid #334155;display:flex;flex-direction:column}
header{padding:14px;border-bottom:1px solid #334155}h2{margin:0 0 5px}.muted{font-size:12px;color:#94a3b8}
.controls{padding:9px;border-bottom:1px solid #334155;display:grid;gap:7px}input,select{width:100%;padding:8px;border:1px solid #475569;border-radius:6px;background:#1f2937;color:#e5e7eb}
#summary{font-size:11px;color:#cbd5e1}.list{flex:1;min-height:0;overflow:auto;padding:6px}.rec{width:100%;text-align:left;padding:9px;margin:3px 0;border:1px solid transparent;border-radius:7px;background:#182235;color:#e5e7eb;cursor:pointer}.rec:hover,.rec.active{border-color:#38bdf8}.rec.missing{opacity:.55}.name{font-size:12px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.meta{font-size:11px;color:#94a3b8;margin-top:4px}.bar{height:5px;background:#334155;border-radius:4px;overflow:hidden;margin-top:5px}.fill{height:100%;background:#38bdf8}
main{height:100%;min-width:0;display:flex;flex-direction:column}.mainbar{height:48px;flex:0 0 48px;padding:8px 12px;background:#0f172a;border-bottom:1px solid #334155;display:flex;align-items:center;justify-content:space-between;gap:8px}.mainbar button{padding:7px 10px;background:#334155;color:white;border:1px solid #475569;border-radius:6px;cursor:pointer}.finish{font-size:12px;color:#cbd5e1}.frame{flex:1;min-height:0;width:100%;border:0;background:#111827}.empty{flex:1;display:flex;align-items:center;justify-content:center;color:#64748b}
@media(max-width:850px){#app{grid-template-columns:230px 1fr}}
</style></head><body><div id="app">
<aside><header><h2>GT Workspace</h2><div class="muted">current frame inputs + current 1 FPS tags</div></header>
<div class="controls"><input id="search" placeholder="Search recording"><select id="filter"><option value="unfinished">Unfinished</option><option value="all">All</option><option value="not_started">Not started</option><option value="in_progress">In progress</option><option value="done">Done</option><option value="missing_prediction">Missing prediction</option></select><div id="summary"></div></div>
<div id="list" class="list"></div></aside>
<main><div class="mainbar"><div id="current">Choose a recording</div><div><label class="finish"><input id="finishToggle" type="checkbox" disabled> GT finished</label> <button id="refresh">Refresh</button> <button id="next">Next unfinished →</button></div></div><div id="empty" class="empty">Select a recording.</div><iframe id="editor" class="frame" style="display:none"></iframe></main>
</div><script>
let recordings=[],selected=null;
function visible(r){const q=document.getElementById('search').value.trim().toLowerCase(),f=document.getElementById('filter').value;if(q&&!r.recording.toLowerCase().includes(q))return false;if(f==='unfinished'&&r.status==='done')return false;if(f==='missing_prediction'&&r.prediction)return false;if(['not_started','in_progress','done'].includes(f)&&r.status!==f)return false;return true;}
function render(){const list=document.getElementById('list');list.innerHTML='';const shown=recordings.filter(visible);for(const r of shown){const b=document.createElement('button');b.className=`rec ${r.prediction?'':'missing'} ${selected===r.recording?'active':''}`;b.onclick=()=>selectRecording(r.recording,true);b.innerHTML=`<div class="name">${r.gt_finished?'✓ ':''}${r.recording}</div><div class="bar"><div class="fill" style="width:${r.percent}%"></div></div><div class="meta">${r.reviewed}/${r.total} reviewed · ${r.percent}%${r.prediction?'':' · no frame tags'}</div>`;list.appendChild(b);}const reviewed=recordings.reduce((a,r)=>a+r.reviewed,0),total=recordings.reduce((a,r)=>a+r.total,0);document.getElementById('summary').textContent=`${shown.length}/${recordings.length} recordings · ${reviewed}/${total} frames reviewed`;}
async function refresh(){recordings=await fetch('/api/recordings').then(r=>r.json());render();if(selected&&recordings.some(r=>r.recording===selected))selectRecording(selected,false);}
function selectRecording(name,reload){selected=name;const r=recordings.find(x=>x.recording===name);document.getElementById('current').textContent=r?`${name} · ${r.reviewed}/${r.total}`:name;const toggle=document.getElementById('finishToggle');toggle.disabled=!r;toggle.checked=!!r?.gt_finished;document.getElementById('empty').style.display='none';const f=document.getElementById('editor');f.style.display='block';const url='/editor/'+encodeURIComponent(name);if(reload||!f.src.endsWith(url))f.src=url;render();}
async function setFinished(){if(!selected)return;await fetch('/finish/'+encodeURIComponent(selected),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({gt_finished:document.getElementById('finishToggle').checked})});await refresh();}
function nextUnfinished(){const list=recordings.filter(r=>!r.gt_finished&&r.total>0);if(!list.length)return;let i=selected?list.findIndex(r=>r.recording===selected):-1;selectRecording(list[(i+1+list.length)%list.length].recording,true);}
document.getElementById('search').addEventListener('input',render);document.getElementById('filter').addEventListener('change',render);document.getElementById('refresh').onclick=refresh;document.getElementById('next').onclick=nextUnfinished;document.getElementById('finishToggle').onchange=setFinished;window.addEventListener('message',e=>{if(e.data&&['gt-saved','gt-complete'].includes(e.data.type))refresh();});
refresh().then(()=>{const first=recordings.find(r=>!r.gt_finished&&r.total>0)||recordings[0];if(first)selectRecording(first.recording,true);});
</script></body></html>'''


def _inject_workspace_autosave(html: str, recording: str, sample_hz: float) -> str:
    endpoint = "/save/" + quote(recording, safe="")
    script = f'''<script>
const __workspaceEndpoint={json.dumps(endpoint)};
const __workspaceRecording={json.dumps(recording)};
const __workspacePersist=persist;
persist=function(){{
  __workspacePersist();
  const reviewed=rows.filter(r=>r.reviewed).map(r=>({{frame_index:r.frame_index,timestamp:r.timestamp,gt:r.gt,reviewed:true}}));
  fetch(__workspaceEndpoint,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{recording_id:__workspaceRecording,sampling_hz:{sample_hz},frames:reviewed}})}})
    .then(()=>window.parent.postMessage({{type:reviewed.length===rows.length?'gt-complete':'gt-saved',recording:__workspaceRecording}},'*'))
    .catch(err=>console.warn('GT autosave failed',err));
}};
</script>'''
    return html.replace("</body>", script + "</body>")


def _inject_workspace_layout(html: str) -> str:
    css = '''<style>
html,body{height:100%;overflow:hidden}
body{margin:0;padding:8px}
.container,.grid{max-height:calc(100vh - 16px)}
.card{min-height:0;overflow:auto}
#bevImg,#bev{max-height:calc(100vh - 150px);width:auto;max-width:100%;object-fit:contain}
@media(max-width:1000px){html,body{height:auto;overflow:auto}.container,.grid{max-height:none}.card{overflow:visible}#bevImg,#bev{max-height:none}}
</style>'''
    return html.replace("</head>", css + "</head>", 1)


def _safe_recording(frame_root: Path, recording: str) -> Path | None:
    if not recording or recording in {".", ".."} or "/" in recording or "\\" in recording:
        return None
    path = frame_root / recording
    return path if path.is_dir() else None


def _write_json_atomic(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _make_handler(frame_root: Path, gt_root: Path, source_hz: float, sample_hz: float):
    class Handler(BaseHTTPRequestHandler):
        def _send_bytes(self, payload: bytes, content_type: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def _send_text(self, text: str, content_type: str = "text/html; charset=utf-8", status: int = 200) -> None:
            self._send_bytes(text.encode("utf-8"), content_type, status)

        def do_GET(self) -> None:  # noqa: N802
            path = unquote(urlparse(self.path).path)
            if path == "/":
                self._send_text(_dashboard_html())
                return
            if path == "/api/recordings":
                summaries = [
                    _recording_summary(d, gt_root, source_hz, sample_hz)
                    for d in sorted(frame_root.iterdir(), key=lambda p: p.name)
                    if d.is_dir()
                ]
                self._send_text(json.dumps(summaries, ensure_ascii=False), "application/json; charset=utf-8")
                return
            if path.startswith("/editor/"):
                recording = path[len("/editor/"):]
                recording_dir = _safe_recording(frame_root, recording)
                if recording_dir is None:
                    self.send_error(404)
                    return
                try:
                    rows = discover_completed_rows(recording_dir, source_hz=source_hz, sample_hz=sample_hz)
                    if not rows:
                        raise ValueError("no completed sampled frames")
                    matched = _prepare_rows(rows, recording_dir, _gt_path(gt_root, recording), sample_hz)
                    for row in rows:
                        row["bev_uri"] = f"/bev/{quote(recording, safe='')}/{row['frame_index']}"
                    html = _html(rows, recording, sample_hz)
                    html = _inject_bulk_yes_no(html)
                    html = _inject_workspace_layout(html)
                    html = _inject_workspace_autosave(html, recording, sample_hz)
                    html = html.replace("</body>", f"<script>console.info('prediction rows matched: {matched}/{len(rows)}')</script></body>")
                    self._send_text(html)
                except Exception as exc:
                    self._send_text(f"<pre>Failed to load {recording}: {exc}</pre>", status=500)
                return
            if path.startswith("/bev/"):
                rest = path[len("/bev/"):]
                try:
                    recording, frame_text = rest.rsplit("/", 1)
                    frame_index = int(frame_text)
                except ValueError:
                    self.send_error(400)
                    return
                recording_dir = _safe_recording(frame_root, recording)
                if recording_dir is None:
                    self.send_error(404)
                    return
                image = recording_dir / f"frame_{frame_index:06d}" / "bev.png"
                if not image.is_file():
                    self.send_error(404)
                    return
                try:
                    payload = image.read_bytes()
                except OSError:
                    self.send_error(500)
                    return
                self._send_bytes(payload, mimetypes.guess_type(image.name)[0] or "image/png")
                return
            self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            path = unquote(urlparse(self.path).path)
            if path.startswith("/save/"):
                recording = path[len("/save/"):]
                action = "save"
            elif path.startswith("/finish/"):
                recording = path[len("/finish/"):]
                action = "finish"
            else:
                self.send_error(404)
                return
            if _safe_recording(frame_root, recording) is None:
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                gt_path = _gt_path(gt_root, recording)
                existing: dict = {}
                if gt_path.is_file():
                    try:
                        loaded = json.loads(gt_path.read_text(encoding="utf-8"))
                        if isinstance(loaded, dict):
                            existing = loaded
                    except (OSError, json.JSONDecodeError):
                        pass

                if action == "save":
                    frames = payload.get("frames", []) if isinstance(payload, dict) else []
                    document = {
                        "schema_version": "simplified-manual-gt-v1",
                        "recording_id": recording,
                        "sampling_hz": sample_hz,
                        "gt_finished": existing.get("gt_finished") is True,
                        "frames": frames,
                    }
                else:
                    document = {
                        "schema_version": existing.get("schema_version", "simplified-manual-gt-v1"),
                        "recording_id": recording,
                        "sampling_hz": existing.get("sampling_hz", sample_hz),
                        "gt_finished": payload.get("gt_finished") is True if isinstance(payload, dict) else False,
                        "frames": existing.get("frames", []),
                    }
                _write_json_atomic(gt_path, document)
            except Exception as exc:
                self._send_text(str(exc), "text/plain; charset=utf-8", 400)
                return
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()

        def log_message(self, fmt: str, *args) -> None:
            return

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Simplified Taxonomy GT Workspace using current frame inputs and recording_frame_tags_1fps."
    )
    parser.add_argument("--frame-root", type=Path, default=Path("outputs/02_frame_inputs"))
    parser.add_argument("--gt-root", type=Path, default=Path("outputs/06_gt_comparison/gt"))
    parser.add_argument("--source-hz", type=float, default=10.0)
    parser.add_argument("--sample-hz", type=float, default=1.0)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if not args.frame_root.is_dir():
        raise SystemExit(f"Frame root does not exist: {args.frame_root}")
    args.gt_root.mkdir(parents=True, exist_ok=True)

    recordings = [p for p in args.frame_root.iterdir() if p.is_dir()]
    if not recordings:
        raise SystemExit(f"No recording directories found under {args.frame_root}")

    server = ThreadingHTTPServer(
        (args.host, args.port),
        _make_handler(args.frame_root, args.gt_root, args.source_hz, args.sample_hz),
    )
    print(f"GT Workspace: http://{args.host}:{args.port}")
    print(f"Frame root: {args.frame_root}")
    print(f"GT root: {args.gt_root}")
    print(f"Prediction source: <recording>/{FRAME_TAG_DIRNAME}")
    print("Prediction alignment: exact frame index, then nearest timestamp within half a sample period.")
    print("Unreviewed frames are prediction-prefilled when a prediction is available.")
    print("Ctrl+C stops the workspace.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
