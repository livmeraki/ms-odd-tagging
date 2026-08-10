from ms_odd_tagging.experiments.lane_debug_v2.boundary_corridor import infer_ego_corridor_from_boundaries
from ms_odd_tagging.experiments.lane_debug_v2.canonical_track_stitch import stitch_canonical_tracks
from ms_odd_tagging.experiments.lane_debug_v2.continuous_tracks import build_continuous_tracks, assign_point_to_track, adjacent_tracks
from ms_odd_tagging.experiments.lane_debug_v2.lane_state import deterministic_candidate, direction_relation, transition_kind
from ms_odd_tagging.experiments.lane_debug_v2.object_motion import build_object_motion_evidence
from ms_odd_tagging.experiments.lane_debug_v2.strict_track_assignment import assign_point_to_track_strict
from ms_odd_tagging.experiments.lane_debug_v2.track_topology import build_track_adjacency_graph, select_topology_adjacency


def _recording(points):
    return {"frames":[{"frame_index":i,"time_since_start_s":i*0.1,"ego":{"position_lcs_m":[i,0],"heading_lcs_rad":0.0},"objects":[{"object_id":"1","position_lcs_m":p}]} for i,p in enumerate(points)]}


def _lane(lane_id,x0,x1,y,next_id=None):
    center=[[x0,y],[x1,y]]
    left=[[x0,y+1.75],[x1,y+1.75]]
    right=[[x0,y-1.75],[x1,y-1.75]]
    continuation=[]
    if next_id is not None:
        gap=[[x1,y],[x1+1,y],[x1+2,y]]
        continuation=[{
            "destination_lane_id":next_id,
            "projected_centerline_lcs_m":gap,
            "inferred_gap_polygon_lcs_m":[],
            "accepted_candidate":{"score":2.0,"gap_m":2.0,"rejection_reasons":[]},
        }]
    return {
        "lane_id":lane_id,"assignment_valid":True,"centerline_lcs_m":center,
        "left_boundary_lcs_m":left,"right_boundary_lcs_m":right,
        "left_edge_id":f"{lane_id}_L","right_edge_id":f"{lane_id}_R",
        "polygon_lcs_m":left+list(reversed(right)),"geometry_recovered":False,
        "recovery_method":None,"curvature_continuations":continuation,
    }


def _reverse_lane_geometry(lane):
    out=dict(lane)
    out["centerline_lcs_m"]=list(reversed(lane["centerline_lcs_m"]))
    out["left_boundary_lcs_m"]=list(reversed(lane["left_boundary_lcs_m"]))
    out["right_boundary_lcs_m"]=list(reversed(lane["right_boundary_lcs_m"]))
    out["polygon_lcs_m"]=out["left_boundary_lcs_m"]+list(reversed(out["right_boundary_lcs_m"]))
    return out


def test_overlapping_ego_lane_candidates_are_deterministic():
    c=deterministic_candidate([{"lane_id":"20","score":1.0},{"lane_id":"10","score":1.0}])
    assert c["lane_id"]=="10"


def test_consecutive_physical_fragments_same_logical_route_are_not_lane_change():
    assert transition_kind("A","B","route1","route1",None,None)=="physical_fragment_transition_same_route"


def test_turning_crossing_lane_is_not_same_direction_adjacent():
    assert direction_relation(0,75,20)=="crossing_or_diverging"


def test_opposite_direction_vehicle_ahead_is_directionally_invalid():
    e=build_object_motion_evidence(_recording([[3,0],[2,0],[1,0],[0,0]]),history_frames=2,minimum_displacement_m=0.1)
    assert abs(abs(e[(2,"1")]["object_motion_heading_deg"])-180)<1e-6
    assert direction_relation(0,e[(2,"1")]["object_motion_heading_deg"],20)=="opposite_direction"


