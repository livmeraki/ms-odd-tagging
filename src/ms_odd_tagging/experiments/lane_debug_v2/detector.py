"""Experimental following-lane detector with continuous-track lane state.

The duplicated segment detector is retained as a baseline/evidence source. A
continuous lane-track layer then promotes accepted segment continuations into
persistent tracks and becomes the primary ego logical-lane/adjacency context.
Production files are not imported or modified.
"""
from __future__ import annotations
import copy, math
from typing import Any
from .detector_baseline import run_following_lane as run_baseline
from .lane_geometry import nearest_heading, polyline_distance, wrap_angle
from .object_motion import build_object_motion_evidence
from .continuous_tracks import build_continuous_tracks, adjacent_tracks
from .strict_track_assignment import assign_point_to_track_strict

DEFAULT_DEBUG = {
    "object_motion_history_frames": 3,
    "object_motion_minimum_displacement_m": 0.5,
    "lead_direction_filter_mode": "diagnostic",
    "maximum_lead_direction_difference_deg": None,
    "reject_ambiguous_stationary_lead": False,
    "continuous_track_assignment_enabled": True,
    "continuous_track_maximum_heading_difference_deg": 60.0,
    "continuous_track_outside_tolerance_m": 1.0,
    "continuous_track_adjacent_heading_difference_deg": 20.0,
    "continuous_track_adjacent_minimum_lateral_m": 1.5,
    "continuous_track_adjacent_maximum_lateral_m": 8.0,
    "continuous_track_adjacent_local_window_m": 20.0,
}

def _finite(v: Any) -> bool:
    return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)

def _lead_base_candidate(obj: dict[str,Any], frame: dict[str,Any], settings: dict[str,Any]) -> bool:
    ego_route = (frame.get("ego_lane") or {}).get("logical_lane_id")
    return bool(
        ego_route and obj.get("logical_lane_id") == ego_route
        and obj.get("annotation_type") in settings.get("lead_annotation_types", ["dynamic"])
        and obj.get("class") in {"car","truck","truck_head","bus","trailer","special_vehicle"}
        and _finite(obj.get("longitudinal_m"))
        and 0.0 < float(obj["longitudinal_m"]) <= float(settings.get("maximum_lead_distance_m",80.0))
    )

def _nearest_member(track: dict[str,Any] | None, point: tuple[float,float], lane_by_id: dict[str,dict[str,Any]]) -> str | None:
    if not track:
        return None
    candidates=[]
    for lane_id in track.get("member_lane_ids",[]):
        lane=lane_by_id.get(str(lane_id))
        center=(lane or {}).get("centerline_lcs_m") or []
        if len(center)>=2:
            candidates.append((polyline_distance(point,center),str(lane_id)))
    return min(candidates)[1] if candidates else None

def _apply_continuous_track_state(recording: dict[str,Any], result: dict[str,Any], settings: dict[str,Any]) -> None:
    tracks, member_to_track, connection_debug = build_continuous_tracks(result.get("lane_geometry",[]), recording)
    result["continuous_lane_tracks"]=tracks
    result["continuous_track_member_map"]=member_to_track
    result["continuous_track_connection_debug"]=connection_debug
    if not settings.get("continuous_track_assignment_enabled",True):
        return
    track_by_id={str(t["track_id"]):t for t in tracks}
    lane_by_id={str(l["lane_id"]):l for l in result.get("lane_geometry",[])}
    source_by_frame={f.get("frame_index"):f for f in recording.get("frames",[])}
    previous_track_id=None
    for frame in result.get("frames",[]):
        source=source_by_frame.get(frame.get("frame_index"),{})
        ego=(source.get("ego") or {})
        p=ego.get("position_lcs_m") or []
        heading=ego.get("heading_lcs_rad")
        frame["segment_ego_lane"]=copy.deepcopy(frame.get("ego_lane"))
        frame["segment_left_lane"]=copy.deepcopy(frame.get("left_lane"))
        frame["segment_right_lane"]=copy.deepcopy(frame.get("right_lane"))
        if len(p)<2 or not all(_finite(x) for x in p[:2]) or not _finite(heading):
            frame["continuous_ego_track"]={"track_id":None,"method":"invalid_ego_pose","confidence":"unknown"}
            frame["continuous_adjacency"]={"left":{"track_id":None},"right":{"track_id":None},"candidates":[]}
            frame["ego_lane"]={"lane_id":None,"logical_lane_id":None,"method":"invalid_ego_pose","confidence":"unknown"}
            continue
        point=(float(p[0]),float(p[1]))
        assignment=assign_point_to_track_strict(
            point,float(heading),tracks,previous_track_id=previous_track_id,
            maximum_heading_difference_deg=float(settings["continuous_track_maximum_heading_difference_deg"]),
            outside_tolerance_m=float(settings["continuous_track_outside_tolerance_m"]),
        )
        frame["continuous_ego_track"]=assignment
        track_id=assignment.get("track_id")
        if track_id:
            previous_track_id=str(track_id)
            track=track_by_id.get(str(track_id))
            physical=assignment.get("matched_lane_id") or _nearest_member(track,point,lane_by_id)
            frame["ego_lane"]={
                "lane_id":physical,
                "logical_lane_id":track_id,
                "continuous_track_id":track_id,
                "continuous_track_member_lane_ids":assignment.get("member_lane_ids",[]),
                "method":assignment.get("method"),
                "confidence":assignment.get("confidence"),
                "inside_polygon":assignment.get("inside_polygon"),
                "polygon_distance_m":assignment.get("polygon_distance_m"),
                "outside_tolerance_m":assignment.get("outside_tolerance_m"),
                "matched_piece_kind":assignment.get("matched_piece_kind"),
                "center_distance_m":assignment.get("center_distance_m"),
                "heading_difference_deg":assignment.get("heading_difference_deg"),
            }
        else:
            # Do not retain or promote a segment-level left/right candidate as ego
            # merely because it is near the merged track centerline. The primary
            # ego lane is unknown until the ego center is inside an actual lane
            # polygon (or within the explicit 1 m tolerance).
            frame["ego_lane"]={
                "lane_id":None,
                "logical_lane_id":None,
                "continuous_track_id":None,
                "method":assignment.get("method","no_track_contains_ego_center_within_tolerance"),
                "confidence":"unknown",
                "outside_tolerance_m":assignment.get("outside_tolerance_m"),
                "candidates":assignment.get("candidates",[]),
                "rejected_candidates":assignment.get("rejected_candidates",[]),
            }
        adjacency=adjacent_tracks(
            track_id,point,tracks,
            maximum_heading_difference_deg=float(settings["continuous_track_adjacent_heading_difference_deg"]),
            minimum_lateral_m=float(settings["continuous_track_adjacent_minimum_lateral_m"]),
            maximum_lateral_m=float(settings["continuous_track_adjacent_maximum_lateral_m"]),
            local_window_m=float(settings["continuous_track_adjacent_local_window_m"]),
        )
        frame["continuous_adjacency"]=adjacency
        for side,key in (("left","left_lane"),("right","right_lane")):
            selected=adjacency.get(side) or {}
            adjacent_track_id=selected.get("track_id")
            adjacent_track=track_by_id.get(str(adjacent_track_id)) if adjacent_track_id else None
            physical=_nearest_member(adjacent_track,point,lane_by_id) if adjacent_track else None
            frame[key]={
                "lane_id":physical,
                "logical_lane_id":adjacent_track_id,
                "continuous_track_id":adjacent_track_id,
                "method":selected.get("method","not_found"),
                "confidence":selected.get("confidence","unknown"),
                "lateral_offset_m":selected.get("lateral_offset_m"),
                "heading_difference_deg":selected.get("heading_difference_deg"),
            }
        for obj in frame.get("objects",[]):
            lane_id=obj.get("lane_id")
            if lane_id is not None and str(lane_id) in member_to_track:
                obj["segment_logical_lane_id"]=obj.get("logical_lane_id")
                obj["logical_lane_id"]=member_to_track[str(lane_id)]
                obj["continuous_track_id"]=member_to_track[str(lane_id)]


