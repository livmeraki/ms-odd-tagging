"""Generate deterministic pseudo-BEV fixtures for pedestrian VLM audits."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1000
HEIGHT = 900
EGO = (500, 700)


SCENES = {
    "positive_crossing_ahead": {
        "pedestrians": [(455, 430, "right")],
        "crosswalk": True,
        "ego_stopped": True,
    },
    "positive_approaching_left": {
        "pedestrians": [(315, 505, "right")],
        "crosswalk": True,
        "ego_stopped": True,
    },
    "positive_approaching_right": {
        "pedestrians": [(685, 500, "left")],
        "crosswalk": True,
        "ego_stopped": True,
    },
    "positive_multiple_one_crossing": {
        "pedestrians": [(470, 430, "right"), (245, 350, "up"), (780, 330, "down")],
        "crosswalk": True,
        "ego_stopped": True,
    },
    "negative_no_pedestrian": {
        "pedestrians": [],
        "crosswalk": True,
        "ego_stopped": False,
    },
    "negative_sidewalk_only": {
        "pedestrians": [(205, 425, "up")],
        "crosswalk": False,
        "ego_stopped": False,
    },
    "negative_other_lane_crossing": {
        "pedestrians": [(755, 330, "left")],
        "crosswalk": True,
        "ego_stopped": False,
    },
    "negative_stopped_for_lead": {
        "pedestrians": [],
        "crosswalk": True,
        "ego_stopped": True,
        "lead_vehicle": (500, 475),
    },
}


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size=size)
    except OSError:
        return ImageFont.load_default()


def _arrow(draw: ImageDraw.ImageDraw, x: int, y: int, direction: str) -> None:
    delta = {"up": (0, -42), "down": (0, 42), "left": (-42, 0), "right": (42, 0)}[direction]
    end = (x + delta[0], y + delta[1])
    draw.line((x, y, *end), fill=(255, 181, 61), width=7)
    if direction == "right":
        head = [(end[0], end[1]), (end[0] - 14, end[1] - 10), (end[0] - 14, end[1] + 10)]
    elif direction == "left":
        head = [(end[0], end[1]), (end[0] + 14, end[1] - 10), (end[0] + 14, end[1] + 10)]
    elif direction == "up":
        head = [(end[0], end[1]), (end[0] - 10, end[1] + 14), (end[0] + 10, end[1] + 14)]
    else:
        head = [(end[0], end[1]), (end[0] - 10, end[1] - 14), (end[0] + 10, end[1] - 14)]
    draw.polygon(head, fill=(255, 181, 61))


def render_scene(scene: dict, output_path: Path) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), (18, 23, 29))
    draw = ImageDraw.Draw(image)

    # Road, sidewalks, lane lines and ego path.
    draw.rectangle((170, 30, 830, 890), fill=(54, 60, 67))
    draw.rectangle((130, 30, 170, 890), fill=(96, 88, 75))
    draw.rectangle((830, 30, 870, 890), fill=(96, 88, 75))
    for y in range(50, 880, 80):
        draw.line((390, y, 390, min(y + 42, 880)), fill=(71, 157, 255), width=6)
        draw.line((610, y, 610, min(y + 42, 880)), fill=(71, 157, 255), width=6)
    draw.polygon([(435, 760), (565, 760), (540, 80), (460, 80)], fill=(45, 86, 113))

    if scene.get("crosswalk"):
        for y in range(390, 475, 18):
            draw.rectangle((175, y, 825, y + 8), fill=(220, 72, 72))

    # Ego footprint and forward nose.
    ex, ey = EGO
    draw.rounded_rectangle((ex - 40, ey - 62, ex + 40, ey + 62), radius=8, fill=(42, 196, 102), outline="white", width=3)
    draw.polygon([(ex, ey - 92), (ex - 24, ey - 60), (ex + 24, ey - 60)], fill=(42, 196, 102), outline="white")
    draw.text((ex - 27, ey - 13), "EGO", font=_font(20), fill="white")
    draw.text((455, 805), "FORWARD", font=_font(22), fill=(235, 235, 235))
    draw.line((500, 798, 500, 770), fill=(235, 235, 235), width=4)

    if lead := scene.get("lead_vehicle"):
        x, y = lead
        draw.rounded_rectangle((x - 35, y - 58, x + 35, y + 58), radius=8, fill=(76, 139, 245), outline="white", width=3)

    for x, y, direction in scene.get("pedestrians", []):
        draw.ellipse((x - 18, y - 18, x + 18, y + 18), fill=(255, 142, 43), outline="white", width=3)
        draw.line((x, y + 18, x, y + 48), fill=(255, 142, 43), width=10)
        _arrow(draw, x, y - 27, direction)

    status = "EGO SPEED: 0.0 m/s" if scene.get("ego_stopped") else "EGO SPEED: 4.0 m/s"
    draw.rounded_rectangle((24, 20, 290, 70), radius=10, fill=(7, 10, 13), outline=(130, 140, 150), width=2)
    draw.text((42, 34), status, font=_font(20), fill=(245, 245, 245))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG", optimize=True)


def generate(output_dir: Path) -> list[Path]:
    paths = []
    for scene_id, scene in SCENES.items():
        path = output_dir / f"{scene_id}.png"
        render_scene(scene, path)
        paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate controlled pseudo-BEV pedestrian scenes.")
    parser.add_argument("--output-dir", type=Path, default=Path("examples/pseudo_bev_pedestrian"))
    args = parser.parse_args()
    paths = generate(args.output_dir)
    print(f"Generated {len(paths)} pseudo-BEV images in {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
