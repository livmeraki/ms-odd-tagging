#!/usr/bin/env python3
"""Forensic report for one rejected event-driven waiting-pedestrian candidate."""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
from pathlib import Path
from typing import Any


SCENARIO = "waiting_for_pedestrian_to_cross"
RECORDING = "Rec_Drv_GER_MACHET18_20260422_101126"
CASE_SUFFIX = "scene_000528_000597"
TARGET_IDS = ["437", "509", "541", "544"]


def finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def load_json(path: Path) -> Any:
    with path.open() as f:
        return json.load(f)


def frame_index(frame: dict[str, Any]) -> int:
    return int(frame["frame_index"])


def object_id(obj: dict[str, Any]) -> str:
    return str(obj.get("track_id") or obj.get("object_id") or obj.get("id") or "")


def object_class(obj: dict[str, Any]) -> str:
    return str(obj.get("class") or obj.get("class_name") or obj.get("category") or "")


def lcs_to_ego(point: list[float], frame: dict[str, Any]) -> tuple[float, float]:
    ego = frame.get("ego") or {}
    ego_pos = ego.get("position_lcs_m") or [0.0, 0.0]
    yaw = float(ego.get("heading_lcs_rad") or 0.0)
    dx = float(point[0]) - float(ego_pos[0])
    dy = float(point[1]) - float(ego_pos[1])
    c = math.cos(yaw)
    s = math.sin(yaw)
    return c * dx + s * dy, -s * dx + c * dy


def object_ego_xy_like_pipeline(obj: dict[str, Any], frame: dict[str, Any]) -> tuple[float, float] | None:
    pos_ego = obj.get("position_ego_m") or {}
    if finite(pos_ego.get("longitudinal_m")) and finite(pos_ego.get("lateral_m")):
        return float(pos_ego["longitudinal_m"]), float(pos_ego["lateral_m"])
    if finite(pos_ego.get("longitudinal")) and finite(pos_ego.get("lateral")):
        return float(pos_ego["longitudinal"]), float(pos_ego["lateral"])
    pos = obj.get("position_lcs_m") or obj.get("center_lcs_m")
    if isinstance(pos, list) and len(pos) >= 2 and finite(pos[0]) and finite(pos[1]):
        return lcs_to_ego(pos, frame)
    if finite(obj.get("signed_longitudinal_m")) and finite(obj.get("signed_lateral_m")):
        return float(obj["signed_longitudinal_m"]), float(obj["signed_lateral_m"])
    return None


def round3(value: float | None) -> float | None:
    return round(float(value), 3) if value is not None else None


def find_one(root: Path, rel: str, pattern: str) -> Path:
    matches = sorted((root / rel).glob(pattern))
    if len(matches) != 1:
        raise RuntimeError(f"expected one match for {rel}/{pattern}, found {len(matches)}")
    return matches[0]


def extract_model_input(request: dict[str, Any]) -> dict[str, Any]:
    content = request["messages"][1]["content"]
    text = next(item["text"] for item in content if item.get("type") == "text")
    match = re.search(r"Model input JSON:\n(\{.*\})", text, re.S)
    if not match:
        raise RuntimeError("Model input JSON block not found")
    return json.loads(match.group(1))


def sanitize_request(request: dict[str, Any]) -> dict[str, Any]:
    sanitized = copy.deepcopy(request)
    for message in sanitized.get("messages", []):
        content = message.get("content")
        if not isinstance(content, list):
            continue
        image_index = 0
        for item in content:
            if item.get("type") == "image_url":
                image_index += 1
                item["image_url"]["url"] = f"<base64 image omitted: selected_bev_{image_index}>"
    return sanitized


def decision_from_raw(raw: dict[str, Any]) -> dict[str, Any]:
    text = raw["response"]["choices"][0]["message"]["content"]
    return json.loads(text)


def payload_pedestrian_lookup(model_input: dict[str, Any]) -> dict[tuple[int, str], dict[str, Any]]:
    out = {}
    for row in model_input.get("pedestrian_measurements", []):
        for ped in row.get("pedestrians", []):
            out[(int(row["frame"]), str(ped["object_id"]))] = ped
    return out


