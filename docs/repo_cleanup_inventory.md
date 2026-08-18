# Repository Cleanup Inventory

Branch purpose: safely consolidate duplicate implementations without losing behavior, experimental findings, evaluation tooling, or recoverability.

## Rules for this cleanup

1. Do not delete an implementation until its callers, unique behavior, tests, and replacement are identified.
2. Prefer one public entrypoint per responsibility. Internal implementations may remain separate when they represent genuinely different data or research modes.
3. Separate canonical runtime code, experiments, evaluation tools, visualization tools, and historical/legacy code.
4. Move questionable code before deleting it.
5. Make structural changes separately from algorithm changes.
6. Require regression checks before removing alternatives.
7. Preserve scenario names and unsupported/not-yet-implemented taxonomy entries explicitly rather than dropping them silently.

## Classification

| Status | Meaning | Cleanup action |
|---|---|---|
| Canonical | Intended current implementation/public boundary | Keep, simplify, test |
| Candidate | Possible replacement for canonical implementation | Compare before promotion |
| Experiment | PoC or research hypothesis | Isolate under experiment boundary |
| Tool | GT, evaluation, explorer, audit, conversion utility | Retain separately |
| Legacy | Superseded but may contain unique behavior or lessons | Archive temporarily |
| Dead | No unique behavior, callers, tests, or historical value | Delete only after verification |

## Decisions completed on this branch

### Canonical input generation

`canonical_builder.py` now exposes only OD+LD+trajectory canonicalization.
`canonical_odld.py` owns the supported schema and imports reusable OD/trajectory
parsing and geometry from `canonical.py`. The latter remains an internal shared
core, not a separately selectable mode. The main pipeline always calls this
single ODLD entrypoint.

### Per-frame BEV/input generation

The previous `frame_input.py` / `frame_input_revised.py` split represented two rendering modes with substantial shared behavior. A stable `bev_renderer.py` API now owns renderer selection:

- `standard`: existing model-facing rendering;
- `explorer_aligned`: centered explorer-aligned rendering.

`frame_inputs/builder.py` is the public dispatcher. Historical modules under `input_generator/` are compatibility aliases; active implementations now live in their owning packages.

### CLI ownership

`pyproject.toml` now exposes stable public commands:

- `ms-odd-canonical` -> ODLD canonical generation;
- `ms-odd-frame-inputs` -> frame-input dispatcher;
- `ms-odd-tagging` -> ordered ODLD pipeline.

The implementation-specific `ms-odd-canonical-od` and
`ms-odd-canonical-odld` aliases were removed so there is one public canonical
command.

### Root clutter

Generated root preview/speed PNGs were removed. The recording-specific speed diagnostic script was moved under `scripts/debug/`. `.gitignore` now prevents those generated images from being recommitted.

## Current inventory

| Responsibility / Feature | Current path | Status | Ownership / unique behavior | Action |
|---|---|---|---|---|
| Public canonical generation | `canonical/` | Canonical | Stable ODLD-only public boundary | Keep |
| OD + trajectory core | `canonical/core.py` | Internal core | Shared OD parsing, object, ego, and interaction semantics reused by ODLD | Keep internal; do not expose as a mode |
| LD augmentation | `canonical/odld.py` | Canonical extension | Recording-static LD store, lane/topology/roadmark normalization, per-frame nearby references | Keep separate |
| Public frame-input generation | `frame_inputs/` | Canonical | Stable explorer-aligned public boundary | Keep |
| BEV renderer selection | `frame_inputs/bev_renderer.py` | Canonical | Single renderer API and metadata contract | Keep |
| Standard frame-input implementation | `frame_inputs/_standard_impl.py` via `frame_inputs/standard.py` | Internal compatibility mode | Exact historical behavior retained behind the owning boundary | Keep while supported by regression tests |
| Explorer-aligned implementation | `frame_inputs/_explorer_aligned_impl.py` via `frame_inputs/explorer_aligned.py` | Canonical implementation | Active per-frame generation behavior | Keep |
| Rule-based tagging | `tagger/rule_based/` + `configs/scenario_catalog.csv` + `configs/direct_scenarios.yaml` | Canonical | Unified scenario catalog, detector registry, and thresholds | Keep catalog as source of truth |
| Shared features | `features/` | Canonical | Cross-detector reusable relations/motion/context | Keep; future duplicate-utility audit |
| Following-lane | `scenarios/following_lane/` | Canonical/candidate | Active physical lane/lead logic with extensive tests | High risk; defer consolidation |
| LD topology | `ld_topology/` | Experiment/candidate | Independent topology/intersection approach | Keep isolated until equivalence is proven |
| BEV lane PoC | `bev_lane_poc/` | Experiment | Separate lane reconstruction hypothesis | Keep isolated |
| Lanelet2 PoC | `lanelet2_poc/` | Experiment | Optional Lanelet2-based approach/dependency | Keep isolated |
| Qwen VLM PoC | `qwen_vlm_poc/` | Experiment/candidate | Scenario-specific prompts/evidence/candidate generation/review | Keep separate from generic model tagger |
| Generic local model tagger | `tagger/model_based/local_vllm.py` | Legacy/canonical compatibility | Older general model-facing inference path | Do not delete without downstream caller audit |
| GT comparison/authoring | `gt_comparison/` | Tool | Evaluation and authoring, not detector ownership | Preserve |
| Visualization | `visualization/` + package-specific overlays | Tool | Generic explorer plus algorithm-specific debug overlays | Preserve; avoid premature merge |
| ODLD explorer scripts | `scripts/odld_explorer/` | Tool/legacy mixture | Large authoring/debug/generator scripts with potentially unique behavior | Needs separate entrypoint audit; no deletion this pass |
| Root compatibility wrappers | `run_*.py` | Compatibility | Convenient source-tree execution, especially without install | Keep for now; `run_pipeline.py` is documented |
| Lane continuation patch | `docs/archive/lane_continuation_current_working.patch` | Legacy artifact | Preserved for comparison without cluttering the repository root | Compare before deletion |
| Historical brainstorm | `docs/archive/brainstorm.md` | Historical design artifact | Preserved outside the runtime/documentation entry path | Retain as archive |
| `artifacts/*.txt` | repository root artifact folder | Artifact | Generated prediction lists may support retrospective/debugging | Do not delete without caller/provenance check |

