from __future__ import annotations

import pytest

from ms_odd_tagging.frame_inputs.bev_renderer import normalize_bev_style, render_metadata
from ms_odd_tagging.frame_inputs.revised_bev import metric_viewport


def test_bev_style_aliases() -> None:
    assert normalize_bev_style("standard") == "standard"
    assert normalize_bev_style("legacy") == "standard"
    assert normalize_bev_style("revised") == "explorer_aligned"
    assert normalize_bev_style("explorer-aligned") == "explorer_aligned"


def test_invalid_bev_style() -> None:
    with pytest.raises(ValueError):
        normalize_bev_style("invalid")


def test_centered_renderer_metadata() -> None:
    metadata = render_metadata("explorer_aligned", (45.0, 45.0, 25.0, 95.0)).to_dict()
    assert metadata["ego_position"] == "center"
    assert metadata["extent_m"] == {
        "left": 45.0,
        "right": 45.0,
        "behind": 60.0,
        "ahead": 60.0,
    }
    assert metadata["configured_extent_m"] == {
        "left": 45.0,
        "right": 45.0,
        "behind": 25.0,
        "ahead": 95.0,
    }


def test_standard_renderer_metadata() -> None:
    metadata = render_metadata("standard", (45.0, 45.0, 25.0, 95.0)).to_dict()
    assert metadata["ego_position"] == "configured-offset"
    assert metadata["extent_m"] == metadata["configured_extent_m"]


def test_metric_viewport_uses_one_pixels_per_meter_scale() -> None:
    scale, origin_x, origin_y, draw_width, draw_height = metric_viewport(
        (45.0, 45.0, 60.0, 60.0),
        (1000, 900),
    )

    # 90 m x 120 m must fit inside 1000 x 900 without geometric stretching.
    assert scale == pytest.approx(7.5)
    assert draw_width == pytest.approx(675.0)
    assert draw_height == pytest.approx(900.0)
    assert origin_x == pytest.approx(162.5)
    assert origin_y == pytest.approx(0.0)


def test_metric_viewport_rejects_invalid_dimensions() -> None:
    with pytest.raises(ValueError):
        metric_viewport((0.0, 0.0, 60.0, 60.0), (1000, 900))
    with pytest.raises(ValueError):
        metric_viewport((45.0, 45.0, 60.0, 60.0), (0, 900))
