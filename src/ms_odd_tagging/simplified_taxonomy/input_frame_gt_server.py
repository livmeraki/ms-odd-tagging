from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .input_frame_gt import discover_completed_rows
from .manual_gt import _html


def _gt_document(recording: str, sample_hz: float, rows: list[dict]) -> dict:
    return {
        "schema_version": "simplified-manual-gt-v1",
        "recording_id": recording,
        "sampling_hz": sample_hz,
        "frames": [
            {
                "frame_index": row["frame_index"],
                "timestamp": row.get("timestamp"),
                "gt": row.get("gt"),
                "reviewed": True,
            }
            for row in rows
            if row.get("reviewed") is True and isinstance(row.get("gt"), dict)
        ],
    }


def _blank_gt() -> dict[str, Any]:
    return {
        "ego_motion": {"state": "unknown", "speed_band": "unknown"},
        "ego_maneuver": {"type": "unknown", "direction": None},
        "traffic_relation": {"lead": "unknown", "trail": "unknown"},
        "road_context": {
            "intersection": "unknown",
            "traffic_light_intersection": "unknown",
            "traffic_light_relevant": "unknown",
            "on_stopline_crosswalk": "unknown",
        },
        "interaction_tags": [],
    }


def _prediction_by_frame(path: Path | None) -> dict[int, dict[str, Any]]:
    if path is None:
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    frames = document.get("frames") if isinstance(document, dict) else None
    if not isinstance(frames, list):
        raise ValueError("prediction JSON must contain a top-level frames list")
    result: dict[int, dict[str, Any]] = {}
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        idx = frame.get("frame_index")
        if not isinstance(idx, int):
            continue
        prediction = frame.get("simplified_tags")
        if not isinstance(prediction, dict):
            required = {"ego_motion", "ego_maneuver", "traffic_relation", "road_context"}
            if required.issubset(frame):
                prediction = {
                    key: frame.get(key)
                    for key in (*required, "interaction_tags")
                }
        if isinstance(prediction, dict):
            result[idx] = prediction
    return result


def _existing_gt_by_frame(path: Path) -> dict[int, dict[str, Any]]:
    if not path.is_file():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    frames = document.get("frames") if isinstance(document, dict) else None
    if not isinstance(frames, list):
        return {}
    result: dict[int, dict[str, Any]] = {}
    for frame in frames:
        if not isinstance(frame, dict) or frame.get("reviewed") is not True:
            continue
        idx = frame.get("frame_index")
        gt = frame.get("gt")
        if isinstance(idx, int) and isinstance(gt, dict):
            result[idx] = gt
    return result


def _prepare_rows(
    rows: list[dict[str, Any]],
    prediction_path: Path | None,
    gt_output: Path,
) -> None:
    predictions = _prediction_by_frame(prediction_path)
    existing_gt = _existing_gt_by_frame(gt_output)
    for row in rows:
        idx = row["frame_index"]
        row["prediction"] = predictions.get(idx, {})
        if idx in existing_gt:
            row["gt"] = existing_gt[idx]
            row["reviewed"] = True
        else:
            # Keep GT independent from the displayed prediction.
            row["gt"] = _blank_gt()
            row["reviewed"] = False


def _inject_autosave(html: str, endpoint: str, recording: str, sample_hz: float) -> str:
    patch = f'''<script>
const __gtAutosaveEndpoint={json.dumps(endpoint)};
const __originalPersist=persist;
persist=function(){{
  __originalPersist();
  const reviewed=rows.filter(r=>r.reviewed).map(r=>({{
    frame_index:r.frame_index,
    timestamp:r.timestamp,
    gt:r.gt,
    reviewed:true
  }}));
  fetch(__gtAutosaveEndpoint,{{
    method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{
      recording_id:{json.dumps(recording)},
      sampling_hz:{sample_hz},
      frames:reviewed
    }})
  }}).catch(err=>console.warn('GT autosave failed',err));
}};
</script>'''
    return html.replace("</body>", patch + "</body>")


def _inject_equal_height_sidebar(html: str) -> str:
    old = '<section class="card"><div id="form"></div><div class="toolbar">'
    new = (
        '<section class="card" id="taggingCard">'
        '<div id="formScroll"><div id="form"></div></div>'
        '<div class="toolbar">'
    )
    html = html.replace(old, new, 1)
    css = '''<style>
#taggingCard{display:flex;flex-direction:column;overflow:hidden;min-height:0}
#formScroll{flex:1 1 auto;min-height:0;overflow-y:auto;padding-right:4px}
#taggingCard>.toolbar{flex:0 0 auto;padding-top:8px;border-top:1px solid #374151;background:#1f2937}
@media(max-width:1000px){#taggingCard{height:auto!important;max-height:none!important}#formScroll{overflow-y:visible}}
</style>'''
    script = '''<script>
function __syncTaggingHeight(){
  const bev=document.getElementById('bev');
  const card=document.getElementById('taggingCard');
  if(!bev||!card)return;
  if(window.innerWidth<=1000){card.style.height='';return;}
  const h=Math.max(240,Math.round(bev.getBoundingClientRect().height));
  card.style.height=h+'px';
}
window.addEventListener('resize',__syncTaggingHeight);
const __bevResizeObserver=new ResizeObserver(__syncTaggingHeight);
const __bevNode=document.getElementById('bev');
if(__bevNode)__bevResizeObserver.observe(__bevNode);
const __bevImage=document.getElementById('bevImg');
if(__bevImage)__bevImage.addEventListener('load',__syncTaggingHeight);
requestAnimationFrame(__syncTaggingHeight);
</script>'''
    html = html.replace("</head>", css + "</head>", 1)
    return html.replace("</body>", script + "</body>", 1)