## Regression gate before removal

Before deleting or replacing an implementation, verify where applicable:

- imports and installed CLI entrypoints succeed;
- the ODLD canonical frame schema remains stable;
- one representative ODLD recording runs end-to-end;
- standard and explorer-aligned per-frame output metadata remains stable;
- detector/unit tests pass;
- GT comparison/authoring still works;
- old and cleaned outputs are compared on a small fixture;
- lane/topology real-recording tests pass before any lane implementation is retired;
- intentional differences are documented rather than hidden.

## Deliberately deferred high-risk cleanup

### Lane reconstruction / lane topology

Do not merge `following_lane`, `ld_topology`, `bev_lane_poc`, or `lanelet2_poc` merely because they operate on similar LD geometry. They encode different assumptions about physical lane assignment, route continuity, topology, and dependencies. Consolidation requires representative-recording equivalence evidence first.

### Scenario registry and policies

Do not move thresholds from `configs/direct_scenarios.yaml` or rewrite detector registration during a structural cleanup. Detector policy changes would make regression attribution difficult.

### VLM pipeline

Do not collapse `qwen_vlm_poc` into `tagger/model_based/local_vllm.py` yet. The former contains scenario-specific evidence construction and experimental candidate generation; the latter is a generic model-facing path. First identify the long-term inference contract, then migrate reusable client/validation utilities.

## Practical target architecture after this pass

```text
src/ms_odd_tagging/
├── common/
├── input_generator/
│   ├── canonical_builder.py      # public ODLD entrypoint
│   ├── canonical.py              # internal OD/trajectory core
│   ├── canonical_odld.py         # supported ODLD schema
│   ├── frame_input_builder.py    # public per-frame dispatcher
│   ├── bev_renderer.py           # renderer ownership
│   └── ...
├── features/                     # shared deterministic features
├── scenarios/                    # supported scenario-specific pipelines
├── tagger/
│   ├── rule_based/
│   └── model_based/
├── gt_comparison/                # evaluation/authoring tools
├── visualization/                # generic visualization
├── qwen_vlm_poc/                 # explicit experiment
├── bev_lane_poc/                 # explicit experiment
├── lanelet2_poc/                 # explicit experiment
└── ld_topology/                  # explicit candidate/experiment
```

This is intentionally less aggressive than a wholesale directory rewrite. The current repository already has useful semantic boundaries; the main cleanup need is explicit ownership and stable entrypoints, not moving every file.


## Boundary resolution pass

The seven repository-boundary issues now have explicit, testable decisions:

1. Canonicalization has a public `ms_odd_tagging.canonical` package.
2. Frame generation is physically owned by `ms_odd_tagging.frame_inputs`; old
   standard/revised modules are compatibility internals and the standard path is
   retained only as a regression oracle.
3. `ms_odd_tagging.geometry` records one owner and lifecycle status per geometry
   capability instead of pretending the lane approaches are interchangeable.
4. `ms_odd_tagging.scenarios` records production, candidate, feature, and
   experiment ownership.
5. `ms_odd_tagging.vlm` owns transport-neutral contracts and backend status;
   scenario prompts and Qwen evidence remain experimental.
6. `ms_odd_tagging.evaluation` and `ms_odd_tagging.visualization` are the tool
   boundaries; GT comparison remains a compatibility implementation package.
7. `ms-odd` is the unified command surface. Existing commands remain aliases
   during migration.

These decisions are enforced by `test_architecture_boundaries.py` and documented
in `docs/canonical_paths.md`. They do not claim output equivalence between
independent lane experiments, so no high-risk algorithm was deleted.


## Final low-risk hygiene pass

- Removed two generated 15 MB manual-tagging HTML exports from the repository root.
- Removed the incomplete tracked raw LD/trajectory sample; raw recordings are now
  uniformly ignored and runnable tests use small fixtures or external data.
- Moved the historical brainstorm and lane-continuation patch under
  `docs/archive/`.
- Made all supported unit tests required in CI. LD-topology candidate tests run
  separately and remain advisory until their algorithm is reconciled.
- Fixed explorer thumbnail generation for older/minimal payloads that omit
  trajectory `x`/`y` arrays.
