"""Fresh-run CLI for isolated lane-debug-v2 experiments."""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import DEBUG_IMPLEMENTATION_VERSION
from .detector_static_order_integrated import run_lane_debug_v2
from .lane_changes import run_lane_change_debug
from .explorer_visualization import render_plotly_explorer


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, indent=2), encoding="utf-8")


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return None


def run_one(
    canonical_path: Path,
    output_root: Path,
    config: dict[str, Any],
    lane_change_config: dict[str, Any],
    run_id: str | None = None,
) -> list[Path]:
    recording = _load(canonical_path)
    rid = recording.get("recording_id") or canonical_path.stem.replace("_canonical_odld_frames", "")
    run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    root = output_root / run_id
    if root.exists():
        raise FileExistsError(f"refusing to reuse existing debug run directory: {root}")
    root.mkdir(parents=True)

    following = run_lane_debug_v2(recording, config)
    changes = run_lane_change_debug(recording, following, lane_change_config)

    lane_path = root / "lane_results" / f"{rid}_lane_debug_v2.json"
    tag_path = root / "tagging_results" / f"{rid}_lane_change_debug_v2.json"
    explorer_path = root / "explorers" / f"{rid}_lane_debug_v2_plotly.html"
    metadata_path = root / "metadata.json"

    _write(lane_path, following)
    _write(tag_path, changes)
    _write(metadata_path, {
        "run_id": run_id,
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit_sha": _git_sha(),
        "input_recording": rid,
        "input_path": str(canonical_path),
        "debug_implementation_version": DEBUG_IMPLEMENTATION_VERSION,
        "lane_debug_config": config,
        "lane_change_config_source": "provided direct_scenarios config",
        "artifact_policy": "fresh_run_no_reuse",
    })
    render_plotly_explorer(recording, following, changes, explorer_path, run_id)
    return [metadata_path, lane_path, tag_path, explorer_path]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("recording", help="recording ID without _canonical_odld_frames.json")
    p.add_argument("--canonical-dir", type=Path, required=True)
    p.add_argument("--output-root", type=Path, default=Path("outputs/debug_lane_v2"))
    p.add_argument("--config", type=Path, default=Path("configs/lane_debug_v2.json"))
    p.add_argument("--lane-change-config", type=Path, default=Path("configs/direct_scenarios.yaml"))
    p.add_argument("--run-id", default=None)
    a = p.parse_args(argv)

    canonical = a.canonical_dir / f"{a.recording}_canonical_odld_frames.json"
    if not canonical.is_file():
        p.error(f"missing canonical recording: {canonical}")
    for output in run_one(canonical, a.output_root, _load(a.config), _load(a.lane_change_config), a.run_id):
        print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