def _inject_bulk_yes_no(html: str) -> str:
    css = '''<style>
.bulk-rest{display:inline-flex;gap:4px;margin-left:8px;vertical-align:middle}
.bulk-rest button{padding:4px 7px;margin:0 2px;font-size:11px;background:#273449;border-color:#475569}
.bulk-rest .bulk-yes{border-color:#22c55e}
.bulk-rest .bulk-no{border-color:#ef4444}
</style>'''
    script = '''<script>
function applyRemaining(path,value){
  const count=rows.length-i;
  if(count<=0)return;
  const pretty=label(path);
  if(!confirm(`Set ${pretty} = ${value.toUpperCase()} for current frame and all ${count-1} remaining sampled frame(s)?`))return;
  for(let k=i;k<rows.length;k++){
    ensureGT(rows[k]);
    set(rows[k].gt,path,value);
    rows[k].reviewed=true;
  }
  persist();
  render();
}
function addBulkYesNoControls(){
  const groups=document.querySelectorAll('#form .group');
  scalarPaths.forEach((path,gidx)=>{
    const values=defs[path]||[];
    if(!(values.includes('yes')&&values.includes('no')))return;
    const group=groups[gidx];
    if(!group||group.querySelector('.bulk-rest'))return;
    const h=group.querySelector('h3');
    if(!h)return;
    const wrap=document.createElement('span');
    wrap.className='bulk-rest';
    const yes=document.createElement('button');
    yes.type='button'; yes.className='bulk-yes'; yes.textContent='YES → rest';
    yes.onclick=(e)=>{e.stopPropagation();applyRemaining(path,'yes');};
    const no=document.createElement('button');
    no.type='button'; no.className='bulk-no'; no.textContent='NO → rest';
    no.onclick=(e)=>{e.stopPropagation();applyRemaining(path,'no');};
    wrap.append(yes,no); h.appendChild(wrap);
  });
}
const __renderBeforeBulk=render;
render=function(){__renderBeforeBulk();addBulkYesNoControls();};
render();
</script>'''
    html = html.replace("</head>", css + "</head>", 1)
    return html.replace("</body>", script + "</body>", 1)


def _make_handler(gt_path: Path, recording: str, sample_hz: float):
    class Handler(BaseHTTPRequestHandler):
        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "null")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/save":
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
                gt_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = gt_path.with_suffix(gt_path.suffix + ".tmp")
                tmp.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
                tmp.replace(gt_path)
            except Exception as exc:
                self.send_response(400)
                self._cors()
                self.end_headers()
                self.wfile.write(str(exc).encode("utf-8"))
                return
            self.send_response(204)
            self._cors()
            self.end_headers()

        def log_message(self, fmt: str, *args) -> None:
            return

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate read-only input-frame GT HTML and autosave reviewed GT to disk."
    )
    parser.add_argument("recording_dir", type=Path)
    parser.add_argument("--prediction", type=Path, default=None)
    parser.add_argument("--source-hz", type=float, default=10.0)
    parser.add_argument("--sample-hz", type=float, default=1.0)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--html-output", type=Path, default=None)
    parser.add_argument("--gt-output", type=Path, default=None)
    args = parser.parse_args()

    recording = args.recording_dir.name
    rows = discover_completed_rows(
        args.recording_dir,
        source_hz=args.source_hz,
        sample_hz=args.sample_hz,
    )
    if not rows:
        raise SystemExit("No completed input frames found; generator output was not modified.")

    html_output = args.html_output or Path("outputs/06_gt_comparison") / f"{recording}_manual_gt.html"
    gt_output = args.gt_output or Path("outputs/06_gt_comparison/gt") / f"{recording}_manual_gt.json"
    _prepare_rows(rows, args.prediction, gt_output)

    endpoint = f"http://127.0.0.1:{args.port}/save"
    html = _html(rows, recording, args.sample_hz)
    # Avoid stale browser rows when the generation snapshot gains new frames.
    old_key = f"simplified-gt-v3:{recording}"
    snapshot_key = f"simplified-gt-server-v1:{recording}:{len(rows)}:{rows[-1]['frame_index']}"
    html = html.replace(old_key, snapshot_key)
    html = _inject_equal_height_sidebar(html)
    html = _inject_bulk_yes_no(html)
    html = _inject_autosave(html, endpoint, recording, args.sample_hz)
    html_output.parent.mkdir(parents=True, exist_ok=True)
    html_output.write_text(html, encoding="utf-8")

    if not gt_output.exists():
        gt_output.parent.mkdir(parents=True, exist_ok=True)
        gt_output.write_text(
            json.dumps(_gt_document(recording, args.sample_hz, []), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    server = ThreadingHTTPServer(("127.0.0.1", args.port), _make_handler(gt_output, recording, args.sample_hz))
    print(f"Completed input frames in snapshot: {len(rows)}")
    print(f"Manual GT review: {html_output}")
    print(f"Autosave GT file: {gt_output}")
    if args.prediction:
        matched = sum(1 for row in rows if row.get("prediction"))
        print(f"Prediction overlay: {args.prediction} ({matched}/{len(rows)} sampled frames matched)")
    else:
        print("Prediction overlay: disabled")
    print(f"Autosave server: {endpoint}")
    print("Keep this process running while annotating. Ctrl+C stops autosave. Source input frames remain read-only.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
