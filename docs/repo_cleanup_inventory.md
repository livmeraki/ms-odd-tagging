# Repository Cleanup Inventory

Branch purpose: safely consolidate duplicate implementations without losing behavior, experimental findings, evaluation tooling, or recoverability.

## Rules for this cleanup

1. Do not delete an implementation until its callers, unique behavior, tests, and replacement are identified.
2. Prefer one canonical implementation per responsibility. Avoid suffix-based forks such as `_v2`, `_new`, `_revised`, `_fixed`, and `_final` in the final architecture.
3. Separate canonical runtime code, experiments, evaluation tools, visualization tools, and historical/legacy code.
4. Move questionable code before deleting it.
5. Make structural changes separately from algorithm changes.
6. Require regression checks before removing alternatives.
7. Preserve scenario names and unsupported/not-yet-implemented taxonomy entries explicitly rather than dropping them silently.

## Classification

| Status | Meaning | Cleanup action |
|---|---|---|
| Canonical | Intended current implementation | Keep, simplify, test |
| Candidate | Possible replacement for canonical implementation | Compare before promotion |
| Experiment | PoC or research hypothesis | Isolate under experiment boundary |
| Tool | GT, evaluation, explorer, audit, conversion utility | Retain separately |
| Legacy | Superseded but may contain unique behavior or lessons | Archive temporarily |
| Dead | No unique behavior, callers, tests, or historical value | Delete only after verification |

## High-risk areas

### Lane reconstruction / lane topology
Treat as highest risk and clean late. Multiple approaches may encode different behavior for lane polygon construction, boundary validation and fallback geometry, lane continuation/merging, physical ego-lane assignment versus logical route continuity, intersection/topology classification, and visualization-specific fixes.

### Scenario detection
For every scenario, inventory detector path, method type (rule / hybrid / VLM), inputs, thresholds/config, output schema, tests, runtime entrypoint, and duplicate/alternate implementations.

### VLM pipeline
Keep experimental model/prompt/input variants distinguishable from the canonical runtime path. Do not consolidate materially different evidence construction or candidate-generation strategies simply because they emit the same schema.

## Inventory table

| Responsibility / Feature | Path | Status | Method | Called by | Tests | Unique behavior | Proposed canonical path | Action |
|---|---|---|---|---|---|---|---|---|
| Canonical frame generation | TBD | TBD | OD/LD normalization | TBD | TBD | TBD | `src/ms_odd_tagging/canonical/` | Inspect |
| Lane geometry | TBD | TBD | Geometry/rules | TBD | TBD | TBD | `src/ms_odd_tagging/geometry/lane/` | Inspect last |
| Intersection topology | TBD | TBD | Geometry/rules | TBD | TBD | TBD | `src/ms_odd_tagging/geometry/topology/` | Inspect last |
| Scenario detectors | TBD | TBD | Rule/hybrid/VLM | TBD | TBD | TBD | `src/ms_odd_tagging/scenarios/` | Inventory individually |
| VLM inference | TBD | TBD | VLM | TBD | TBD | TBD | `src/ms_odd_tagging/vlm/` | Compare variants |
| Evaluation / GT | TBD | Tool | Evaluation | TBD | TBD | TBD | `src/ms_odd_tagging/evaluation/` or `tools/` | Retain |
| Visualization / Explorer | TBD | Tool | Visualization | TBD | TBD | TBD | `src/ms_odd_tagging/visualization/` or `tools/` | Consolidate carefully |
| One-off debug scripts | TBD | TBD | Debug | TBD | TBD | TBD | `experiments/` or delete | Trace callers |

## Regression gate before removal

Before deleting or replacing an implementation, verify where applicable: imports succeed; CLI entrypoints still work; canonical frame generation still works; one representative recording runs end-to-end; output JSON/schema remains compatible; detector/unit tests pass; evaluation/GT tooling still works; old and cleaned outputs are compared on a small fixture; and any intentional output difference is documented.

## Recommended commit sequence

1. `chore: add repository cleanup inventory`
2. `refactor: establish canonical package boundaries`
3. `refactor: consolidate duplicate utilities`
4. `refactor: consolidate scenario registry and configuration`
5. `refactor: consolidate visualization and evaluation tooling`
6. `refactor: consolidate VLM pipeline`
7. `refactor: consolidate lane and topology implementation`
8. `chore: archive superseded experimental code`
9. `test: add cleanup regression fixtures`
10. `chore: remove verified dead code`

## Target architecture (directional, not yet approved)

```text
src/ms_odd_tagging/
├── canonical/
├── geometry/
│   ├── lane/
│   └── topology/
├── scenarios/
│   ├── dynamics/
│   ├── behavior/
│   ├── interaction/
│   ├── maneuver/
│   └── zone/
├── vlm/
├── evaluation/
├── visualization/
└── cli/
```

This layout is a cleanup hypothesis only. Do not move code into it until the inventory identifies existing runtime dependencies.
