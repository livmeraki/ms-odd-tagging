from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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


def _inject_autosave(html: str, endpoint: str) -> str:
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
    body:JSON.stringify({{recording_id:{json.dumps('RECORDING_PLACEHOLDER')},sampling_hz:{json.dumps('SAMPLE_PLACEHOLDER')},frames:reviewed}})
  }}).catch(err=>console.warn('GT autosave failed',err));
}};
</script>'''
    return html.replace("</body>", patch + "</body>")


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
            except Exception as exc:  # browser autosave should not crash the server
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
    endpoint = f"http://127.0.0.1:{args.port}/save"
    html = _html(rows, recording, args.sample_hz)
    html = _inject_autosave(html, endpoint)
    html = html.replace('"RECORDING_PLACEHOLDER"', json.dumps(recording))
    html = html.replace('"SAMPLE_PLACEHOLDER"', str(args.sample_hz))
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