def test_crossing_vehicle_near_ego_is_directionally_invalid():
    e=build_object_motion_evidence(_recording([[0,-2],[0,-1],[0,0],[0,1]]),history_frames=2,minimum_displacement_m=0.1)
    assert direction_relation(0,e[(2,"1")]["object_motion_heading_deg"],20)=="crossing_or_diverging"


def test_valid_same_direction_lead():
    e=build_object_motion_evidence(_recording([[0,0],[1,0],[2,0],[3,0]]),history_frames=2,minimum_displacement_m=0.1)
    assert direction_relation(0,e[(2,"1")]["object_motion_heading_deg"],20)=="same_direction"


def test_temporary_missing_lane_assignment_is_explicit():
    assert transition_kind("A",None,"r1",None,"r2","r3")=="missing_lane"


def test_actual_left_lane_transition_is_distinguished():
    assert transition_kind("A","B","r1","r2","r2","r3")=="lane_change_left_candidate"


def test_actual_right_lane_transition_is_distinguished():
    assert transition_kind("A","B","r1","r3","r2","r3")=="lane_change_right_candidate"


def test_continuous_track_recursively_chains_multiple_segments():
    lanes=[_lane("A",0,10,0,"B"),_lane("B",12,22,0,"C"),_lane("C",24,34,0)]
    tracks,mapping,_=build_continuous_tracks(lanes,_recording([[0,0],[5,0],[15,0],[25,0]]))
    track=next(t for t in tracks if "A" in t["member_lane_ids"])
    assert track["member_lane_ids"]==["A","B","C"]
    assert track["inferred_gap_count"]==2
    assert mapping["A"]==mapping["B"]==mapping["C"]
    assignment=assign_point_to_track((23.0,0.0),0.0,tracks)
    assert assignment["track_id"]==mapping["A"]


def test_canonical_endpoint_stitch_merges_same_lane_across_five_metre_gap():
    lanes=[_lane("A",0,10,0),_lane("B",15,25,0)]
    preliminary,_,_=build_continuous_tracks(lanes,_recording([[0,0],[5,0],[20,0]]))
    assert len(preliminary)==2
    stitched,mapping,debug=stitch_canonical_tracks(preliminary,lanes,maximum_endpoint_gap_m=8.0)
    assert len(stitched)==1
    assert set(stitched[0]["member_lane_ids"])=={"A","B"}
    assert stitched[0]["canonical_stitch_count"]==1
    assert mapping["physical_track_0001"]==mapping["physical_track_0002"]
    accepted=next(item for item in debug if item["accepted"])
    assert accepted["endpoint_gap_m"]==5.0
    assert accepted["centerline_lateral_error_m"]==0.0
    assignment=assign_point_to_track_strict((12.5,0.0),0.0,stitched)
    assert assignment["track_id"]==mapping["physical_track_0001"]
    assert assignment["matched_piece_kind"]=="canonical_track_stitch"


def test_canonical_endpoint_stitch_handles_reversed_fragment_point_order():
    lane_a=_lane("A",0,10,0)
    lane_b=_reverse_lane_geometry(_lane("B",15,25,0))
    lanes=[lane_a,lane_b]
    preliminary,_,_=build_continuous_tracks(lanes,_recording([[0,0],[5,0],[20,0]]))
    assert len(preliminary)==2
    stitched,mapping,debug=stitch_canonical_tracks(preliminary,lanes,maximum_endpoint_gap_m=8.0)
    assert len(stitched)==1
    assert set(stitched[0]["member_lane_ids"])=={"A","B"}
    assert mapping["physical_track_0001"]==mapping["physical_track_0002"]
    accepted=next(item for item in debug if item["accepted"])
    assert {accepted["endpoint_a"],accepted["endpoint_b"]} <= {"start","end"}
    assignment=assign_point_to_track_strict((12.5,0.0),0.0,stitched)
    assert assignment["matched_piece_kind"]=="canonical_track_stitch"


