from __future__ import annotations

from ms_odd_tagging.input_generator.model_input import CLASS_COLORS
from ms_odd_tagging.qwen_vlm_poc.bev_legend import bev_legend_text


def test_bev_legend_covers_every_rendered_object_class():
    legend = bev_legend_text()
    for class_name in CLASS_COLORS:
        assert f"- {class_name}:" in legend

    assert "pedestrian: orange" in legend
    assert "Ego vehicle: green" in legend
    assert "Candidate/active object outline:" in legend
    assert "crosswalk roadmark:" in legend
    assert "stopline roadmark:" in legend
    assert "lane lines by pattern:" in legend
