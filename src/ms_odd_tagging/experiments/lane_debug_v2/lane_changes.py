"""Run duplicated production lane-change detector from lane-debug v2 evidence."""
from __future__ import annotations
from typing import Any
from ms_odd_tagging.features.ego_motion import extract_ego_motion_features
from .lane_changes_baseline import LaneChangeDetector


def run_lane_change_debug(recording: dict[str,Any], following_result: dict[str,Any], config: dict[str,Any]) -> dict[str,Any]:
    frames=recording.get("frames",[])
    features=extract_ego_motion_features(frames)
    source_by_index={f.get("frame_index"):f for f in frames}
    context={}
    for item in following_result.get("frames",[]):
        fi=item["frame_index"]
        source=source_by_index.get(fi,{})
        topology={k:v for k,v in source.items() if k.startswith("topology_") or k in {
            "active_topology_subtype","active_topology_component_id","active_is_intersection",
            "is_intersection_component","ego_inside_topology_polygon","distance_to_topology_polygon_m",
            "component_geometry_confidence"}}
        context[fi]={
            **topology,
            "logical_lane_id":(item.get("ego_lane") or {}).get("logical_lane_id"),
            "physical_lane_id":(item.get("ego_lane") or {}).get("lane_id"),
            "left_logical_lane_id":(item.get("left_lane") or {}).get("logical_lane_id"),
            "right_logical_lane_id":(item.get("right_lane") or {}).get("logical_lane_id"),
            "lane_assignment_method":(item.get("ego_lane") or {}).get("method"),
            "lane_assignment_confidence":(item.get("ego_lane") or {}).get("confidence"),
        }
    detector=LaneChangeDetector()
    events=detector.detect(frames,features,config,frame_context=context)
    return {
        "schema_version":"lane-debug-v2-lane-change-tags-v1",
        "recording_id":recording.get("recording_id"),
        "events":[event.to_dict() for event in events],
        "frame_evaluations":getattr(detector,"debug_evaluations",[]),
    }
