import inspect

from ms_odd_tagging.experiments.lane_debug_v2 import explorer_visualization


def test_explorer_includes_constructed_inferred_gap_polygons():
    source = inspect.getsource(explorer_visualization)
    assert "p.kind==='inferred_gap'" in source
    assert "drawFillPieces(out,t,color,strong)" in source
