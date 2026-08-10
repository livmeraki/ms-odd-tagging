import math

from ms_odd_tagging.experiments.lane_debug_v2.curvature_gap_fill import build_curvature_gap


def _arc(radius, angles):
    return [[radius * math.cos(a), radius * math.sin(a)] for a in angles]


def test_curvature_gap_fill_bends_between_curved_fragments():
    # Same circular lane with a missing angular section between the fragments.
    radius = 30.0
    a = _arc(radius, [math.radians(x) for x in (0, 5, 10, 15)])
    b = _arc(radius, [math.radians(x) for x in (30, 35, 40, 45)])
    fill = build_curvature_gap(
        a, "end", b, "start",
        width_a_m=3.5,
        width_b_m=3.5,
        sample_spacing_m=0.5,
    )
    assert fill is not None
    assert len(fill["centerline_lcs_m"]) >= 4
    assert len(fill["polygon_lcs_m"]) == 2 * len(fill["centerline_lcs_m"])
    assert fill["arc_length_m"] > fill["chord_length_m"]
    assert fill["arc_to_chord_ratio"] < 1.2
    assert fill["maximum_abs_bridge_curvature_per_m"] < 0.12


def test_curvature_gap_fill_preserves_width_through_gap():
    a = [[0.0, 0.0], [4.0, 0.2], [8.0, 0.8], [12.0, 1.8]]
    b = [[18.0, 4.2], [22.0, 6.2], [26.0, 8.8], [30.0, 12.0]]
    fill = build_curvature_gap(a, "end", b, "start", width_a_m=3.4, width_b_m=3.8)
    assert fill is not None
    start_width = math.dist(fill["left_boundary_lcs_m"][0], fill["right_boundary_lcs_m"][0])
    end_width = math.dist(fill["left_boundary_lcs_m"][-1], fill["right_boundary_lcs_m"][-1])
    assert abs(start_width - 3.4) < 1e-6
    assert abs(end_width - 3.8) < 1e-6
