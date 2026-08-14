from __future__ import annotations

import pytest

from ms_odd_tagging.input_generator.bev_renderer import normalize_bev_style, render_metadata


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
