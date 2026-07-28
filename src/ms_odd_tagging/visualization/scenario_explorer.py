"""Generate standalone trajectory/OD/LD explorers with Phase 1 event intervals."""

from __future__ import annotations

import argparse
import html
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable

from ms_odd_tagging.input_generator.canonical import parse_trajectory
from ms_odd_tagging.tagger.rule_based.registry import (
    detect_events,
    detect_recording_events,
    load_config,
)


DEFAULT_OUTPUT_DIR = Path("outputs/07_scenario_explorers")
TEMPLATE_PATH = Path(__file__).with_name("templates") / "scenario_explorer.html"


def finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def rounded(value: Any, digits: int = 4) -> float | None:
    return round(float(value), digits) if finite(value) else None


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "recording"


def deduplicated_frames(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("frames"), list):
        candidates = payload["frames"]
    else:
        candidates = [
            frame
            for window in payload.get("windows", [])
            for frame in window.get("frames", [])
        ]
    by_index: dict[int, dict[str, Any]] = {}
    for frame in candidates:
        if isinstance(frame, dict) and isinstance(frame.get("frame_index"), int):
            by_index.setdefault(frame["frame_index"], frame)
    return [by_index[index] for index in sorted(by_index)]


def deduplicated_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = payload.get("rule_based_events") or []
    if not candidates:
        candidates = [
            event
            for window in payload.get("windows", [])
            for event in window.get("rule_based_events", [])
        ]
    result: dict[tuple[Any, ...], dict[str, Any]] = {}
    for event in candidates:
        if not isinstance(event, dict):
            continue
        key = (
            event.get("scenario"), event.get("start_frame"), event.get("end_frame"),
            event.get("start_timestamp_s"), event.get("end_timestamp_s"),
        )
        result[key] = event
    return sorted(
        result.values(),
        key=lambda event: (event.get("start_timestamp_s", 0), event.get("scenario", "")),
    )


def frames_from_trajectory(path: Path) -> list[dict[str, Any]]:
    trajectory = parse_trajectory(path)
    if not trajectory:
        return []
    start = trajectory[0]["timestamp"]
    return [
        {
            "frame_index": index,
            "time_since_start_s": row["timestamp"] - start,
            "ego": {
                "position_lcs_m": list(row["position"]),
                "velocity_lcs_mps": list(row["velocity"]),
                "speed_mps": row["speed"],
                "acceleration_mps2": row["acceleration"],
                "heading_lcs_rad": row["yaw"],
                "yaw_rate_radps": row["yaw_rate"],
            },
            "objects": [],
        }
        for index, row in enumerate(trajectory)
    ]


def compact_frame(frame: dict[str, Any]) -> list[Any]:
    ego = frame.get("ego") or {}
    position = ego.get("position_lcs_m") or []
    return [
        frame["frame_index"], rounded(frame.get("time_since_start_s"), 4),
        rounded(position[0] if len(position) > 0 else None),
        rounded(position[1] if len(position) > 1 else None),
        rounded(ego.get("speed_mps")),
        rounded(ego.get("heading_lcs_rad", ego.get("heading_rad"))),
    ]


def compact_objects(frames: Iterable[dict[str, Any]]) -> list[list[Any]]:
    result = []
    for frame in frames:
        states = []
        ego = frame.get("ego") or {}
        ego_heading = ego.get("heading_lcs_rad", ego.get("heading_rad"))
        for state in frame.get("objects", []):
            position = state.get("position_lcs_m") or []
            dimensions = state.get("dimensions_m") or {}
            if len(position) < 2 or not finite(position[0]) or not finite(position[1]):
                continue
            object_heading = state.get("heading_lcs_rad")
            if object_heading is None and finite(ego_heading) and finite(state.get("heading_relative_rad")):
                object_heading = float(ego_heading) + float(state["heading_relative_rad"])
            states.append([
                str(state.get("object_id", "")), state.get("class", "unknown"),
                rounded(position[0]), rounded(position[1]),
                rounded(dimensions.get("length")), rounded(dimensions.get("width")),
                rounded(object_heading),
            ])
        if states:
            result.append([frame["frame_index"], states])
    return result