def test_continuous_track_adjacent_lane_uses_local_parallel_overlap():
    lanes=[_lane("E",0,30,0),_lane("L",0,30,3.5)]
    tracks,mapping,_=build_continuous_tracks(lanes,_recording([[0,0],[5,0],[10,0]]))
    adjacency=adjacent_tracks(mapping["E"],(10.0,0.0),tracks)
    assert adjacency["left"]["track_id"]==mapping["L"]
    assert adjacency["right"]["track_id"] is None


def test_track_topology_establishes_static_left_and_right_neighbors():
    lanes=[_lane("E",0,40,0),_lane("L",0,40,3.5),_lane("R",0,40,-3.5)]
    tracks,mapping,_=build_continuous_tracks(lanes,_recording([[0,0],[5,0],[10,0]]))
    graph=build_track_adjacency_graph(tracks,lanes,minimum_overlap_m=8.0)
    selected,_,_=select_topology_adjacency(mapping["E"],(20.0,0.0),tracks,graph,hysteresis_enabled=False)
    assert selected["left"]["track_id"]==mapping["L"]
    assert selected["right"]["track_id"]==mapping["R"]
    assert selected["left"]["method"]=="track_topology_adjacency"


def test_topology_hysteresis_holds_previous_neighbor_when_improvement_is_small():
    tracks=[{"track_id":"E","centerline_lcs_m":[[0,0],[40,0]]}]
    graph={"by_ego_track":{"E":{"left":[
        {"ego_track_id":"E","adjacent_track_id":"A","side":"left","ego_s_start_m":0.0,"ego_s_end_m":40.0,"overlap_m":40.0,"score":3.2},
        {"ego_track_id":"E","adjacent_track_id":"B","side":"left","ego_s_start_m":0.0,"ego_s_end_m":40.0,"overlap_m":40.0,"score":3.0},
    ],"right":[]}}}
    selected,previous,pending=select_topology_adjacency(
        "E",(20.0,0.0),tracks,graph,
        previous={"left":"A","right":None},pending={"left":None,"right":None},
        hysteresis_enabled=True,switch_score_margin=0.75,switch_confirmation_frames=3,
    )
    assert selected["left"]["track_id"]=="A"
    assert selected["left"]["held_from_previous_frame"] is True
    assert previous["left"]=="A"
    assert pending["left"] is None


def test_outside_tolerance_cannot_acquire_new_track():
    lane=_lane("E",0,30,0)
    tracks,mapping,_=build_continuous_tracks([lane],_recording([[0,0],[5,0]]))
    assignment=assign_point_to_track_strict((10.0,2.0),0.0,tracks,previous_track_id=None,outside_tolerance_m=1.0)
    assert assignment["track_id"] is None
    held=assign_point_to_track_strict((10.0,2.0),0.0,tracks,previous_track_id=mapping["E"],outside_tolerance_m=1.0)
    assert held["track_id"]==mapping["E"]
    assert held["method"]=="previous_track_tolerance_hold"


def test_raw_ld_lines_can_infer_missing_ego_corridor():
    recording={
        "ld_feature_store":{
            "points":[
                {"point_id":"l0","position_lcs_m":[-20,1.75]},{"point_id":"l1","position_lcs_m":[20,1.75]},
                {"point_id":"r0","position_lcs_m":[-20,-1.75]},{"point_id":"r1","position_lcs_m":[20,-1.75]},
            ],
            "lane_lines":[
                {"line_id":"LEFT_RAW","point_ids":["l0","l1"]},
                {"line_id":"RIGHT_RAW","point_ids":["r0","r1"]},
            ],
            "road_boundaries":[],
        },
        "frames":[],
    }
    corridor=infer_ego_corridor_from_boundaries(recording,[],{},(0.0,0.0),0.0)
    assert corridor["valid"] is True
    assert corridor["left_boundary_id"]=="LEFT_RAW"
    assert corridor["right_boundary_id"]=="RIGHT_RAW"
    assert abs(corridor["width_at_ego_m"]-3.5)<1e-6
