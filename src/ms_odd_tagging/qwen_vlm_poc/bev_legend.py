"""Human-readable BEV legend for VLM prompts.

Object-class entries are generated from the same CLASS_COLORS mapping used by the
BEV renderer so the model-facing legend stays aligned with visualization colors.
"""

from __future__ import annotations

from ms_odd_tagging.input_generator.model_input import CLASS_COLORS
from ms_odd_tagging.input_generator.revised_bev import (
    ACTIVE_OBJECT_COLOR,
    CROSSWALK_COLOR,
    FUTURE_PATH_COLOR,
    FUTURE_PATH_CORRIDOR_COLOR,
    LANE_STYLES,
    PEDESTRIAN_COLOR,
    PEDESTRIAN_TRAIL_COLOR,
    STOPLINE_COLOR,
)


_COLOR_NAMES = {
    "#2f6fed": "blue",
    "#7c3aed": "purple",
    "#6d28d9": "dark purple",
    "#8b5cf6": "violet",
    "#a855f7": "purple",
    "#9333ea": "purple",
    "#4f9a38": "green",
    "#0d9488": "teal",
    "#14b8a6": "teal",
    "#f97316": "orange",
    "#10b981": "green",
    "#0891b2": "cyan",
    "#2563eb": "blue",
    "#a16207": "brown",
    "#92400e": "brown",
    "#b45309": "brown/orange",
    "#d97706": "orange",
    "#ef4444": "red",
    "#dc2626": "red",
    "#f43f5e": "pink/red",
    "#fb923c": "orange",
    "#475569": "gray",
    "#facc15": "yellow",
    "#e11d48": "red/pink",
    "#0ea5e9": "light blue",
    "#94a3b8": "gray",
    "#64748b": "gray",
    "#111827": "near-black",
    "#67e8f9": "light cyan",
    "#ca8a04": "yellow-brown",
}


def _describe_color(hex_color: str) -> str:
    return f"{_COLOR_NAMES.get(hex_color.lower(), 'color')} ({hex_color})"


def bev_legend_text() -> str:
    lines = [
        "BEV drawing legend (visual encoding only; colors do not imply scenario truth):",
        "- Ego vehicle: green, centered, with a nose marker showing forward direction.",
        f"- Candidate/active object outline: {_describe_color(ACTIVE_OBJECT_COLOR)}; candidate pedestrians also show their numeric object ID next to the object.",
        f"- Candidate pedestrian observed trail: {_describe_color(PEDESTRIAN_TRAIL_COLOR)} line/dots; raw observed trajectory across the scene, transformed into the current BEV frame.",
        f"- Future ego trajectory centerline: {_describe_color(FUTURE_PATH_COLOR)}; derived from future canonical ego poses.",
        f"- Future ego path corridor: translucent {_describe_color(FUTURE_PATH_CORRIDOR_COLOR)} band around the future trajectory; this is geometry only, not a conflict label.",
        "- Object classes:",
    ]
    for class_name, color in CLASS_COLORS.items():
        effective_color = PEDESTRIAN_COLOR if class_name == "pedestrian" else color
        lines.append(f"  - {class_name}: {_describe_color(effective_color)}")

    lines.extend(
        [
            "- Map / road geometry:",
            f"  - crosswalk roadmark: {_describe_color(CROSSWALK_COLOR)}",
            f"  - stopline roadmark: {_describe_color(STOPLINE_COLOR)}",
            "  - drivable road boundary: brown/orange",
            "  - other road boundary: darker brown",
            "  - lane lines by pattern:",
        ]
    )
    for pattern, (color, _width, _alpha) in LANE_STYLES.items():
        lines.append(f"    - {pattern}: {_describe_color(color)}")
    lines.append("- Interpret object motion using the observed trail and matching numeric IDs; colors identify class/overlay type only.")
    return "\n".join(lines)
