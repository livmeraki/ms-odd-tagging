from __future__ import annotations

from ms_odd_tagging.common.scenario_catalog import (
    load_scenario_catalog,
    scenario_names_for_method,
)
from ms_odd_tagging.qwen_vlm_poc.config import SCENARIOS, TRAFFIC_LIGHT_LABELS, VLM_GROUPS
from ms_odd_tagging.tagger.rule_based.registry import RULE_BASED_SCENARIOS


def test_catalog_is_unique_and_covers_current_methods() -> None:
    catalog = load_scenario_catalog()
    names = [entry.name for entry in catalog]

    assert len(names) == len(set(names))
    assert len(catalog) == 76
    assert len(scenario_names_for_method("rule")) == 40
    assert len(scenario_names_for_method("vlm")) == 14


def test_catalog_status_and_method_contract() -> None:
    for entry in load_scenario_catalog():
        if entry.status == "unsupported":
            assert not entry.methods
        else:
            assert entry.methods


def test_rule_registry_matches_catalog() -> None:
    assert set(RULE_BASED_SCENARIOS) == set(scenario_names_for_method("rule"))


def test_vlm_configuration_matches_catalog() -> None:
    configured_vlm = {
        label
        for labels in VLM_GROUPS.values()
        for label in labels
    }
    assert configured_vlm == set(scenario_names_for_method("vlm"))
    assert SCENARIOS == tuple(VLM_GROUPS)
    assert TRAFFIC_LIGHT_LABELS == VLM_GROUPS["traffic_light_episode"]
    assert "waiting_for_pedestrian_to_cross" in scenario_names_for_method("rule")
    assert "waiting_for_pedestrian_to_cross" in scenario_names_for_method("vlm")