def run_lane_debug_v2(recording: dict[str,Any], config: dict[str,Any] | None=None) -> dict[str,Any]:
    settings={**DEFAULT_DEBUG, **(config or {})}
    result=copy.deepcopy(run_baseline(recording, config))
    _apply_continuous_track_state(recording,result,settings)
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
            if diff is None: compatibility="ambiguous"
            elif threshold is None: compatibility="unthresholded_observation"
            elif diff <= float(threshold): compatibility="same_direction"
            elif diff >= 180.0-float(threshold): compatibility="opposite_direction"
            else: compatibility="crossing_or_diverging"
            obj["lead_direction_compatibility"]=compatibility
            obj["lead_base_candidate"]=_lead_base_candidate(obj,frame,result.get("config",{}))
            eligible=obj["lead_base_candidate"]
            rejection=None
            mode=settings.get("lead_direction_filter_mode","diagnostic")
            if eligible and mode=="enforce":
                if threshold is None:
                    eligible=False; rejection="direction_threshold_not_configured"
                elif compatibility!="same_direction":
                    if not (compatibility=="ambiguous" and not settings.get("reject_ambiguous_stationary_lead",False)):
                        eligible=False; rejection="direction_mismatch_or_ambiguous"
            obj["lead_direction_eligible"]=eligible
            obj["lead_rejection_reason"]=rejection
            if eligible: candidates.append(obj)
        candidates.sort(key=lambda x: float(x["longitudinal_m"]))
        frame["lead_candidates_debug"]=[{
            "object_id":o.get("object_id"),"longitudinal_m":o.get("longitudinal_m"),
            "direction_difference_deg":o.get("lead_direction_difference_deg"),
            "direction_compatibility":o.get("lead_direction_compatibility"),
            "eligible":o.get("lead_direction_eligible"),"rejection_reason":o.get("lead_rejection_reason")}
            for o in frame.get("objects",[]) if o.get("lead_base_candidate")]
        if settings.get("lead_direction_filter_mode")=="enforce":
            frame["lead"]=candidates[0] if candidates else None
            frame["lead_candidate_count"]=len(candidates)
            if frame.get("state") not in {"unknown","not_applicable"}:
                if frame["lead"]:
                    frame["state"]="following_lane_with_lead"; frame["reason"]="direction_compatible_lead_in_ego_track"
                else:
                    frame["state"]="following_lane_without_lead"; frame["reason"]="no_direction_compatible_lead_in_ego_track"
    result["schema_version"]="lane-debug-v2-continuous-track-frame-tags-v1"
    result["debug_config"]=settings
    result["lead_direction_angle_samples_deg"]=[round(v,2) for v in angle_samples]
    result["lead_direction_distribution"]={
        "sample_count":len(angle_samples),
        "minimum_deg":None if not angle_samples else round(min(angle_samples),2),
        "maximum_deg":None if not angle_samples else round(max(angle_samples),2),
        "note":"Inspect this distribution before setting maximum_lead_direction_difference_deg; diagnostic mode does not alter lead selection."
    }
    return result