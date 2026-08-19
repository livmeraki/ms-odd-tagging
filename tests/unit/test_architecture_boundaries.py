from __future__ import annotations

import importlib

import tomllib
from pathlib import Path

from ms_odd_tagging.cli import COMMANDS
from ms_odd_tagging.geometry import GEOMETRY_OWNERS
from ms_odd_tagging.scenarios import SCENARIO_OWNERS
from ms_odd_tagging.vlm import VLM_BACKENDS, VLMRequest


ROOT = Path(__file__).resolve().parents[2]


def test_public_input_packages_are_the_installed_boundaries() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = project["project"]["scripts"]
    assert scripts["ms-odd"] == "ms_odd_tagging.cli:main"
    assert scripts["ms-odd-canonical"] == "ms_odd_tagging.canonical.builder:main"
    assert scripts["ms-odd-frame-inputs"] == "ms_odd_tagging.frame_inputs.builder:main"


def test_pipeline_uses_public_stage_boundaries() -> None:
    source = (ROOT / "src/ms_odd_tagging/pipeline.py").read_text(encoding="utf-8")
    assert "ms_odd_tagging.canonical.builder" in source
    assert "ms_odd_tagging.frame_inputs.builder" in source
    assert "input_generator.canonical_builder" not in source
    assert "input_generator.frame_input_builder" not in source


def test_ownership_registries_keep_experiments_explicit() -> None:
    assert GEOMETRY_OWNERS["following_lane"].status == "canonical"
    assert GEOMETRY_OWNERS["bev_lane"].status == "experiment"
    assert GEOMETRY_OWNERS["lanelet2"].status == "experiment"
    assert SCENARIO_OWNERS["direct_rule_based"].status == "canonical"
    assert SCENARIO_OWNERS["qwen_vlm"].status == "experiment"
    assert VLM_BACKENDS["qwen-poc"].status == "experiment"


def test_unified_cli_classifies_every_command() -> None:
    assert COMMANDS["pipeline"].category == "production"
    assert COMMANDS["evaluate-rules"].category == "tool"
    assert COMMANDS["qwen-poc"].category == "experiment"
    assert all(command.target.count(":") == 1 for command in COMMANDS.values())


def test_shared_vlm_contract_does_not_encode_scenario_policy() -> None:
    request = VLMRequest(system_prompt="system", user_prompt="user")
    assert request.image_paths == ()
    assert request.metadata == {}


def test_legacy_input_generator_modules_alias_their_canonical_owners() -> None:
    aliases = {
        "ms_odd_tagging.input_generator.canonical": "ms_odd_tagging.canonical.core",
        "ms_odd_tagging.input_generator.canonical_odld": "ms_odd_tagging.canonical.odld",
        "ms_odd_tagging.input_generator.canonical_builder": "ms_odd_tagging.canonical.builder",
        "ms_odd_tagging.input_generator.frame_input": "ms_odd_tagging.frame_inputs.standard",
        "ms_odd_tagging.input_generator.frame_input_revised": "ms_odd_tagging.frame_inputs.explorer_aligned",
        "ms_odd_tagging.input_generator.frame_input_builder": "ms_odd_tagging.frame_inputs.builder",
        "ms_odd_tagging.input_generator.bev_renderer": "ms_odd_tagging.frame_inputs.bev_renderer",
        "ms_odd_tagging.input_generator.revised_bev": "ms_odd_tagging.frame_inputs.revised_bev",
    }
    for legacy_name, owner_name in aliases.items():
        assert importlib.import_module(legacy_name) is importlib.import_module(owner_name)


def test_verified_dead_facades_stay_removed() -> None:
    removed = (
        "src/ms_odd_tagging/common/io.py",
        "src/ms_odd_tagging/input_generator/bev.py",
        "src/ms_odd_tagging/input_generator/compaction.py",
        "src/ms_odd_tagging/input_generator/features.py",
        "src/ms_odd_tagging/input_generator/sampler.py",
        "src/ms_odd_tagging/tagger/event_segmentation.py",
    )
    assert all(not (ROOT / relative_path).exists() for relative_path in removed)


def test_production_source_avoids_moved_input_generator_modules() -> None:
    forbidden = (
        "input_generator.canonical",
        "input_generator.canonical_odld",
        "input_generator.canonical_builder",
        "input_generator.frame_input",
        "input_generator.frame_input_revised",
        "input_generator.frame_input_builder",
        "input_generator.bev_renderer",
        "input_generator.revised_bev",
    )
    source_root = ROOT / "src/ms_odd_tagging"
    for path in source_root.rglob("*.py"):
        if "input_generator" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        for module_name in forbidden:
            assert module_name not in source, f"{module_name} imported by {path}"
