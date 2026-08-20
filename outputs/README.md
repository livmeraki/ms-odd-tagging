# Outputs Directory

Generated artifacts follow the active execution order:

1. `01_canonical/`
2. `02_frame_inputs/`
3. `03_tagging/`
4. `04_validation/`
5. `05_gt_comparison/`
6. `06_scenario_explorers/`
   - `odld/`: full tagged OD+LD explorers
   - `gt_authoring/`: integrated frame-GT authoring explorers
   - `gt_comparison/`: GT comparison explorers
   - `reviews/`: task-specific review pages

Deprecated window and model-input artifacts belong under `legacy/`; they are
not active numbered stages. Runtime logs belong under `runtime_logs/`.

Everything under `outputs/` is ignored except this file and tracked
placeholder files.
