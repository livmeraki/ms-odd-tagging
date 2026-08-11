from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from .input_frame_gt import discover_completed_rows
from .input_frame_gt_server import (
    _existing_gt_by_frame,
    _inject_bulk_yes_no,
    _inject_equal_height_sidebar,
    _prepare_rows,
)
from .manual_gt import _html


def _sampled_frame_indices(recording_dir: Path, source_hz: float, sample_hz: float) -> list[int]:
    """Use the same timestamp-based sampling as the editor itself."""
    try:
        rows = discover_completed_rows(
            recording_dir,
            source_hz=source_hz,
            sample_hz=sample_hz,
        )
    except ValueError:
        return []
    return [row["frame_index"] for row in rows]


def _prediction_path(prediction_root: Path, recording: str) -> Path:
    return prediction_root / f"{recording}_simplified_prediction.json"


def _gt_path(gt_root: Path, recording: str) -> Path:
    return gt_root / f"{recording}_manual_gt.json"


def _recording_summary(
    recording_dir: Path,
    prediction_root: Path,
    gt_root: Path,
    source_hz: float,
    sample_hz: float,
) -> dict:
    recording = recording_dir.name
    sampled = _sampled_frame_indices(recording_dir, source_hz, sample_hz)
    gt_by_frame = _existing_gt_by_frame(_gt_path(gt_root, recording))
    reviewed = sum(1 for idx in sampled if idx in gt_by_frame)
    total = len(sampled)
    if total and reviewed >= total:
        status = "done"
    elif reviewed:
        status = "in_progress"
    else:
        status = "not_started"
    return {
        "recording": recording,
        "total": total,
        "reviewed": reviewed,
        "remaining": max(0, total - reviewed),
        "percent": round(100.0 * reviewed / total, 1) if total else 0.0,
        "status": status,
        "prediction": _prediction_path(prediction_root, recording).is_file(),
    }


def _dashboard_html() -> str:
    return r'''<!doctype html>
<html><head><meta charset="utf-8"><title>GT Workspace</title>
<style>
*{box-sizing:border-box}html,body{height:100%;margin:0;font-family:Arial,sans-serif;background:#0b1020;color:#e5e7eb}
#app{height:100%;display:grid;grid-template-columns:310px 1fr;overflow:hidden}
aside{background:#111827;border-right:1px solid #334155;display:flex;flex-direction:column;min-width:0}
.brand{padding:16px;border-bottom:1px solid #334155}.brand h2{margin:0 0 5px}.muted{color:#94a3b8;font-size:12px}
.controls{padding:10px;border-bottom:1px solid #334155;display:grid;gap:8px}input,select{width:100%;padding:8px;border-radius:7px;border:1px solid #475569;background:#1f2937;color:#e5e7eb}
#summary{font-size:12px;color:#cbd5e1}.list{overflow:auto;flex:1;padding:6px}.rec{width:100%;text-align:left;background:#182235;color:#e5e7eb;border:1px solid transparent;border-radius:8px;padding:9px;margin:3px 0;cursor:pointer}.rec:hover{border-color:#475569}.rec.active{border-color:#38bdf8;background:#172033}.rec.missing{opacity:.55}.top{display:flex;justify-content:space-between;gap:8px}.name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;font-weight:600}.pct{font-size:11px;color:#cbd5e1}.bar{height:5px;background:#334155;border-radius:4px;overflow:hidden;margin-top:6px}.fill{height:100%;background:#38bdf8}.meta{margin-top:5px;font-size:11px;color:#94a3b8}.dot{font-weight:bold}.done .dot{color:#22c55e}.in_progress .dot{color:#f59e0b}.not_started .dot{color:#64748b}
main{height:100%;min-width:0;display:flex;flex-direction:column}.mainbar{height:48px;flex:0 0 48px;padding:8px 14px;background:#0f172a;border-bottom:1px solid #334155;display:flex;align-items:center;justify-content:space-between}.mainbar button{padding:7px 10px;background:#334155;color:white;border:1px solid #475569;border-radius:7px;cursor:pointer}#current{font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.frame{flex:1;width:100%;border:0;background:#111827}.empty{flex:1;display:flex;align-items:center;justify-content:center;color:#64748b}
@media(max-width:900px){#app{grid-template-columns:240px 1fr}}
</style></head><body><div id="app">
<aside><div class="brand"><h2>GT Workspace</h2><div class="muted">All recordings · one autosave server</div></div>
<div class="controls"><input id="search" placeholder="Filter recordings"><select id="filter"><option value="all">All</option><option value="unfinished" selected>Unfinished</option><option value="not_started">Not started</option><option value="in_progress">In progress</option><option value="done">Done</option><option value="missing_prediction">Missing prediction</option></select><div id="summary"></div></div>
<div id="list" class="list"></div></aside>
<main><div class="mainbar"><div id="current">Choose a recording</div><div><button onclick="refresh()">Refresh</button> <button onclick="nextUnfinished()">Next unfinished →</button></div></div><div id="empty" class="empty">Select a recording from the left.</div><iframe id="editor" class="frame" style="display:none"></iframe></main>
</div><script>
let recordings=[], selected=null;
async function refresh(){
  recordings=await fetch('/api/recordings').then(r=>r.json()); renderList();
  if(selected && recordings.some(r=>r.recording===selected)){selectRecording(selected,false);}
}
function visible(r){const q=document.getElementById('search').value.trim().toLowerCase(),f=document.getElementById('filter').value;if(q&&!r.recording.toLowerCase().includes(q))return false;if(f==='unfinished'&&r.status==='done')return false;if(f==='missing_prediction'&&r.prediction)return false;if(['not_started','in_progress','done'].includes(f)&&r.status!==f)return false;return true;}
function renderList(){const list=document.getElementById('list');list.innerHTML='';const shown=recordings.filter(visible);for(const r of shown){const b=document.createElement('button');b.className=`rec ${r.status} ${r.prediction?'':'missing'} ${selected===r.recording?'active':''}`;b.onclick=()=>selectRecording(r.recording,true);b.innerHTML=`<div class="top"><span class="name"><span class="dot">●</span> ${r.recording}</span><span class="pct">${r.percent}%</span></div><div class="bar"><div class="fill" style="width:${r.percent}%"></div></div><div class="meta">${r.reviewed}/${r.total} reviewed${r.prediction?'':' · no prediction'}</div>`;list.appendChild(b);}const done=recordings.filter(r=>r.status==='done').length;const reviewed=recordings.reduce((a,r)=>a+r.reviewed,0), total=recordings.reduce((a,r)=>a+r.total,0);document.getElementById('summary').textContent=`${done}/${recordings.length} recordings done · ${reviewed}/${total} frames`;}
function selectRecording(name,reload){selected=name;const r=recordings.find(x=>x.recording===name);document.getElementById('current').textContent=r?`${name} · ${r.reviewed}/${r.total}`:name;document.getElementById('empty').style.display='none';const f=document.getElementById('editor');f.style.display='block';const url='/editor/'+encodeURIComponent(name);if(reload||!f.src.endsWith(url))f.src=url;renderList();}
function nextUnfinished(){const unfinished=recordings.filter(r=>r.status!=='done'&&r.total>0);if(!unfinished.length)return;let idx=selected?unfinished.findIndex(r=>r.recording===selected):-1;selectRecording(unfinished[(idx+1+unfinished.length)%unfinished.length].recording,true);}
document.getElementById('search').addEventListener('input',renderList);document.getElementById('filter').addEventListener('change',renderList);
window.addEventListener('message',async e=>{if(!e.data||!['gt-saved','gt-complete'].includes(e.data.type))return;await refresh();});
refresh().then(()=>{const first=recordings.find(r=>r.status!=='done'&&r.total>0)||recordings[0];if(first)selectRecording(first.recording,true);});
</script></body></html>'''