def compact_ld(payload: dict[str, Any]) -> dict[str, list[list[Any]]]:
    store = payload.get("ld_feature_store") or {}
    point_by_id = {
        str(point.get("point_id")): point.get("position_lcs_m")
        for point in store.get("points", [])
    }

    def feature_rows(features: list[dict[str, Any]], id_key: str, kind: str) -> list[list[Any]]:
        rows = []
        for feature in features:
            points = [
                point_by_id.get(str(point_id))
                for point_id in feature.get("point_ids", [])
            ]
            xy = [[rounded(point[0]), rounded(point[1])] for point in points if point and len(point) >= 2]
            if len(xy) >= 2:
                rows.append([str(feature.get(id_key)), kind, xy])
        return rows

    roadmarks = []
    for feature in store.get("roadmarks", []):
        points = [point.get("position_lcs_m") for point in feature.get("points", [])]
        xy = [[rounded(point[0]), rounded(point[1])] for point in points if point and len(point) >= 2]
        if len(xy) >= 2:
            roadmarks.append([str(feature.get("roadmark_id")), feature.get("class", "roadmark"), xy])
    return {
        "laneLines": feature_rows(store.get("lane_lines", []), "line_id", "lane_line"),
        "boundaries": feature_rows(store.get("road_boundaries", []), "road_boundary_id", "road_boundary"),
        "roadmarks": roadmarks,
    }


def compact_event(event: dict[str, Any]) -> dict[str, Any]:
    evidence = event.get("evidence") or {}
    keep = (
        "start_speed_mps", "end_speed_mps", "minimum_speed_mps", "maximum_speed_mps",
        "peak_abs_lateral_acceleration_mps2", "peak_signed_lateral_acceleration_mps2",
        "representative_abs_lateral_acceleration_mps2", "peak_jerk_mps3",
        "representative_jerk_mps3", "signed_heading_delta_rad",
        "peak_signed_yaw_rate_rad_s", "trigger_speed_mps",
        "physical_turn_event_id", "threshold_provenance", "turn_speed_threshold_provenance",
        "same_logical_lane", "logical_lane_ids", "threshold_mode",
        "minimum_accumulated_heading_change_rad",
    )
    return {
        "scenario": event.get("scenario"),
        "startFrame": event.get("start_frame"),
        "endFrame": event.get("end_frame"),
        "startTime": rounded(event.get("start_timestamp_s")),
        "endTime": rounded(event.get("end_timestamp_s")),
        "duration": rounded(event.get("duration_s")),
        "evidence": {key: evidence[key] for key in keep if key in evidence},
    }


def build_explorer_payload(
    source: dict[str, Any], *, source_name: str = "recording", config_path: Path | None = None
) -> dict[str, Any]:
    frames = deduplicated_frames(source)
    if not frames:
        raise ValueError(f"{source_name}: no canonical/window frames found")
    events = deduplicated_events(source)
    quality = source.get("rule_based_data_quality")
    config = load_config(config_path)
    if not events:
        if source.get("ld_feature_store"):
            detected, quality = detect_recording_events(source, config)
        else:
            detected, quality = detect_events(frames, config)
        events = [event.to_dict() for event in detected]
    duration = max(float(frame["time_since_start_s"]) for frame in frames)
    return {
        "schemaVersion": "tagged-scenario-explorer-v1",
        "recording": source.get("recording_id") or source_name,
        "frameCount": len(frames),
        "durationSec": rounded(duration),
        "ruleConfigVersion": source.get("rule_config_version") or config["config_version"],
        "frames": [compact_frame(frame) for frame in frames],
        "objectsByFrame": compact_objects(frames),
        "ld": compact_ld(source),
        "events": [compact_event(event) for event in events],
        "quality": quality or {},
    }


