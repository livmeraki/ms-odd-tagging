from __future__ import annotations

import json
from pathlib import Path

from ms_odd_tagging.canonical import core as canonical
from ms_odd_tagging.canonical.odld import build_recording


RECORDING = "Rec_Drv_GER_STATIC_TRAFFIC_LIGHT_TEST"


def _bbox(x: float, y: float = 0.0) -> dict[str, float]:
    return {
        "x": x,
        "y": y,
        "z": 4.0,
        "length": 0.5,
        "width": 0.5,
        "height": 3.0,
        "qx": 0.0,
        "qy": 0.0,
        "qz": 0.0,
        "qw": 1.0,
    }


def _object(
    object_id: str,
    *,
    class_name: str = "traffic_light_car",
    annotation_type: str = "static",
    x: float = 20.0,
) -> dict:
    bbox = _bbox(x)
    return {
        "objectId": object_id,
        "className": class_name,
        "subclassName": None,
        "type": annotation_type,
        "bbox3d": bbox,
        "visible_frames": [5],
        "frames": {
            "5": {
                "frameIndex": 5,
                "bbox3d": bbox,
            }
        },
    }


def test_only_nearby_supported_static_objects_are_persisted() -> None:
    nearby_light = _object("nearby")
    far_light = _object("far", x=150.0)
    traffic_sign = _object("sign", class_name="traffic_sign")
    dynamic_light = _object("dynamic", annotation_type="dynamic")

    candidates = canonical.persisted_static_objects(
        [nearby_light, far_light, traffic_sign, dynamic_light]
    )
    merged = canonical.frame_objects_with_persisted_static(
        [],
        candidates,
        (0.0, 0.0, 0.0),
    )

    assert [obj["objectId"] for obj in merged] == ["nearby"]


def test_odld_persists_sparse_static_traffic_light_before_sampling(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    recording_dir = source_root / RECORDING
    recording_dir.mkdir(parents=True)

    od_annotations = {
        "scene": {
            "id": "scene-id",
            "name": "scene-name",
            "frameCount": 11,
        },
        "objects": [_object("traffic-light-1")],
    }
    ld_annotations = {
        "scene": {
            "id": "scene-id",
            "name": "scene-name",
            "frameCount": 11,
        },
        "lanes": {
            "points": [],
            "lines": [],
            "lanes": [],
            "roadBoundaries": [],
            "topologies": [],
        },
        "roadmarks": [],
    }
    trajectory = "".join(
        f"{index / 10:.1f} 0.0 0.0 0.0 0.0 0.0 0.0 1.0\n"
        for index in range(11)
    )

    (recording_dir / "annotations_OD.json").write_text(
        json.dumps(od_annotations), encoding="utf-8"
    )
    (recording_dir / "annotations_LD.json").write_text(
        json.dumps(ld_annotations), encoding="utf-8"
    )
    (recording_dir / "traj_lcs.txt").write_text(trajectory, encoding="utf-8")

    _, result = build_recording(
        source_root,
        tmp_path / "output",
        RECORDING,
        100.0,
        False,
    )

    for frame in result["frames"]:
        lights = [
            obj
            for obj in frame["objects"]
            if obj["class"] == "traffic_light_car"
        ]
        assert len(lights) == 1

    assert result["frames"][0]["objects"][0]["geometry_source"] == (
        "object_bbox3d_spatial_persistence"
    )
    assert result["frames"][5]["objects"][0]["geometry_source"] == (
        "per_frame_bbox3d"
    )
