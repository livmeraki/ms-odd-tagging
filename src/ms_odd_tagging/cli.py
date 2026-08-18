"""One installed command surface for production, tools, and experiments."""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Command:
    target: str
    category: str
    description: str


COMMANDS: dict[str, Command] = {
    "pipeline": Command("ms_odd_tagging.pipeline:main", "production", "Run canonical and frame-input stages."),
    "canonical": Command("ms_odd_tagging.canonical.builder:main", "production", "Build canonical OD+LD recording JSON."),
    "frame-inputs": Command("ms_odd_tagging.frame_inputs.builder:main", "production", "Build sampled frame JSON and BEVs."),
    "validate-frames": Command("ms_odd_tagging.validator.frame_schema:main", "tool", "Validate generated frame inputs."),
    "tag": Command("ms_odd_tagging.tagger.model_based.local_vllm:main", "candidate", "Run local model-based tagging."),
    "rules": Command("ms_odd_tagging.tagger.rule_based.registry:main", "production", "Run deterministic scenario detectors."),
    "explore": Command("ms_odd_tagging.visualization.scenario_explorer:main", "tool", "Build the generic scenario explorer."),
    "frame-gt-review": Command("ms_odd_tagging.gt_comparison.authoring:main", "tool", "Run frame GT review/authoring."),
    "evaluate-rules": Command("ms_odd_tagging.evaluation.rule_based:main", "tool", "Compare rule output with GT."),
    "following-lane": Command("ms_odd_tagging.scenarios.following_lane.pipeline:main", "production", "Run following-lane analysis."),
    "qwen-poc": Command("ms_odd_tagging.qwen_vlm_poc.cli:main", "experiment", "Run the Qwen VLM experiment."),
    "qwen-review": Command("ms_odd_tagging.qwen_vlm_poc.visualization:main", "experiment", "Review Qwen experiment output."),
    "lanelet2-poc": Command("ms_odd_tagging.lanelet2_poc.cli:main", "experiment", "Run Lanelet2 lane experiment."),
    "bev-lane-poc": Command("ms_odd_tagging.bev_lane_poc.cli:main", "experiment", "Run BEV lane experiment."),
    "ld-topology": Command("ms_odd_tagging.ld_topology.cli:main", "candidate", "Run LD topology candidate."),
}


def _usage() -> str:
    lines = ["usage: ms-odd <command> [arguments]", "", "commands:"]
    width = max(len(name) for name in COMMANDS)
    for name, command in COMMANDS.items():
        lines.append(f"  {name:<{width}}  [{command.category}] {command.description}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] in {"-h", "--help"}:
        print(_usage())
        return 0

    name = arguments.pop(0)
    command = COMMANDS.get(name)
    if command is None:
        print(f"ERROR: unknown command {name!r}\n\n{_usage()}", file=sys.stderr)
        return 2

    module_name, attribute = command.target.split(":", 1)
    target = getattr(importlib.import_module(module_name), attribute)
    previous = sys.argv
    try:
        sys.argv = [f"ms-odd {name}", *arguments]
        result = target()
    finally:
        sys.argv = previous
    return 0 if result is None else int(result)


if __name__ == "__main__":
    raise SystemExit(main())