def object_rows(
    frames_by_index: dict[int, dict[str, Any]],
    frame_indices: list[int],
    target_ids: list[str],
    payload_lookup: dict[tuple[int, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for idx in frame_indices:
        frame = frames_by_index[idx]
        ego = frame.get("ego") or {}
        objects = {object_id(obj): obj for obj in frame.get("objects", [])}
        for ped_id in target_ids:
            obj = objects.get(ped_id)
            payload = payload_lookup.get((idx, ped_id))
            if obj is None and payload is None:
                continue
            stored = (obj or {}).get("position_ego_m") or {}
            recomputed = None
            pipeline_value = None
            if obj is not None:
                pos = obj.get("position_lcs_m")
                if isinstance(pos, list) and len(pos) >= 2:
                    recomputed = lcs_to_ego(pos, frame)
                pipeline_value = object_ego_xy_like_pipeline(obj, frame)
            stored_pair = (
                stored.get("longitudinal_m", stored.get("longitudinal")),
                stored.get("lateral_m", stored.get("lateral")),
            )
            row = {
                "frame": idx,
                "time_s": frame.get("time_since_start_s"),
                "ped_id": ped_id,
                "raw_canonical_object_id": object_id(obj) if obj else None,
                "class": object_class(obj) if obj else None,
                "position_lcs_m": (obj or {}).get("position_lcs_m"),
                "ego_position_lcs_m": ego.get("position_lcs_m"),
                "ego_heading_lcs_rad": ego.get("heading_lcs_rad"),
                "stored_position_ego_m": stored if obj else None,
                "stored_ego_lon_lat": [round3(stored_pair[0]), round3(stored_pair[1])]
                if finite(stored_pair[0]) and finite(stored_pair[1])
                else None,
                "recomputed_lon_lat": [round3(recomputed[0]), round3(recomputed[1])] if recomputed else None,
                "pipeline_object_ego_xy_lon_lat": [round3(pipeline_value[0]), round3(pipeline_value[1])]
                if pipeline_value
                else None,
                "payload_lon_lat": [
                    payload.get("longitudinal_m"),
                    payload.get("lateral_m"),
                ]
                if payload
                else None,
                "flags": [],
            }
            if row["stored_ego_lon_lat"] and row["recomputed_lon_lat"]:
                if any(abs(a - b) > 0.015 for a, b in zip(row["stored_ego_lon_lat"], row["recomputed_lon_lat"])):
                    row["flags"].append("stored_vs_recomputed_disagreement")
            if row["payload_lon_lat"] and row["pipeline_object_ego_xy_lon_lat"]:
                if any(abs(float(a) - float(b)) > 0.015 for a, b in zip(row["payload_lon_lat"], row["pipeline_object_ego_xy_lon_lat"])):
                    row["flags"].append("payload_vs_pipeline_disagreement")
            if obj is None:
                row["flags"].append("target_not_present_in_frame")
            if payload is None:
                row["flags"].append("target_not_serialized_in_payload_for_frame")
            rows.append(row)
    return rows


def dense_pedestrian_trajectories(
    frames_by_index: dict[int, dict[str, Any]],
    start: int,
    end: int,
    target_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    trajectories = {ped_id: [] for ped_id in target_ids}
    for idx in range(start, end + 1):
        frame = frames_by_index.get(idx)
        if frame is None:
            continue
        objects = {object_id(obj): obj for obj in frame.get("objects", [])}
        for ped_id in target_ids:
            obj = objects.get(ped_id)
            if obj is None:
                continue
            xy = object_ego_xy_like_pipeline(obj, frame)
            if xy is None:
                continue
            trajectories[ped_id].append(
                {
                    "frame": idx,
                    "time_s": frame.get("time_since_start_s"),
                    "longitudinal_m": round3(xy[0]),
                    "lateral_m": round3(xy[1]),
                }
            )
    return trajectories


def dense_ego_trajectory(
    frames_by_index: dict[int, dict[str, Any]],
    start: int,
    end: int,
) -> list[dict[str, Any]]:
    rows = []
    for idx in range(start, end + 1):
        frame = frames_by_index.get(idx)
        if frame is None:
            continue
        ego = frame.get("ego") or {}
        rows.append(
            {
                "frame": idx,
                "time_s": frame.get("time_since_start_s"),
                "ego_speed_mps": round3(ego.get("speed_mps")) if finite(ego.get("speed_mps")) else None,
                "ego_position_lcs": ego.get("position_lcs_m"),
                "ego_heading": ego.get("heading_lcs_rad"),
            }
        )
    return rows


def speed_stats(dense: list[dict[str, Any]], raw_start: int, raw_end: int) -> dict[str, Any]:
    def speeds(lo: int, hi: int) -> list[float]:
        return [float(r["ego_speed_mps"]) for r in dense if lo <= r["frame"] <= hi and r["ego_speed_mps"] is not None]

    all_s = [float(r["ego_speed_mps"]) for r in dense if r["ego_speed_mps"] is not None]
    before = speeds(min(r["frame"] for r in dense), raw_start - 1)
    during = speeds(raw_start, raw_end)
    after = speeds(raw_end + 1, max(r["frame"] for r in dense))
    return {
        "minimum_speed_mps": min(all_s) if all_s else None,
        "speed_before_interaction_mps": {"first": before[0], "last": before[-1], "min": min(before), "max": max(before)} if before else None,
        "speed_during_interaction_mps": {"first": during[0], "last": during[-1], "min": min(during), "max": max(during)} if during else None,
        "speed_after_interaction_mps": {"first": after[0], "last": after[-1], "min": min(after), "max": max(after)} if after else None,
    }


def selected_vs_dense_ego(dense: list[dict[str, Any]], payload_ego: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by = {int(r["frame"]): r for r in dense}
    rows = []
    for item in payload_ego:
        frame = int(item["frame"])
        actual = by.get(frame, {})
        rows.append(
            {
                "frame": frame,
                "dense_speed_mps": actual.get("ego_speed_mps"),
                "payload_speed_mps": item.get("speed_mps"),
                "agrees": actual.get("ego_speed_mps") == item.get("speed_mps"),
            }
        )
    return rows


def screen_point(lon: float, lat: float) -> dict[str, float]:
    width = height = 768
    left = right = (45.0 + 45.0) / 2.0
    back = forward = (25.0 + 70.0) / 2.0
    return {
        "x_px": round(width / 2.0 - lat * (width / (left + right)), 1),
        "y_px": round(height / 2.0 - lon * (height / (back + forward)), 1),
    }


def bev_coordinate_checks(
    model_input: dict[str, Any],
    bev_paths: list[str],
    frames_by_index: dict[int, dict[str, Any]],
    target_ids: list[str],
) -> list[dict[str, Any]]:
    path_by_frame = {}
    for p in bev_paths:
        m = re.search(r"_frame_(\d+)\.png$", p)
        if m:
            path_by_frame[int(m.group(1))] = p
    rows = []
    for row in model_input["pedestrian_measurements"]:
        frame = int(row["frame"])
        frame_obj = frames_by_index[frame]
        orange_visible = 0
        yellow_target_visible = 0
        for obj in frame_obj.get("objects", []):
            pos = object_ego_xy_like_pipeline(obj, frame_obj)
            if pos is None:
                continue
            lon, lat = pos
            visible = -47.5 <= lon <= 47.5 and -45.0 <= lat <= 45.0
            if visible and object_class(obj).lower() == "pedestrian":
                orange_visible += 1
            if visible and object_id(obj) in target_ids:
                yellow_target_visible += 1
        for ped in row.get("pedestrians", []):
            lon = float(ped["longitudinal_m"])
            lat = float(ped["lateral_m"])
            rows.append(
                {
                    "frame": frame,
                    "png": path_by_frame.get(frame),
                    "ped_id": ped["object_id"],
                    "payload_lon_lat": [lon, lat],
                    "expected_pixel_center": screen_point(lon, lat),
                    "render_mapping": "x = center - lateral * scale_x; y = center - longitudinal * scale_y; positive lateral appears left, positive longitudinal appears up/ahead",
                    "visible_in_bev_extent": -47.5 <= lon <= 47.5 and -45.0 <= lat <= 45.0,
                    "yellow_target_outline_expected": True,
                    "visible_orange_pedestrian_count": orange_visible,
                    "visible_target_pedestrian_count": yellow_target_visible,
                    "assessment": "consistent: renderer uses the same ego transform and centered extent; no sign or axis swap found from code and visual contact sheet",
                }
            )
    return rows


def trajectory_observations(trajectories: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    out = {}
    for ped_id, rows in trajectories.items():
        if not rows:
            out[ped_id] = {"summary": "not present in dense interval"}
            continue
        lats = [r["lateral_m"] for r in rows]
        lons = [r["longitudinal_m"] for r in rows]
        out[ped_id] = {
            "first_lon_lat": [rows[0]["longitudinal_m"], rows[0]["lateral_m"]],
            "last_lon_lat": [rows[-1]["longitudinal_m"], rows[-1]["lateral_m"]],
            "min_abs_lateral_m": min(abs(v) for v in lats),
            "lateral_sign_change": min(lats) <= 0 <= max(lats),
            "ever_ahead": any(v > 0 for v in lons),
            "ever_near_center_abs_lat_le_1m": any(abs(v) <= 1.0 for v in lats),
            "frame_of_closest_lateral": min(rows, key=lambda r: abs(r["lateral_m"])),
        }
    return out


def build_timeline(
    candidate: dict[str, Any],
    dense_ego: list[dict[str, Any]],
    trajectories: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    meta = candidate["metadata"]
    raw_start = int(meta["raw_trigger_start_frame"])
    raw_end = int(meta["raw_trigger_end_frame"])
    selected = candidate["selected_frame_indices"]
    closest = []
    for ped_id, rows in trajectories.items():
        for row in rows:
            if row["longitudinal_m"] is not None and row["longitudinal_m"] > 0:
                closest.append((abs(row["lateral_m"]), ped_id, row))
    closest_row = min(closest, default=None, key=lambda x: x[0])
    stopped = [r for r in dense_ego if r["ego_speed_mps"] is not None and r["ego_speed_mps"] <= 1.0]
    slow = [r for r in dense_ego if r["ego_speed_mps"] is not None and r["ego_speed_mps"] <= 2.0]
    return [
        {"label": "context start", "frame": candidate["start_frame"]},
        {"label": "pre selected", "frame": selected[0]},
        {"label": "raw trigger start", "frame": raw_start},
        {"label": "1/3 selected", "frame": selected[2]},
        {"label": "2/3 selected", "frame": selected[3]},
        {"label": "raw trigger end", "frame": raw_end},
        {"label": "post selected", "frame": selected[-1]},
        {
            "label": "actual pedestrian crossing / closest ahead approach",
            "frame": closest_row[2]["frame"] if closest_row else None,
            "ped_id": closest_row[1] if closest_row else None,
            "lon_lat": [closest_row[2]["longitudinal_m"], closest_row[2]["lateral_m"]] if closest_row else None,
        },
        {
            "label": "ego deceleration / slow interval in dense report",
            "frame_range": [slow[0]["frame"], slow[-1]["frame"]] if slow else None,
            "near_stop_le_1mps_range": [stopped[0]["frame"], stopped[-1]["frame"]] if stopped else None,
        },
    ]


def summarize_other_candidates(run_root: Path) -> list[dict[str, Any]]:
    out = []
    cand_dir = run_root / "candidates" / SCENARIO / RECORDING
    raw_dir = run_root / "raw_responses" / SCENARIO
    for cpath in sorted(cand_dir.glob("*.json")):
        candidate = load_json(cpath)["candidate"]
        cid = candidate["candidate_id"]
        raw_path = sorted(raw_dir.glob(f"{cid}_*.json"))[0]
        decision = decision_from_raw(load_json(raw_path))
        out.append(
            {
                "candidate_id": cid,
                "context_frames": [candidate["start_frame"], candidate["end_frame"]],
                "raw_trigger_frames": [
                    candidate["metadata"].get("raw_trigger_start_frame"),
                    candidate["metadata"].get("raw_trigger_end_frame"),
                ],
                "selected_frame_indices": candidate.get("selected_frame_indices"),
                "target_pedestrian_ids": candidate.get("primary_object_ids"),
                "decision": decision.get("decision"),
                "reason": decision.get("reason"),
                "brief_visual_note": "see BEV contact sheet; strongest visible crossing/ego-response case selected for detail"
                if CASE_SUFFIX in cid
                else "briefly inspected in contact sheet; less visually obvious than scene_000528_000597",
            }
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--canonical", required=True, type=Path)
    parser.add_argument("--output", default="waiting_for_pedestrian_forensic_report.json")
    args = parser.parse_args()

    run_root = args.run_root
    frames = load_json(args.canonical)["frames"]
    frames_by_index = {frame_index(f): f for f in frames}

    cid = f"{RECORDING}_{SCENARIO}_{CASE_SUFFIX}"
    candidate_path = find_one(run_root, f"candidates/{SCENARIO}/{RECORDING}", f"{cid}.json")
    request_path = find_one(run_root, f"request_payloads/{SCENARIO}", f"{cid}_*.json")
    raw_path = find_one(run_root, f"raw_responses/{SCENARIO}", f"{cid}_*.json")
    candidate = load_json(candidate_path)["candidate"]
    request = load_json(request_path)
    raw = load_json(raw_path)
    model_input = extract_model_input(request)
    qwen_output = decision_from_raw(raw)
    payload_lookup = payload_pedestrian_lookup(model_input)

    selected = [int(v) for v in candidate["selected_frame_indices"]]
    raw_start = int(candidate["metadata"]["raw_trigger_start_frame"])
    raw_end = int(candidate["metadata"]["raw_trigger_end_frame"])
    dense_start = max(min(frames_by_index), raw_start - 10)
    dense_end = min(max(frames_by_index), raw_end + 10)
    trajectories = dense_pedestrian_trajectories(frames_by_index, dense_start, dense_end, TARGET_IDS)
    dense_ego = dense_ego_trajectory(frames_by_index, dense_start, dense_end)

    exact_model_facing_json = {
        key: model_input.get(key)
        for key in (
            "target_pedestrian_ids",
            "bev_frame_indices",
            "coordinate_convention",
            "ego_measurements",
            "pedestrian_measurements",
            "evaluation_mode",
        )
    }
    report = {
        "run_root": str(run_root),
        "case_selection": {
            "rejected_candidates_inspected": summarize_other_candidates(run_root),
            "selected_case_reason": "Most obvious rejected visual case in the seven-candidate BEV contact sheet: scene_000528_000597 shows target pedestrian points near/crossing the ego-forward road area while ego speed is low and decreasing.",
        },
        "candidate_identity": {
            "candidate_id": cid,
            "context_start_frame": candidate["start_frame"],
            "context_end_frame": candidate["end_frame"],
            "raw_trigger_start_frame": raw_start,
            "raw_trigger_end_frame": raw_end,
            "selected_bev_frame_indices": selected,
            "candidate_pedestrian_ids": candidate["primary_object_ids"],
            "source_candidate_ids": candidate["metadata"].get("source_candidate_ids"),
        },
        "actual_vlm_request": {
            "request_path": str(request_path),
            "sanitized_request_json_excluding_base64": sanitize_request(request),
            "exact_model_facing_json_subset": exact_model_facing_json,
            "png_by_selected_frame": [
                {"frame": frame, "png": path}
                for frame, path in zip(selected, candidate["bev_paths"])
            ],
            "latest_additions_present_in_actual_request": {
                key: key in model_input
                for key in (
                    "target_pedestrian_ids",
                    "bev_frame_indices",
                    "coordinate_convention",
                    "ego_measurements",
                    "pedestrian_measurements",
                    "evaluation_mode",
                )
            },
        },
        "pedestrian_tracking_validation": {
            "object_ego_xy_field_convention": "The run's source path checks position_ego_m.longitudinal_m/lateral_m first, then position_ego_m.longitudinal/lateral, then recomputes from position_lcs_m. This canonical file uses longitudinal/lateral without _m, and those values match recomputation.",
            "selected_frame_table": object_rows(frames_by_index, selected, TARGET_IDS, payload_lookup),
            "dense_interval_frames": [dense_start, dense_end],
            "dense_trajectories": trajectories,
            "trajectory_observations": trajectory_observations(trajectories),
        },
        "ego_motion_validation": {
            "dense_interval_frames": [dense_start, dense_end],
            "dense_ego_trajectory": dense_ego,
            "speed_summary": speed_stats(dense_ego, raw_start, raw_end),
            "selected_payload_vs_dense_speed": selected_vs_dense_ego(dense_ego, model_input["ego_measurements"]),
            "frame_selection_assessment": "Selected frames include low/decreasing speed during the raw trigger, but sparse sampling misses the deepest near-stop portion around frames 585-595; there are no post-597 frames available to show later recovery.",
        },
        "bev_coordinate_consistency": {
            "renderer_mapping_from_code": "render_revised_bev_png uses the same LCS-to-ego transform, then screen(longitudinal,lateral) = (center_x - lateral*scale_x, center_y - longitudinal*scale_y). Positive longitudinal is up/ahead; positive lateral is image-left.",
            "selected_bev_checks": bev_coordinate_checks(model_input, candidate["bev_paths"], frames_by_index, TARGET_IDS),
            "assessment": {
                "lateral_sign_reversed": False,
                "longitudinal_lateral_axes_swapped": False,
                "ego_heading_transform_disagreement": False,
                "wrong_object_highlighted": False,
                "candidate_yellow_outline_missing": False,
                "candidate_pedestrian_outside_selected_bev": False,
                "multiple_orange_pedestrians_ambiguous": True,
                "note": "The geometry and renderer are consistent, but there are multiple orange pedestrians and the BEV does not print object IDs, so identity attribution is visually ambiguous.",
            },
        },
        "ego_path_visibility": {
            "ego_lane_or_drivable_corridor_visibly_reconstructed": False,
            "lane_boundaries_visible_around_ego": True,
            "centerline_or_ego_future_trajectory_visible": False,
            "pedestrian_visibly_inside_that_corridor": "ambiguous: lane/road edges and crosswalk/roadmark geometry are visible, but no explicit ego path corridor is drawn.",
            "human_unfamiliar_with_renderer_can_tell_exact_ego_path_region": False,
            "diagnosis": "The BEV shows road boundaries/lane lines, but not an explicit ego lane, drivable corridor, centerline, or future trajectory. The model must infer ego's expected path from sparse map lines and the ego heading marker.",
        },
        "frame_selection_quality": {
            "timeline": build_timeline(candidate, dense_ego, trajectories),
            "captures_before_crossing": "partial: frame 541/542 are just before/during raw trigger but not before the earlier deceleration onset",
            "captures_entering_ego_path": "partial/ambiguous: selected frames show target 541/544 ahead at negative lateral from 570 onward and target 437 approaching center only after it is behind",
            "captures_inside_or_crossing_ego_path": "weak for ahead pedestrians: no selected target has longitudinal > 0 and lateral near 0; target 437 reaches lateral 0.053 at frame 597 but is 18.705 m behind",
            "captures_after_crossing": "limited: frame 597 is the recording end, no later post-context exists",
            "captures_ego_response": "yes for low/decreasing speed, but misses the true near-stop minimum around frame 590",
            "important_frames_missed": [
                "deepest near-stop interval around frames 585-595, including dense minimum speed near frame 590",
                "any later recovery/post-crossing ego response after frame 597 is unavailable",
                "if the visual positive is target 437, selected frames miss it passing near lateral 0 while still ahead; by frame 597 it is behind",
            ],
        },
        "exact_qwen_output": {
            "raw_response_path": str(raw_path),
            "decision_json": qwen_output,
            "claim_comparison": [
                {
                    "qwen_claim": "Pedestrian not entering or crossing ego's path",
                    "evidence": "Payload coordinates show target 437 lateral 6.378 -> 0.053 but longitudinal -1.439 -> -18.705, so it approaches center after/while behind ego. Targets 541/544 remain ahead but lateral stays about -9 to -6 m. The BEV road/path corridor is visually ambiguous.",
                    "conclusion": "ambiguous/supported by serialized coordinates, visually contestable from BEV because no explicit ego corridor is drawn",
                },
                {
                    "qwen_claim": "ego slowing",
                    "evidence": "Dense ego speed in frames 532-597 falls from 7.609 m/s to 0.86 m/s; selected payload speeds fall 3.403 -> 0.86 m/s.",
                    "conclusion": "supported",
                },
                {
                    "qwen_claim": "no clear pedestrian interaction",
                    "evidence": "Temporal overlap exists between low/decreasing ego speed and target pedestrians near the ego road area, but target IDs split the physical situation into several tracks and no explicit path corridor/object IDs are printed in BEV.",
                    "conclusion": "ambiguous; likely driven by path/identity ambiguity rather than wrong numeric speed evidence",
                },
            ],
        },
        "root_cause_ranking": [
            {"cause": "A. wrong pedestrian coordinates", "likelihood": "low", "reason": "Stored ego lon/lat match recomputed LCS-to-ego and payload values for selected frames."},
            {"cause": "B. payload/BEV coordinate mismatch", "likelihood": "low", "reason": "Renderer and payload use the same ego transform and sign convention; expected pixel positions match the visual layout."},
            {"cause": "C. selected frames miss the crossing", "likelihood": "medium", "reason": "For the strongest crossing-looking target, 437 approaches lateral 0 only once it is behind ego; ahead targets stay laterally far in serialized selected frames."},
            {"cause": "D. selected frames miss ego deceleration", "likelihood": "medium", "reason": "Payload captures slowing, but sparse frames miss the deepest near-stop interval: dense speed reaches 0.225 m/s near frame 590 while selected frames jump from 579 to 597."},
            {"cause": "E. ego path is visually ambiguous in BEV", "likelihood": "high", "reason": "No explicit ego corridor, centerline, or future trajectory is drawn; the model must infer path from lane/road boundary geometry."},
            {"cause": "F. target pedestrian identity is visually ambiguous", "likelihood": "high", "reason": "Multiple orange pedestrians and four yellow-highlighted target IDs appear, but the BEV has no object ID labels."},
            {"cause": "G. prompt interpretation problem", "likelihood": "medium", "reason": "Prompt allows low speed after prior braking, but Qwen still demanded clearer path interaction; likely coupled to visual ambiguity."},
            {"cause": "H. Qwen model limitation", "likelihood": "medium", "reason": "The model may be unable to integrate sparse geometry, multiple highlighted pedestrians, and neutral numeric tracks reliably."},
            {"cause": "I. candidate itself is not actually positive", "likelihood": "low-to-medium", "reason": "The scene is visually plausible as waiting for pedestrians, but serialized target tracks do not show a clean ahead-of-ego lateral center crossing in selected frames."},
        ],
    }

    output_path = run_root / args.output
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    print(f"Forensic report written: {output_path}")
    print()
    print("Selected rejected case:", cid)
    print("Request path:", request_path)
    print("Raw response path:", raw_path)
    print("Selected BEV frames:", selected)
    print("Target pedestrians:", ", ".join(TARGET_IDS))
    print()
    print("Exact model-facing JSON subset:")
    print(json.dumps(exact_model_facing_json, indent=2, sort_keys=True))
    print()
    print("Dense pedestrian trajectory observations:")
    print(json.dumps(report["pedestrian_tracking_validation"]["trajectory_observations"], indent=2, sort_keys=True))
    print()
    print("Dense ego speed summary:")
    print(json.dumps(report["ego_motion_validation"]["speed_summary"], indent=2, sort_keys=True))
    print()
    print("Qwen output:")
    print(json.dumps(qwen_output, indent=2, sort_keys=True))
    print()
    print("Root-cause ranking:")
    for item in report["root_cause_ranking"]:
        print(f"- {item['cause']}: {item['likelihood']} - {item['reason']}")


if __name__ == "__main__":
    main()
