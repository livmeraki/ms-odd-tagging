from __future__ import annotations

import struct
from pathlib import Path

from ms_odd_tagging.input_generator.revised_bev import (
    _clip_segment,
    _footprint_buffer_points,
    render_revised_bev_png,
)


def test_clipping_keeps_geometry_crossing_the_asymmetric_view() -> None:
    clipped = _clip_segment((-40.0, 0.0), (120.0, 0.0), 45.0, 45.0, 25.0, 95.0)
    assert clipped == ((-25.0, 0.0), (95.0, 0.0))


def test_footprint_proximity_boundary_uses_configured_buffer_radius() -> None:
    points = _footprint_buffer_points(4.8, 2.0, 30.0)
    assert max(point[0] for point in points) == 32.4
    assert min(point[0] for point in points) == -32.4
    assert max(point[1] for point in points) == 31.0
    assert min(point[1] for point in points) == -31.0


def test_revised_bev_renders_png_with_requested_dimensions(tmp_path: Path) -> None:
    recording = {"recording_id": "recording", "ld_feature_store": {}}
    frame = {
        "frame_index": 0,
        "ego": {
            "position_lcs_m": [10.0, 20.0, 0.0],
            "heading_lcs_rad": 1.0,
            "speed_mps": 5.0,
            "velocity_lcs_mps": [2.7, 4.2, 0.0],
        },
        "objects": [
            {
                "object_id": "lead-1",
                "class": "car",
                "annotation_type": "dynamic",
                "position_lcs_m": [15.0, 28.0, 0.0],
                "dimensions_m": {"length": 4.5, "width": 1.8},
                "heading_relative_rad": 0.0,
                "velocity_lcs_mps": [2.0, 3.0, 0.0],
            }
        ],
        "ld": {"available": False},
    }
    output = tmp_path / "bev.png"
    render_revised_bev_png(
        recording,
        frame,
        output,
        (45.0, 45.0, 25.0, 95.0),
        (320, 288),
        lane_context={
            "ego_lane": {"logical_lane_id": "route-1"},
            "lead": {"object_id": "lead-1", "class": "car"},
            "objects": [
                {"object_id": "lead-1", "logical_lane_id": "route-1"}
            ],
        },
        proximity_radius_m=30.0,
    )
    content = output.read_bytes()
    assert content.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", content[16:24])
    assert (width, height) == (320, 288)
