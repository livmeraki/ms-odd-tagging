from __future__ import annotations

from pathlib import Path

from PIL import Image

from ms_odd_tagging.frame_inputs.pillow_canvas import PillowCanvas


def test_pillow_canvas_supports_bev_drawing_api(tmp_path: Path) -> None:
    output = tmp_path / "canvas.png"
    canvas = PillowCanvas(120, 80)
    canvas.line(5, 5, 110, 5, (255, 0, 0), width=3, alpha=0.8)
    canvas.polyline([(5, 15), (60, 25), (110, 15)], (0, 0, 255), width=2, alpha=0.7)
    canvas.circle(30, 45, 6, (0, 255, 0), alpha=1.0)
    canvas.polygon(
        [(60, 40), (100, 40), (100, 70), (60, 70)],
        (255, 255, 0),
        outline=(0, 0, 0),
        alpha=0.25,
        outline_width=2,
    )
    canvas.save_png(output)

    assert output.is_file()
    with Image.open(output) as image:
        assert image.size == (120, 80)
        assert image.mode == "RGB"