def trajectory_payload(path: Path, config_path: Path | None = None) -> dict[str, Any]:
    frames = frames_from_trajectory(path)
    return build_explorer_payload(
        {"recording_id": path.parent.name, "frames": frames},
        source_name=path.parent.name,
        config_path=config_path,
    )


def generate_explorer(payload: dict[str, Any], output_path: Path) -> Path:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c")
    page = template.replace("__PAGE_TITLE__", html.escape(str(payload["recording"]))).replace("__SCENARIO_DATA__", serialized)
    if "__PAGE_TITLE__" in page or "__SCENARIO_DATA__" in page:
        raise ValueError("scenario explorer template replacement failed")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(page, encoding="utf-8")
    return output_path


def index_page(rows: list[dict[str, Any]]) -> str:
    links = "\n".join(
        f'<li><a href="{html.escape(row["file"])}">{html.escape(row["recording"])}</a>'
        f'<span>{row["frames"]} frames | {row["events"]} events | {row["duration"]:.1f} s</span></li>'
        for row in rows
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tagged Scenario Explorers</title><style>
:root{{--bg:#f7f8fa;--fg:#18202a;--card:#fff;--border:#d9dee7;--accent:#2458c6;--muted:#5f6b7a}}
@media(prefers-color-scheme:dark){{:root{{--bg:#11151b;--fg:#edf1f7;--card:#181e27;--border:#303a49;--accent:#8cb4ff;--muted:#aeb8c7}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px system-ui,sans-serif}}main{{max-width:920px;margin:auto;padding:28px}}h1{{font-size:24px}}ul{{list-style:none;padding:0;display:grid;gap:10px}}li{{display:flex;justify-content:space-between;gap:16px;padding:14px;background:var(--card);border:1px solid var(--border);border-radius:8px}}a{{color:var(--accent);font-weight:600}}span{{color:var(--muted)}}
</style></head><body><main><h1>Tagged Scenario Explorers</h1><ul>{links}</ul></main></body></html>"""


def discover_inputs(values: list[Path]) -> list[Path]:
    result = []
    for value in values:
        if value.is_dir():
            result.extend(
                path for path in sorted(value.glob("*.json"))
                if path.name != "manifest.json"
            )
        else:
            result.append(value)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate standalone Phase 1 tagged-scenario explorers.")
    parser.add_argument("inputs", nargs="*", type=Path, help="Canonical/window JSON files or directories.")
    parser.add_argument("--trajectory", action="append", type=Path, default=[], help="Raw traj_lcs.txt to tag and visualize. Repeatable.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    sources: list[tuple[str, dict[str, Any]]] = []
    for path in discover_inputs(args.inputs):
        payload = json.loads(path.read_text(encoding="utf-8"))
        sources.append((path.name, build_explorer_payload(payload, source_name=path.stem, config_path=args.config)))
    for path in args.trajectory:
        sources.append((path.name, trajectory_payload(path, args.config)))
    if not sources:
        parser.error("provide canonical/window JSON input or at least one --trajectory")
    rows = []
    for source_name, payload in sources:
        filename = f"{safe_name(str(payload['recording']))}_tagged_scenario_explorer.html"
        output_path = generate_explorer(payload, args.output_dir / filename)
        rows.append({"recording": payload["recording"], "file": filename, "frames": payload["frameCount"], "events": len(payload["events"]), "duration": payload["durationSec"]})
        print(f"Wrote {output_path} ({len(payload['events'])} events from {source_name})")
    index_path = args.output_dir / "index.html"
    index_path.write_text(index_page(rows), encoding="utf-8")
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(json.dumps({"schema_version": "tagged-scenario-explorer-manifest-v1", "index": index_path.name, "recordings": rows}, indent=2), encoding="utf-8")
    print(f"Wrote {index_path}")
    print(f"Wrote {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
