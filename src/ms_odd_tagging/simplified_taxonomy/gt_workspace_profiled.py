from __future__ import annotations

import argparse
import json
import mimetypes
from collections import defaultdict
from pathlib import Path
from threading import Lock
from time import perf_counter
from urllib.parse import quote, unquote, urlparse

from http.server import ThreadingHTTPServer

from . import gt_workspace as workspace
from .current_frame_predictions import (
    apply_current_predictions,
    current_prediction_tags,
    frame_tag_dir,
)
from .gt_workspace_layout import inject_workspace_layout
from .input_frame_gt import discover_completed_rows
from .input_frame_gt_server import _existing_gt_by_frame, _prepare_rows
from .manual_gt import _html


class _ListLoadProfiler:
    """Accumulate timing for one /api/recordings list build."""

    def __init__(self, expected_recordings: int) -> None:
        self.expected_recordings = expected_recordings
        self.lock = Lock()
        self.rows: list[dict[str, float | str]] = []
        self.request_number = 0

    def summarize(
        self,
        recording_dir: Path,
        prediction_root: Path,
        gt_root: Path,
        source_hz: float,
        sample_hz: float,
    ) -> dict:
        started = perf_counter()
        recording = recording_dir.name

        t0 = perf_counter()
        sampled = workspace._sampled_frame_indices(recording_dir, source_hz, sample_hz)
        sample_s = perf_counter() - t0

        gt_path = workspace._gt_path(gt_root, recording)

        t0 = perf_counter()
        gt_by_frame = _existing_gt_by_frame(gt_path)
        gt_frames_s = perf_counter() - t0

        t0 = perf_counter()
        gt_meta = workspace._gt_document_meta(gt_path)
        gt_meta_s = perf_counter() - t0

        t0 = perf_counter()
        object_tags = current_prediction_tags(recording_dir)
        prediction_tags_s = perf_counter() - t0

        t0 = perf_counter()
        reviewed = sum(1 for idx in sampled if idx in gt_by_frame)
        total = len(sampled)
        if total and reviewed >= total:
            status = "done"
        elif reviewed:
            status = "in_progress"
        else:
            status = "not_started"
        finalize_s = perf_counter() - t0

        prediction_available = frame_tag_dir(recording_dir).is_dir()
        result = {
            "recording": recording,
            "total": total,
            "reviewed": reviewed,
            "remaining": max(0, total - reviewed),
            "percent": round(100.0 * reviewed / total, 1) if total else 0.0,
            "status": status,
            "gt_finished": gt_meta["gt_finished"],
            "prediction": prediction_available,
            "object_tags": object_tags,
        }

        row = {
            "recording": recording,
            "sample_frames": sample_s,
            "read_gt_frames": gt_frames_s,
            "read_gt_meta": gt_meta_s,
            "read_prediction_tags": prediction_tags_s,
            "finalize": finalize_s,
            "total": perf_counter() - started,
        }
        self._record(row)
        return result

    def _record(self, row: dict[str, float | str]) -> None:
        with self.lock:
            self.rows.append(row)
            if len(self.rows) < self.expected_recordings:
                return
            rows = self.rows[: self.expected_recordings]
            del self.rows[: self.expected_recordings]
            self.request_number += 1

        totals: defaultdict[str, float] = defaultdict(float)
        for item in rows:
            for key in (
                "sample_frames",
                "read_gt_frames",
                "read_gt_meta",
                "read_prediction_tags",
                "finalize",
                "total",
            ):
                totals[key] += float(item[key])

        slowest = sorted(rows, key=lambda item: float(item["total"]), reverse=True)[:5]
        print("\n" + "=" * 72)
        print(f"GT WORKSPACE LIST LOAD PROFILE #{self.request_number}")
        print(f"Recordings scanned: {len(rows)}")
        print("Accumulated per-recording work:")
        print(f"  1. scan/read frame inputs : {totals['sample_frames']:8.3f} s")
        print(f"  2. read reviewed GT      : {totals['read_gt_frames']:8.3f} s")
        print(f"  3. read GT metadata      : {totals['read_gt_meta']:8.3f} s")
        print(f"  4. read current frame tags: {totals['read_prediction_tags']:7.3f} s")
        print(f"  5. status/finalize       : {totals['finalize']:8.3f} s")
        print(f"  SUM recording summaries  : {totals['total']:8.3f} s")
        print("Slowest recordings:")
        for item in slowest:
            print(
                "  "
                f"{str(item['recording'])}: {float(item['total']):.3f}s "
                f"(frames {float(item['sample_frames']):.3f}s, "
                f"GT {float(item['read_gt_frames']) + float(item['read_gt_meta']):.3f}s, "
                f"frame-tags {float(item['read_prediction_tags']):.3f}s)"
            )
        dominant = max(
            (
                ("frame input scan", totals["sample_frames"]),
                ("GT reads", totals["read_gt_frames"] + totals["read_gt_meta"]),
                ("current frame-tag reads", totals["read_prediction_tags"]),
                ("finalization", totals["finalize"]),
            ),
            key=lambda pair: pair[1],
        )
        print(f"Dominant measured step: {dominant[0]} ({dominant[1]:.3f}s)")
        print("=" * 72 + "\n")


