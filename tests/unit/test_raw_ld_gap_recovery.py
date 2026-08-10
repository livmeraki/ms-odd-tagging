from ms_odd_tagging.experiments.lane_debug_v2.raw_ld_gap_recovery import build_raw_ld_gap_tracks


def _recording(lines):
    points=[]; lane_lines=[]
    for index,(line_id,coords) in enumerate(lines):
        ids=[]
        for j,(x,y) in enumerate(coords):
            pid=f"p{index}_{j}"; ids.append(pid); points.append({"point_id":pid,"position_lcs_m":[x,y]})
        lane_lines.append({"line_id":line_id,"point_ids":ids})
    return {"ld_feature_store":{"points":points,"lane_lines":lane_lines,"road_boundaries":[]},"frames":[]}


def test_only_immediate_neighbor_boundaries_form_gap_lanes():
    recording=_recording([
        ("L0",[(0,0),(20,0)]),
        ("L1",[(0,3.5),(20,3.5)]),
        ("L2",[(0,7.0),(20,7.0)]),
    ])
    tracks,debug=build_raw_ld_gap_tracks(recording,[],minimum_gap_overlap_m=6.0)
    pairs={frozenset((t["left_boundary_id"],t["right_boundary_id"])) for t in tracks}
    assert frozenset(("L0","L1")) in pairs
    assert frozenset(("L1","L2")) in pairs
    assert frozenset(("L0","L2")) not in pairs
    assert all(t["source"]=="raw_ld_gap_recovery" for t in tracks)


def test_wedge_like_diverging_boundary_pair_is_rejected():
    recording=_recording([
        ("A",[(0,0),(10,0),(20,0)]),
        ("B",[(0,3.0),(10,4.5),(20,6.0)]),
    ])
    tracks,debug=build_raw_ld_gap_tracks(
        recording,[],minimum_gap_overlap_m=6.0,
        maximum_width_std_m=0.5,maximum_width_range_m=1.0,maximum_wedge_ratio=1.4,
    )
    assert tracks==[]


def test_raw_ld_does_not_duplicate_canonical_covered_lane():
    recording=_recording([
        ("LEFT",[(0,1.75),(20,1.75)]),
        ("RIGHT",[(0,-1.75),(20,-1.75)]),
    ])
    canonical=[{
        "lane_id":"E","assignment_valid":True,
        "left_edge_id":"LEFT","right_edge_id":"RIGHT",
        "polygon_lcs_m":[[0,1.75],[20,1.75],[20,-1.75],[0,-1.75]],
    }]
    tracks,_=build_raw_ld_gap_tracks(recording,canonical,minimum_gap_overlap_m=6.0)
    assert tracks==[]