def _inject_workspace_autosave(html: str, recording: str, sample_hz: float) -> str:
    endpoint = "/save/" + quote(recording, safe="")
    script = f'''<script>
const __workspaceEndpoint={json.dumps(endpoint)};
const __workspaceRecording={json.dumps(recording)};
const __workspacePersist=persist;
persist=function(){{
  __workspacePersist();
  const reviewed=rows.filter(r=>r.reviewed).map(r=>({{
    frame_index:r.frame_index,timestamp:r.timestamp,gt:r.gt,reviewed:true
  }}));
  fetch(__workspaceEndpoint,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{
    recording_id:__workspaceRecording,sampling_hz:{sample_hz},frames:reviewed
  }})}}).then(()=>{{
    window.parent.postMessage({{type: reviewed.length===rows.length?'gt-complete':'gt-saved',recording:__workspaceRecording,reviewed:reviewed.length,total:rows.length}},'*');
  }}).catch(err=>console.warn('GT autosave failed',err));
}};
</script>'''
    return html.replace("</body>", script + "</body>")


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


def _make_handler(frame_root: Path, prediction_root: Path, gt_root: Path, source_hz: float, sample_hz: float):
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
                    _recording_summary(d, prediction_root, gt_root, source_hz, sample_hz)
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
                    prediction = _prediction_path(prediction_root, recording)
                    _prepare_rows(rows, prediction if prediction.is_file() else None, _gt_path(gt_root, recording))
                    for row in rows:
                        row["bev_uri"] = f"/bev/{quote(recording, safe='')}/{row['frame_index']}"
                    html = _html(rows, recording, sample_hz)
                    old_key = f"simplified-gt-v3:{recording}"
                    workspace_key = f"simplified-gt-workspace-v1:{recording}:{len(rows)}:{rows[-1]['frame_index']}"
                    html = html.replace(old_key, workspace_key)
                    html = _inject_equal_height_sidebar(html)
                    html = _inject_bulk_yes_no(html)
                    html = _inject_workspace_autosave(html, recording, sample_hz)
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
                image = recording_dir / f"frame_{frame_index:06d}" / "bev_revised.png"
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
            if not path.startswith("/save/"):
                self.send_error(404)
                return
            recording = path[len("/save/"):]
            if _safe_recording(frame_root, recording) is None:
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                frames = payload.get("frames", []) if isinstance(payload, dict) else []
                document = {
                    "schema_version": "simplified-manual-gt-v1",
                    "recording_id": recording,
                    "sampling_hz": sample_hz,
                    "frames": frames,
                }
                _write_json_atomic(_gt_path(gt_root, recording), document)
            except Exception as exc:
                self._send_text(str(exc), "text/plain; charset=utf-8", 400)
                return
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()

        def log_message(self, fmt: str, *args) -> None:
            return

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="Unified manual GT workspace for all simplified-taxonomy recordings.")
    parser.add_argument("--frame-root", type=Path, default=Path("outputs/02_frame_inputs_revised"))
    parser.add_argument("--prediction-root", type=Path, default=Path("outputs/06_gt_comparison/predictions"))
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
        _make_handler(args.frame_root, args.prediction_root, args.gt_root, args.source_hz, args.sample_hz),
    )
    url = f"http://{args.host}:{args.port}"
    print(f"GT Workspace: {url}")
    print(f"Recordings: {len(recordings)}")
    print(f"Frame root: {args.frame_root}")
    print(f"Prediction root: {args.prediction_root}")
    print(f"GT autosave root: {args.gt_root}")
    print("Keep this process running while annotating. Ctrl+C stops the workspace.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