def _make_profiled_handler(
    frame_root: Path,
    prediction_root: Path,
    gt_root: Path,
    source_hz: float,
    sample_hz: float,
):
    """Workspace handler using current BEVs and current frame-tag predictions."""
    BaseHandler = workspace._make_handler(
        frame_root, prediction_root, gt_root, source_hz, sample_hz
    )

    class Handler(BaseHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = unquote(urlparse(self.path).path)

            if path.startswith("/editor/"):
                recording = path[len("/editor/") :]
                recording_dir = workspace._safe_recording(frame_root, recording)
                if recording_dir is None:
                    self.send_error(404)
                    return
                try:
                    rows = discover_completed_rows(
                        recording_dir,
                        source_hz=source_hz,
                        sample_hz=sample_hz,
                    )
                    if not rows:
                        raise ValueError("no completed sampled frames")

                    gt_path = workspace._gt_path(gt_root, recording)
                    _prepare_rows(rows, None, gt_path)
                    matched = apply_current_predictions(
                        rows,
                        recording_dir,
                        prefill_unreviewed=True,
                        sample_hz=sample_hz,
                    )
                    for row in rows:
                        row["bev_uri"] = f"/bev/{quote(recording, safe='')}/{row['frame_index']}"

                    html = _html(rows, recording, sample_hz)
                    old_key = f"simplified-gt-v3:{recording}"
                    workspace_key = (
                        f"simplified-gt-workspace-current-v1:{recording}:"
                        f"{len(rows)}:{rows[-1]['frame_index']}"
                    )
                    html = html.replace(old_key, workspace_key)
                    html = workspace._inject_equal_height_sidebar(html)
                    html = workspace._inject_bulk_yes_no(html)
                    html = workspace._inject_workspace_autosave(html, recording, sample_hz)
                    note = (
                        f"<script>console.info('Current frame-tag predictions matched: "
                        f"{matched}/{len(rows)}');</script>"
                    )
                    html = html.replace("</body>", note + "</body>")
                    self._send_text(html)
                except Exception as exc:
                    self._send_text(f"<pre>Failed to load {recording}: {exc}</pre>", status=500)
                return

            if path.startswith("/bev/"):
                rest = path[len("/bev/") :]
                try:
                    recording, frame_text = rest.rsplit("/", 1)
                    frame_index = int(frame_text)
                except ValueError:
                    self.send_error(400)
                    return

                recording_dir = workspace._safe_recording(frame_root, recording)
                if recording_dir is None:
                    self.send_error(404)
                    return

                frame_dir = recording_dir / f"frame_{frame_index:06d}"
                image = frame_dir / "bev.png"
                if not image.is_file():
                    image = frame_dir / "bev_revised.png"
                if not image.is_file():
                    self.send_error(404)
                    return

                try:
                    payload = image.read_bytes()
                except OSError:
                    self.send_error(500)
                    return
                self._send_bytes(
                    payload,
                    mimetypes.guess_type(image.name)[0] or "image/png",
                )
                return

            super().do_GET()

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(
        description="GT Workspace with startup/list-load timing instrumentation."
    )
    parser.add_argument("--frame-root", type=Path, default=Path("outputs/02_frame_inputs"))
    parser.add_argument(
        "--prediction-root",
        type=Path,
        default=Path("outputs/06_gt_comparison/predictions"),
        help="Legacy fallback path; current frame tags under frame-root are used by the editor.",
    )
    parser.add_argument("--gt-root", type=Path, default=Path("outputs/06_gt_comparison/gt"))
    parser.add_argument("--source-hz", type=float, default=10.0)
    parser.add_argument("--sample-hz", type=float, default=1.0)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    startup = perf_counter()
    t0 = perf_counter()
    if not args.frame_root.is_dir():
        raise SystemExit(f"Frame root does not exist: {args.frame_root}")
    frame_root_check_s = perf_counter() - t0

    t0 = perf_counter()
    args.gt_root.mkdir(parents=True, exist_ok=True)
    gt_root_setup_s = perf_counter() - t0

    t0 = perf_counter()
    recordings = [p for p in args.frame_root.iterdir() if p.is_dir()]
    recording_discovery_s = perf_counter() - t0
    if not recordings:
        raise SystemExit(f"No recording directories found under {args.frame_root}")

    profiler = _ListLoadProfiler(len(recordings))
    workspace._recording_summary = profiler.summarize
    workspace._inject_equal_height_sidebar = inject_workspace_layout

    t0 = perf_counter()
    server = ThreadingHTTPServer(
        (args.host, args.port),
        _make_profiled_handler(
            args.frame_root,
            args.prediction_root,
            args.gt_root,
            args.source_hz,
            args.sample_hz,
        ),
    )
    server_setup_s = perf_counter() - t0

    url = f"http://{args.host}:{args.port}"
    print(f"GT Workspace profiler: {url}")
    print(f"Recordings: {len(recordings)}")
    print("Prediction source: <frame-root>/<recording>/recording_frame_tags_1fps")
    print("Prediction alignment: exact frame index, then nearest timestamp within half a sample period.")
    print("Unreviewed GT is prefilled from prediction but remains UNREVIEWED until saved.")
    print("Startup timing before browser request:")
    print(f"  frame-root check     : {frame_root_check_s:.3f} s")
    print(f"  GT-root setup        : {gt_root_setup_s:.3f} s")
    print(f"  recording discovery  : {recording_discovery_s:.3f} s")
    print(f"  HTTP server setup    : {server_setup_s:.3f} s")
    print(f"  startup total        : {perf_counter() - startup:.3f} s")
    print("Open the URL. A detailed list-load profile prints after /api/recordings finishes.")
    print("Press Refresh in the workspace to profile another list load.")
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
