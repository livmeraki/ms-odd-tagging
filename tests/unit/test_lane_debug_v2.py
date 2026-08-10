from ms_odd_tagging.experiments.lane_debug_v2.object_motion import build_object_motion_evidence
from ms_odd_tagging.experiments.lane_debug_v2.lane_state import deterministic_candidate, direction_relation, transition_kind
from ms_odd_tagging.experiments.lane_debug_v2.continuous_tracks import build_continuous_tracks, assign_point_to_track, adjacent_tracks


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
        "polygon_lcs_m":left+list(reversed(right)),"geometry_recovered":False,
        "recovery_method":None,"curvature_continuations":continuation,
    }

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

def test_continuous_track_adjacent_lane_uses_local_parallel_overlap():
    lanes=[_lane("E",0,30,0),_lane("L",0,30,3.5)]
    tracks,mapping,_=build_continuous_tracks(lanes,_recording([[0,0],[5,0],[10,0]]))
    adjacency=adjacent_tracks(mapping["E"],(10.0,0.0),tracks)
    assert adjacency["left"]["track_id"]==mapping["L"]
    assert adjacency["right"]["track_id"] is None
