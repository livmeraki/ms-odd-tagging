"""Stable dispatch API for per-frame BEV rendering."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .model_input import render_bev_model_png
from .revised_bev import centered_extent, render_revised_bev_png

BevStyle = Literal["standard", "explorer_aligned"]
SUPPORTED_BEV_STYLES = ("standard", "explorer_aligned")


@dataclass(frozen=True)
class BevRenderMetadata:
    style: BevStyle
    renderer: str
    orientation: str
    ego_position: str
    extent_m: dict[str, float]
    configured_extent_m: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "style": self.style,
            "renderer": self.renderer,
            "orientation": self.orientation,
            "ego_position": self.ego_position,
            "extent_m": dict(self.extent_m),
            "configured_extent_m": dict(self.configured_extent_m),
        }


def normalize_bev_style(style: str) -> BevStyle:
    normalized = str(style).strip().lower().replace("-", "_")
    aliases = {
        "standard": "standard",
        "legacy": "standard",
        "v1": "standard",
        "explorer_aligned": "explorer_aligned",
        "revised": "explorer_aligned",
        "centered": "explorer_aligned",
    }
    if normalized not in aliases:
        raise ValueError(
            f"Unsupported BEV style {style!r}; expected one of: "
            + ", ".join(SUPPORTED_BEV_STYLES)
        )
    return aliases[normalized]  # type: ignore[return-value]


def render_metadata(style: str, extent: tuple[float, float, float, float]) -> BevRenderMetadata:
    normalized = normalize_bev_style(style)
    left, right, behind, ahead = (float(value) for value in extent)
    configured = {"left": left, "right": right, "behind": behind, "ahead": ahead}
    if normalized == "explorer_aligned":
        cl, cr, cb, ca = centered_extent(extent)
        return BevRenderMetadata(
            style=normalized,
            renderer="explorer-aligned-revised-v1",
            orientation="ego-heading-up",
            ego_position="center",
            extent_m={"left": cl, "right": cr, "behind": cb, "ahead": ca},
            configured_extent_m=configured,
        )
    return BevRenderMetadata(
        style=normalized,
        renderer="model-input-v2",
        orientation="ego-heading-up",
        ego_position="configured-offset",
        extent_m=configured,
        configured_extent_m=configured,
    )


def render_frame_bev(
    *,
    style: str,
    recording: dict[str, Any],
    frame: dict[str, Any],
    output_path: Path,
    extent: tuple[float, float, float, float],
    size: tuple[int, int],
    ld_filters: dict[str, set[str]] | None = None,
    lane_context: dict[str, Any] | None = None,
    proximity_radius_m: float = 30.0,
    crossing_arc: tuple[float, float, float] | None = None,
    debug_context: dict[str, Any] | None = None,
) -> BevRenderMetadata:
    normalized = normalize_bev_style(style)
    if normalized == "explorer_aligned":
        render_revised_bev_png(
            recording,
            frame,
            output_path,
            extent,
            size,
            lane_context=lane_context,
            proximity_radius_m=proximity_radius_m,
            crossing_arc=crossing_arc,
            debug_context=debug_context,
        )
    else:
        render_bev_model_png(
            recording,
            {"frames": [frame]},
            int(frame["frame_index"]),
            "current",
            output_path,
            extent,
            size,
            ld_filters=ld_filters,
        )
    return render_metadata(normalized, extent)
