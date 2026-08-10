"""Evidence bundle serialization and BEV rendering."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ms_odd_tagging.input_generator.revised_bev import render_revised_bev_png

from .config import TRAFFIC_LIGHT_LABELS, VlmPocConfig
from .geometry import ego_acceleration, ego_heading, ego_position, ego_speed, motion_state
from .models import CandidateWindow


def stable_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def frame_summary(frame: dict[str, Any]) -> dict[str, Any]:
    return {
        "frame_index": frame.get("frame_index"),
        "time_since_start_s": frame.get("time_since_start_s"),
        "ego": {
            "position_lcs_m": list(ego_position(frame)),
            "speed_mps": ego_speed(frame),
            "acceleration_mps2": ego_acceleration(frame),
            "heading_lcs_rad": ego_heading(frame),
            "motion_state": motion_state(frame),
        },
    }


def selected_window_frames(
    frames: list[dict[str, Any]],
    start_pos: int,
    end_pos: int,
    config: VlmPocConfig,
) -> list[dict[str, Any]]:
    window = frames[start_pos : end_pos + 1]
    if not window:
        return []
    period_s = 1.0 / config.frames_per_second
    selected = []
    next_t: float | None = None
    for frame in window:
        timestamp = frame.get("time_since_start_s")
        if not isinstance(timestamp, (int, float)):
            continue
        timestamp = float(timestamp)
        if next_t is None or timestamp + 1e-9 >= next_t:
            selected.append(frame)
            next_t = timestamp + period_s if next_t is None else next_t
            while next_t <= timestamp + 1e-9:
                next_t += period_s
        if len(selected) >= config.max_bev_images:
            break
    if not selected:
        selected = [window[0]]
    return selected[: config.max_bev_images]


def _keep_event_driven_waiting_bev(
    frame: dict[str, Any],
    candidate: CandidateWindow,
    config: VlmPocConfig,
) -> bool:
    """Keep all selected BEVs for the BEV-first pedestrian experiment."""
    return True


def _waiting_bev_debug_context(candidate: CandidateWindow) -> dict[str, Any] | None:
    """Highlight candidate pedestrians without adding semantic/conflict labels."""
    if not (
        candidate.scenario == "waiting_for_pedestrian_to_cross"
        and candidate.metadata.get("candidate_strategy") == "event-driven"
    ):
        return None
    return {
        "rule_based_reference": {
            "active_events": [
                {"evidence": {"source_object_ids": list(candidate.primary_object_ids)}}
            ]
        }
    }


def render_candidate_bevs(
    recording: dict[str, Any],
    candidate: CandidateWindow,
    output_root: Path,
    config: VlmPocConfig,
) -> CandidateWindow:
    frames_by_index = {
        int(frame["frame_index"]): frame
        for frame in recording.get("frames", [])
        if isinstance(frame.get("frame_index"), int)
    }
    paths = []
    rendered_frame_indices = []
    waiting_bev_only = (
        candidate.scenario == "waiting_for_pedestrian_to_cross"
        and candidate.metadata.get("candidate_strategy") == "event-driven"
    )
    for frame_index in candidate.selected_frame_indices[: config.max_bev_images]:
        frame = frames_by_index.get(frame_index)
        if frame is None:
            continue
        if not _keep_event_driven_waiting_bev(frame, candidate, config):
            continue
        path = (
            output_root
            / "bev"
            / candidate.scenario
            / candidate.recording_id
            / f"{candidate.candidate_id}_frame_{frame_index:06d}.png"
        )
        render_revised_bev_png(
            recording,
            frame,
            path,
            config.bev_extent_m,
            config.bev_size_px,
            proximity_radius_m=0.0 if waiting_bev_only or candidate.scenario == "on_intersection" else 30.0,
            debug_context=_waiting_bev_debug_context(candidate),
        )
        paths.append(str(path))
        rendered_frame_indices.append(frame_index)
    return CandidateWindow(
        **{
            **candidate.to_dict(),
            "evidence": candidate.evidence,
            "selected_frame_indices": rendered_frame_indices,
            "bev_paths": paths,
        }
    )


def serialize_candidate_bundle(candidate: CandidateWindow) -> dict[str, Any]:
    traffic_light_episode = candidate.scenario == "traffic_light_episode"
    instructions = {
        "one_scenario_per_request": not traffic_light_episode,
        "use_only_supplied_evidence": True,
        "json_only": True,
    }
    if traffic_light_episode:
        instructions.update(
            {
                "multi_label": True,
                "traffic_light_labels": list(TRAFFIC_LIGHT_LABELS),
                "use_structured_motion_values": True,
            }
        )
    return {
        "schema_version": "qwen-vlm-poc-candidate-v1",
        "candidate": candidate.to_dict(),
        "instructions": instructions,
    }


def write_candidate_bundle(candidate: CandidateWindow, output_root: Path) -> Path:
    path = (
        output_root
        / "candidates"
        / candidate.scenario
        / candidate.recording_id
        / f"{candidate.candidate_id}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(serialize_candidate_bundle(candidate), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def load_candidate_bundle(path: Path) -> CandidateWindow:
    from .models import EvidenceItem

    data = json.loads(path.read_text(encoding="utf-8"))
    candidate = data.get("candidate", data)
    evidence = [
        EvidenceItem(
            evidence_id=item["evidence_id"],
            kind=item["kind"],
            summary=item["summary"],
            data=item.get("data") or {},
        )
        for item in candidate.get("evidence", [])
    ]
    return CandidateWindow(
        candidate_id=candidate["candidate_id"],
        recording_id=candidate["recording_id"],
        scenario=candidate["scenario"],
        start_frame=int(candidate["start_frame"]),
        end_frame=int(candidate["end_frame"]),
        start_timestamp_s=float(candidate["start_timestamp_s"]),
        end_timestamp_s=float(candidate["end_timestamp_s"]),
        evidence=evidence,
        selected_frame_indices=[int(v) for v in candidate.get("selected_frame_indices", [])],
        bev_paths=[str(v) for v in candidate.get("bev_paths", [])],
        primary_object_ids=[str(v) for v in candidate.get("primary_object_ids", [])],
        recall_reasons=[str(v) for v in candidate.get("recall_reasons", [])],
        metadata=candidate.get("metadata") or {},
    )
