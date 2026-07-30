from __future__ import annotations

import inspect
import math
import struct
import zlib
from pathlib import Path

import pytest

from ms_odd_tagging.input_generator.revised_bev import (
    ACTIVE_OBJECT_COLOR,
    CROSSWALK_COLOR,
    FORWARD_ARC_COLOR,
    PEDESTRIAN_COLOR,
    _clip_segment,
    _forward_arc_points,
    _footprint_buffer_points,
    centered_extent,
    render_revised_bev_png,
)


def png_pixel(content: bytes, x: int, y: int, width: int) -> bytes:
    offset = 8
    compressed = bytearray()
    while offset < len(content):
        length = struct.unpack(">I", content[offset:offset + 4])[0]
        tag = content[offset + 4:offset + 8]
        data = content[offset + 8:offset + 8 + length]
        if tag == b"IDAT":
            compressed.extend(data)
        offset += 12 + length
    raw = zlib.decompress(bytes(compressed))
    stride = 1 + width * 3
    pixel_start = y * stride + 1 + x * 3
    return raw[pixel_start:pixel_start + 3]


def test_clipping_keeps_geometry_crossing_the_asymmetric_view() -> None:
    clipped = _clip_segment((-40.0, 0.0), (120.0, 0.0), 45.0, 45.0, 25.0, 95.0)
    assert clipped == ((-25.0, 0.0), (95.0, 0.0))


def test_footprint_proximity_boundary_uses_configured_buffer_radius() -> None:
    points = _footprint_buffer_points(4.8, 2.0, 30.0)
    assert max(point[0] for point in points) == 32.4
    assert min(point[0] for point in points) == -32.4
    assert max(point[1] for point in points) == 31.0
    assert min(point[1] for point in points) == -31.0


def test_phase3c_forward_arc_uses_configured_radii_and_angle() -> None:
    points = _forward_arc_points(2.0, 30.0, 30.0)
    radii = [(x * x + y * y) ** 0.5 for x, y in points]
    angles = [abs(math.degrees(math.atan2(y, x))) for x, y in points]
    assert min(radii) == pytest.approx(2.0)
    assert max(radii) == pytest.approx(30.0)
    assert max(angles) == pytest.approx(30.0)


def test_vlm_debug_colors_are_distinct_from_crosswalk_and_each_other() -> None:
    colors = {
        CROSSWALK_COLOR,
        FORWARD_ARC_COLOR,
        ACTIVE_OBJECT_COLOR,
        PEDESTRIAN_COLOR,
    }
    assert len(colors) == 4


def test_centered_extent_keeps_configured_total_width_and_length() -> None:
    assert centered_extent((45.0, 45.0, 25.0, 95.0)) == (
        45.0,
        45.0,
        60.0,
        60.0,
    )


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
        crossing_arc=(2.0, 30.0, 30.0),
        debug_context={
            "rule_based_reference": {
                "active_events": [
                    {
                        "evidence": {
                            "source_object_ids": ["lead-1"],
                        }
                    }
                ]
            }
        },
    )
    content = output.read_bytes()
    assert content.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", content[16:24])
    assert (width, height) == (320, 288)


def test_revised_bev_centers_ego_on_requested_canvas(tmp_path: Path) -> None:
    recording = {"recording_id": "recording", "ld_feature_store": {}}
    frame = {
        "frame_index": 0,
        "ego": {
            "position_lcs_m": [0.0, 0.0, 0.0],
            "heading_lcs_rad": 0.0,
            "speed_mps": 0.0,
        },
        "objects": [],
        "ld": {"available": False},
    }
    output = tmp_path / "bev.png"
    render_revised_bev_png(
        recording,
        frame,
        output,
        (45.0, 45.0, 25.0, 95.0),
        (320, 288),
    )
    content = output.read_bytes()
    center_x = 320 // 2
    center_y = 288 // 2
    assert png_pixel(content, center_x, center_y, 320) != bytes((248, 250, 252))


def test_revised_bev_does_not_draw_top_information_box() -> None:
    source = inspect.getsource(render_revised_bev_png)
    assert "_annotate_kinematics(" not in source
