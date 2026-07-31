#!/usr/bin/env python3
"""Serve integrated GT-authoring explorers with a local GT save endpoint."""

from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
from typing import Any

from ms_odd_tagging.common.config import DATA_GT, OUTPUT_ROOT


DEFAULT_DIRECTORY = (
    OUTPUT_ROOT / "07_odld_scenario_explorers_gt_authoring_all_tags"
)


def validate_gt_payload(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    if payload.get("schema_version") != "scenario-frame-gt-labels-v1":
        raise ValueError("unexpected GT schema_version")
    recording = payload.get("recording_id")
    if not isinstance(recording, str) or not recording:
        raise ValueError("missing recording_id")
    if "/" in recording or "\\" in recording or recording in {".", ".."}:
        raise ValueError("unsafe recording_id")
    frames = payload.get("frames")
    if not isinstance(frames, dict):
        raise ValueError("frames must be an object")
    return payload


def write_gt_atomically(gt_dir: Path, payload: dict) -> Path:
    gt_dir.mkdir(parents=True, exist_ok=True)
    recording = payload["recording_id"]
    target = gt_dir / f"{recording}_frame_gt.json"
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=gt_dir,
        prefix=f".{target.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(body)
        temp_path = Path(handle.name)
    temp_path.replace(target)
    return target


class GtAuthoringHandler(SimpleHTTPRequestHandler):
    gt_dir: Path

    def do_POST(self) -> None:
        if self.path != "/__gt_authoring_save":
            self.send_error(HTTPStatus.NOT_FOUND, "unknown endpoint")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 50_000_000:
                raise ValueError("invalid request size")
            payload = validate_gt_payload(
                json.loads(self.rfile.read(length).decode("utf-8"))
            )
            target = write_gt_atomically(self.gt_dir, payload)
            self._send_json(
                HTTPStatus.OK,
                {"status": "ok", "file": str(target), "recording": payload["recording_id"]},
            )
        except Exception as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"status": "error", "error": str(exc)},
            )

    def _send_json(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    parser.add_argument("--gt-dir", type=Path, default=DATA_GT)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    handler = lambda *handler_args, **kwargs: GtAuthoringHandler(  # noqa: E731
        *handler_args,
        directory=str(args.directory),
        **kwargs,
    )
    GtAuthoringHandler.gt_dir = args.gt_dir
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Serving {args.directory} on http://{args.host}:{args.port}")
    print(f"Saving GT JSON to {args.gt_dir}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
