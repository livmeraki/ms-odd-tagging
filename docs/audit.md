# Source Audit

Active source locations used to build this repository on the server:

- `quick_exploration_outputs`
- `vllm_scenario_tagging`

Excluded material:

- raw annotation data
- generated canonical/window/model-input/output trees
- vLLM virtual environment
- logs, reports, model outputs, and BEV images
- `quick_exploration_outputs/experiments/smoothed_ego_kinematics`
- old Together API probing/evaluation scripts

The source scripts were migrated into the `ms_odd_tagging` package and adjusted for repository-relative paths, prompt/schema locations, and CLI-configurable roots.

The project handoff is historical context rather than an exact inventory. This repository intentionally does not claim that the predecessor's large raw/generated assets are present.
