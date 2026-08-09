"""Experimental following-lane detector with additive debug evidence.

This module runs the duplicated production detector first, then adds object
motion evidence and optional direction-aware lead filtering. Production files
are not imported or modified.
"""
from __future__ import annotations
import copy, math
from typing import Any
from .detector_baseline import run_following_lane as run_baseline
from .lane_geometry import nearest_heading, wrap_angle
from .object_motion import build_object_motion_evidence

DEFAULT_DEBUG = {
    "object_motion_history_frames": 3,
    "object_motion_minimum_displacement_m": 0.5,
    "lead_direction_filter_mode": "diagnostic",
    "maximum_lead_direction_difference_deg": None,
    "reject_ambiguous_stationary_lead": False,
}

def _finite(v: Any) -> bool:
    return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)

def _lead_base_candidate(obj: dict[str,Any], frame: dict[str,Any], settings: dict[str,Any]) -> bool:
    ego_route = (frame.get("ego_lane") or {}).get("logical_lane_id")
    return bool(
        ego_route and obj.get("logical_lane_id") == ego_route
        and obj.get("inside_ego_lane_area") is True
        and obj.get("annotation_type") in settings.get("lead_annotation_types", ["dynamic"])
        and obj.get("class") in {"car","truck","truck_head","bus","trailer","special_vehicle"}
        and _finite(obj.get("longitudinal_m"))
        and 0.0 < float(obj["longitudinal_m"]) <= float(settings.get("maximum_lead_distance_m",80.0))
    )

def run_lane_debug_v2(recording: dict[str,Any], config: dict[str,Any] | None=None) -> dict[str,Any]:
    settings={**DEFAULT_DEBUG, **(config or {})}
    result=copy.deepcopy(run_baseline(recording, config))
    lane_by_id={str(l["lane_id"]):l for l in result.get("lane_geometry",[])}
    motion=build_object_motion_evidence(
        recording,
        history_frames=int(settings["object_motion_history_frames"]),
        minimum_displacement_m=float(settings["object_motion_minimum_displacement_m"]),
    )
    angle_samples=[]
    for frame in result.get("frames",[]):
        fi=frame["frame_index"]
        ego_lane_id=(frame.get("ego_lane") or {}).get("lane_id")
        ego_lane=lane_by_id.get(str(ego_lane_id)) if ego_lane_id is not None else None
        candidates=[]
        for obj in frame.get("objects",[]):
            obj.update(motion.get((fi,str(obj.get("object_id"))), {
                "object_motion_heading_rad":None,"object_motion_heading_deg":None,
                "object_motion_speed_mps":None,"object_motion_source":"unavailable",
                "object_motion_status":"unavailable"}))
            lane_heading=None
            if ego_lane and obj.get("position_lcs_m"):
                lane_heading=nearest_heading(tuple(obj["position_lcs_m"][:2]), ego_lane.get("centerline_lcs_m",[]))
            motion_heading=obj.get("object_motion_heading_rad")
            diff=None
            if lane_heading is not None and motion_heading is not None:
                diff=abs(math.degrees(wrap_angle(float(motion_heading)-float(lane_heading))))
                angle_samples.append(diff)
            obj["ego_lane_heading_at_object_rad"]=lane_heading
            obj["ego_lane_heading_at_object_deg"]=None if lane_heading is None else round(math.degrees(lane_heading),2)
            obj["lead_direction_difference_deg"]=None if diff is None else round(diff,2)
            threshold=settings.get("maximum_lead_direction_difference_deg")
            if diff is None:
                compatibility="ambiguous"
            elif threshold is None:
                compatibility="unthresholded_observation"
            elif diff <= float(threshold):
                compatibility="same_direction"
            elif diff >= 180.0-float(threshold):
                compatibility="opposite_direction"
            else:
                compatibility="crossing_or_diverging"
            obj["lead_direction_compatibility"]=compatibility
            obj["lead_base_candidate"]=_lead_base_candidate(obj,frame,result.get("config",{}))
            eligible=obj["lead_base_candidate"]
            rejection=None
            mode=settings.get("lead_direction_filter_mode","diagnostic")
            if eligible and mode=="enforce":
                if threshold is None:
                    eligible=False; rejection="direction_threshold_not_configured"
                elif compatibility!="same_direction":
                    if compatibility=="ambiguous" and not settings.get("reject_ambiguous_stationary_lead",False):
                        pass
                    else:
                        eligible=False; rejection="direction_mismatch_or_ambiguous"
            obj["lead_direction_eligible"]=eligible
            obj["lead_rejection_reason"]=rejection
            if eligible:
                candidates.append(obj)
        candidates.sort(key=lambda x: float(x["longitudinal_m"]))
        frame["lead_candidates_debug"]=[{
            "object_id":o.get("object_id"),"longitudinal_m":o.get("longitudinal_m"),
            "direction_difference_deg":o.get("lead_direction_difference_deg"),
            "direction_compatibility":o.get("lead_direction_compatibility"),
            "eligible":o.get("lead_direction_eligible"),
            "rejection_reason":o.get("lead_rejection_reason")}
            for o in frame.get("objects",[]) if o.get("lead_base_candidate")]
        if settings.get("lead_direction_filter_mode")=="enforce":
            frame["lead"]=candidates[0] if candidates else None
            frame["lead_candidate_count"]=len(candidates)
            if frame.get("state") not in {"unknown","not_applicable"}:
                if frame["lead"]:
                    frame["state"]="following_lane_with_lead"
                    frame["reason"]="direction_compatible_lead_in_ego_route_lane"
                else:
                    frame["state"]="following_lane_without_lead"
                    frame["reason"]="no_direction_compatible_lead_in_ego_route_lane"
    result["schema_version"]="lane-debug-v2-frame-tags-v1"
    result["debug_config"]=settings
    result["lead_direction_angle_samples_deg"]=[round(v,2) for v in angle_samples]
    result["lead_direction_distribution"]={
        "sample_count":len(angle_samples),
        "minimum_deg":None if not angle_samples else round(min(angle_samples),2),
        "maximum_deg":None if not angle_samples else round(max(angle_samples),2),
        "note":"Inspect this distribution before setting maximum_lead_direction_difference_deg; diagnostic mode does not alter lead selection."
    }
    return result
