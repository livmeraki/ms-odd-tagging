from ms_odd_tagging.experiments.lane_debug_v2.object_motion import build_object_motion_evidence
from ms_odd_tagging.experiments.lane_debug_v2.lane_state import deterministic_candidate, direction_relation, transition_kind


def _recording(points):
    return {"frames":[{"frame_index":i,"time_since_start_s":i*0.1,"objects":[{"object_id":"1","position_lcs_m":p}]} for i,p in enumerate(points)]}

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
