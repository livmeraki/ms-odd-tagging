"""Construct supplemental lane corridors directly from raw LD boundary lines.

Canonical lane entities remain preferred. This module finds sustained parallel
pairs of raw lane-lines/road-boundaries with plausible lane width and creates
static supplemental tracks only when the same physical boundary pair is not
already represented by a valid reconstructed canonical lane.
"""
from __future__ import annotations

import math
from typing import Any

from .lane_geometry import wrap_angle


def _dist(a, b) -> float:
    return math.hypot(float(a[0])-float(b[0]), float(a[1])-float(b[1]))


def _cum(line: list[list[float]]) -> list[float]:
    out=[0.0]
    for a,b in zip(line,line[1:]):
        out.append(out[-1]+_dist(a,b))
    return out


def _sample(line: list[list[float]], spacing_m: float) -> list[tuple[float,list[float],float]]:
    if len(line)<2:
        return []
    cumulative=_cum(line); total=cumulative[-1]
    if total<1.0:
        return []
    count=max(2,int(total/max(spacing_m,0.5))+1); out=[]; seg=0
    for i in range(count):
        s=total if i==count-1 else total*i/(count-1)
        while seg+2<len(cumulative) and cumulative[seg+1]<s:
            seg+=1
        a,b=line[seg],line[seg+1]; span=cumulative[seg+1]-cumulative[seg]
        t=0.0 if span<=1e-9 else (s-cumulative[seg])/span
        p=[float(a[0])+t*(float(b[0])-float(a[0])),float(a[1])+t*(float(b[1])-float(a[1]))]
        h=math.atan2(float(b[1])-float(a[1]),float(b[0])-float(a[0]))
        out.append((s,p,h))
    return out


def _project(point: list[float], line: list[list[float]]) -> tuple[float,list[float],float] | None:
    best=None
    for a,b in zip(line,line[1:]):
        ax,ay,bx,by=float(a[0]),float(a[1]),float(b[0]),float(b[1]); dx,dy=bx-ax,by-ay
        den=dx*dx+dy*dy
        if den<=1e-12: continue
        t=max(0.0,min(1.0,((float(point[0])-ax)*dx+(float(point[1])-ay)*dy)/den))
        q=[ax+t*dx,ay+t*dy]; d=_dist(point,q); h=math.atan2(dy,dx)
        if best is None or d<best[0]: best=(d,q,h)
    return best


def _raw_boundaries(recording: dict[str,Any]) -> list[dict[str,Any]]:
    store=recording.get("ld_feature_store") or {}
    lookup={str(p.get("point_id")):p.get("position_lcs_m",[])[:2] for p in store.get("points",[]) if len(p.get("position_lcs_m") or [])>=2}
    out=[]
    for collection,key,kind in (("lane_lines","line_id","lane_line"),("road_boundaries","road_boundary_id","road_boundary")):
        for feature in store.get(collection,[]):
            ids=list(feature.get("point_ids") or []) or [e.get("point_id") for e in feature.get("elements") or []]
            pts=[lookup[str(pid)] for pid in ids if str(pid) in lookup]
            if len(pts)>=2:
                out.append({"boundary_id":str(feature.get(key)),"kind":kind,"points":pts})
    return out


def build_raw_ld_lane_tracks(
    recording: dict[str,Any],
    lane_geometry: list[dict[str,Any]],
    *,
    sample_spacing_m: float=2.0,
    minimum_width_m: float=2.2,
    maximum_width_m: float=6.5,
    maximum_heading_difference_deg: float=20.0,
    minimum_overlap_m: float=8.0,
    minimum_side_consistency: float=0.85,
    maximum_width_std_m: float=1.0,
) -> tuple[list[dict[str,Any]],list[dict[str,Any]]]:
    boundaries=_raw_boundaries(recording)
    represented_pairs=set()
    for lane in lane_geometry:
        if not lane.get("assignment_valid"): continue
        left,right=lane.get("left_edge_id"),lane.get("right_edge_id")
        if left is not None and right is not None:
            represented_pairs.add(frozenset((str(left),str(right))))
    tracks=[]; debug=[]; seen_pairs=set()
    for i,a in enumerate(boundaries):
        samples=_sample(a["points"],sample_spacing_m)
        if len(samples)<2: continue
        for b in boundaries[i+1:]:
            pair=frozenset((a["boundary_id"],b["boundary_id"]))
            if pair in represented_pairs or pair in seen_pairs: continue
            accepted=[]
            for station,p,h in samples:
                proj=_project(p,b["points"])
                if proj is None: continue
                d,q,h2=proj; diff=abs(math.degrees(wrap_angle(h2-h))); diff=min(diff,abs(180.0-diff))
                nx,ny=-math.sin(h),math.cos(h); lat=(q[0]-p[0])*nx+(q[1]-p[1])*ny
                if diff<=maximum_heading_difference_deg and minimum_width_m<=abs(lat)<=maximum_width_m:
                    accepted.append((station,p,q,h,lat,diff))
            if len(accepted)<2: continue
            signs=[1 if x[4]>0 else -1 for x in accepted]; majority=1 if sum(signs)>=0 else -1
            consistent=[x for x in accepted if (1 if x[4]>0 else -1)==majority]
            consistency=len(consistent)/len(accepted)
            if consistency<minimum_side_consistency or len(consistent)<2: continue
            overlap=consistent[-1][0]-consistent[0][0]
            if overlap<minimum_overlap_m: continue
            widths=[abs(x[4]) for x in consistent]; mean=sum(widths)/len(widths); std=math.sqrt(sum((x-mean)**2 for x in widths)/len(widths))
            if std>maximum_width_std_m: continue
            # If B is left of A's forward direction, B is the left boundary.
            if majority>0:
                left=[x[2] for x in consistent]; right=[x[1] for x in consistent]; left_id=b["boundary_id"]; right_id=a["boundary_id"]
            else:
                left=[x[1] for x in consistent]; right=[x[2] for x in consistent]; left_id=a["boundary_id"]; right_id=b["boundary_id"]
            center=[[(l[0]+r[0])/2.0,(l[1]+r[1])/2.0] for l,r in zip(left,right)]
            polygon=left+list(reversed(right))
            track_id=f"raw_ld_track_{len(tracks)+1:04d}"
            track={
                "track_id":track_id,
                "logical_lane_id":track_id,
                "member_lane_ids":[],
                "centerline_lcs_m":center,
                "polygon_lcs_m":polygon,
                "median_width_m":round(sorted(widths)[len(widths)//2],3),
                "pieces":[{
                    "kind":"raw_ld_boundary_pair",
                    "polygon_lcs_m":polygon,
                    "centerline_lcs_m":center,
                    "left_boundary_lcs_m":left,
                    "right_boundary_lcs_m":right,
                    "left_boundary_id":left_id,
                    "right_boundary_id":right_id,
                }],
                "piece_count":1,
                "observed_segment_count":0,
                "inferred_gap_count":0,
                "source":"raw_ld_boundary_pair",
                "left_boundary_id":left_id,
                "right_boundary_id":right_id,
                "left_boundary_lcs_m":left,
                "right_boundary_lcs_m":right,
            }
            tracks.append(track); seen_pairs.add(pair)
            debug.append({"track_id":track_id,"left_boundary_id":left_id,"right_boundary_id":right_id,"overlap_m":round(overlap,3),"median_width_m":track["median_width_m"],"width_std_m":round(std,3),"side_consistency":round(consistency,3)})
    return tracks,debug
