from __future__ import annotations

import argparse
import mimetypes
from collections import defaultdict
from pathlib import Path
from threading import Lock
from time import perf_counter
from urllib.parse import unquote, urlparse

from http.server import ThreadingHTTPServer

from . import gt_workspace as workspace
from .input_frame_gt_server import _existing_gt_by_frame


class _ListLoadProfiler:
    """Accumulate timing for one /api/recordings list build.

    The existing workspace builds the recording list synchronously by calling
    ``_recording_summary`` once for every recording. Replacing that function
    lets us measure the expensive sub-steps without changing GT behavior.
    """

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
        prediction_path = workspace._prediction_path(prediction_root, recording)

        t0 = perf_counter()
        gt_by_frame = _existing_gt_by_frame(gt_path)
        gt_frames_s = perf_counter() - t0

        t0 = perf_counter()
        gt_meta = workspace._gt_document_meta(gt_path)
        gt_meta_s = perf_counter() - t0

        t0 = perf_counter()
        object_tags = workspace._prediction_tags(prediction_path)
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

        result = {
            "recording": recording,
            "total": total,
            "reviewed": reviewed,
            "remaining": max(0, total - reviewed),
            "percent": round(100.0 * reviewed / total, 1) if total else 0.0,
            "status": status,
            "gt_finished": gt_meta["gt_finished"],
            "prediction": prediction_path.is_file(),
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
        print(f"  4. read prediction tags  : {totals['read_prediction_tags']:8.3f} s")
        print(f"  5. status/finalize       : {totals['finalize']:8.3f} s")
        print(f"  SUM recording summaries  : {totals['total']:8.3f} s")
        print("Slowest recordings:")
        for item in slowest:
            print(
                "  "
                f"{str(item['recording'])}: {float(item['total']):.3f}s "
                f"(frames {float(item['sample_frames']):.3f}s, "
                f"GT {float(item['read_gt_frames']) + float(item['read_gt_meta']):.3f}s, "
                f"prediction {float(item['read_prediction_tags']):.3f}s)"
            )
        dominant = max(
            (
                ("frame input scan", totals["sample_frames"]),
                ("GT reads", totals["read_gt_frames"] + totals["read_gt_meta"]),
                ("prediction tag reads", totals["read_prediction_tags"]),
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
    """Use the normal workspace handler, but serve the current ``bev.png`` name.

    The August simplified-GT workspace expected ``bev_revised.png``. The cleanup
    pipeline now writes ``bev.png``. Prefer the current file and retain the old
    filename only as a compatibility fallback.
    """
    BaseHandler = workspace._make_handler(
        frame_root, prediction_root, gt_root, source_hz, sample_hz
    )

    class Handler(BaseHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = unquote(urlparse(self.path).path)
            if not path.startswith("/bev/"):
                super().do_GET()
                return

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

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(
        description="GT Workspace with startup/list-load timing instrumentation."
    )
    parser.add_argument("--frame-root", type=Path, default=Path("outputs/02_frame_inputs"))
    parser.add_argument(
        "--prediction-root", type=Path, default=Path("outputs/06_gt_comparison/predictions")
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
