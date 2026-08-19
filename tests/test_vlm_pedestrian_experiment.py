from pathlib import Path

from ms_odd_tagging.vlm_understanding_poc.pedestrian_experiment_cli import _load, _validate_scene
from ms_odd_tagging.vlm_understanding_poc.pseudo_bev import SCENES, generate


def test_pseudo_bev_generator_and_manifest_contract(tmp_path: Path) -> None:
    paths = generate(tmp_path)
    assert len(paths) == 8
    assert {path.stem for path in paths} == set(SCENES)
    assert all(path.is_file() and path.stat().st_size > 1000 for path in paths)


def test_absent_pedestrian_ground_truth_is_logically_gated(tmp_path: Path) -> None:
    image = generate(tmp_path)[0]
    scene = {
        "scene_id": "negative",
        "expected_presence": "no",
        "expected_relation": "not_applicable",
        "expected_path_interaction": "no",
        "expected_waiting": "no",
    }
    _validate_scene(scene, image)
