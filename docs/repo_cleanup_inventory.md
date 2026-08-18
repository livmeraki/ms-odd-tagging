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

`frame_input_builder.py` is the public dispatcher. The historical public modules remain compatibility entrypoints, and their original implementations are retained privately during this cleanup branch for rollback.

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
| Public canonical generation | `input_generator/canonical_builder.py` | Canonical | Always builds the ODLD schema; no mode selection | Keep |
| OD + trajectory core | `input_generator/canonical.py` | Internal core | Shared OD parsing, object, ego, and interaction semantics reused by ODLD | Keep internal; do not expose as a mode |
| LD augmentation | `input_generator/canonical_odld.py` | Canonical extension | Recording-static LD store, lane/topology/roadmark normalization, per-frame nearby references | Keep separate |
| Public frame-input generation | `input_generator/frame_input_builder.py` | Canonical | Chooses BEV style and implementation compatibility path | Keep |
| BEV renderer selection | `input_generator/bev_renderer.py` | Canonical | Single renderer API and metadata contract | Keep |
| Standard frame-input implementation | `_frame_input_standard_impl.py` via `frame_input.py` | Legacy/internal during migration | Exact historical behavior retained for rollback | Remove only after local/CI regression run |
| Explorer-aligned implementation | `_frame_input_explorer_aligned_impl.py` via `frame_input_revised.py` | Legacy/internal during migration | Exact historical revised behavior retained for rollback | Remove only after regression run |
| Rule-based tagging | `tagger/rule_based/` + `configs/direct_scenarios.yaml` | Canonical | Detector policies and event logic | Do not restructure in this pass |
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
| Lane continuation patch | `lane_continuation_current_working.patch` | Legacy artifact | May contain unique lane work not represented elsewhere | Do not delete until compared with current lane code |
| `brainstorm.md` | repository root | Historical design artifact | Contains project decisions and old architecture assumptions | Retain until provenance is summarized into docs |
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
2. Frame generation has a public `ms_odd_tagging.frame_inputs` package; old
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
