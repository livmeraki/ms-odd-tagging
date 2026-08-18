"""Fast Pillow-backed drawing surface compatible with the BEV renderer canvas API.

This module is intentionally separate from the active renderer so the Pillow
backend can be benchmarked against the historical pure-Python ``PngCanvas``
before adoption.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw


class PillowCanvas:
    """Pillow/ImageDraw implementation of the small canvas API used by BEV code."""

    def __init__(self, width: int, height: int, bg=(248, 250, 252)) -> None:
        self.width = int(width)
        self.height = int(height)
        self.image = Image.new("RGB", (self.width, self.height), tuple(bg))
        # RGBA mode makes ImageDraw alpha-blend into the RGB destination while
        # keeping all rasterization in Pillow's compiled implementation.
        self.draw = ImageDraw.Draw(self.image, "RGBA")

    @staticmethod
    def _rgba(color, alpha: float = 1.0):
        a = max(0, min(255, round(float(alpha) * 255)))
        return tuple(int(value) for value in color[:3]) + (a,)

    def set_pixel(self, x, y, color, alpha=1.0) -> None:
        x = int(round(x))
        y = int(round(y))
        if 0 <= x < self.width and 0 <= y < self.height:
            self.draw.point((x, y), fill=self._rgba(color, alpha))

    def line(self, x1, y1, x2, y2, color, width=1, alpha=1.0) -> None:
        self.draw.line(
            (float(x1), float(y1), float(x2), float(y2)),
            fill=self._rgba(color, alpha),
            width=max(1, int(round(width))),
        )

    def polyline(self, points, color, width=1, alpha=1.0) -> None:
        points = list(points)
        if len(points) < 2:
            return
        self.draw.line(
            [(float(x), float(y)) for x, y in points],
            fill=self._rgba(color, alpha),
            width=max(1, int(round(width))),
            joint="curve",
        )

    def circle(self, cx, cy, radius, color, alpha=1.0) -> None:
        radius = float(radius)
        self.draw.ellipse(
            (
                float(cx) - radius,
                float(cy) - radius,
                float(cx) + radius,
                float(cy) + radius,
            ),
            fill=self._rgba(color, alpha),
        )

    def polygon(self, points, fill, outline=None, alpha=1.0, outline_width=1) -> None:
        points = [(float(x), float(y)) for x, y in points]
        if not points:
            return
        self.draw.polygon(points, fill=self._rgba(fill, alpha))
        if outline is not None:
            # Match the historical canvas: fill is alpha blended, outline is opaque.
            closed = [*points, points[0]]
            self.draw.line(
                closed,
                fill=self._rgba(outline, 1.0),
                width=max(1, int(round(outline_width))),
                joint="curve",
            )

    def save_png(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.image.save(path, format="PNG")
