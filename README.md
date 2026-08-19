# MS ODD Tagging

Modular autonomous-driving motional-scenario tagging from OD/LD annotations and ego trajectories.

The optional, isolated Lanelet2 ego/adjacent-lane proof of concept is documented
in [docs/lanelet2_poc.md](docs/lanelet2_poc.md). It remains disabled unless its
dedicated CLI receives `--enable-lanelet2-poc`.

```text
data/01_raw
  -> outputs/01_canonical
  -> outputs/02_frame_inputs
  -> outputs/03_tagging
  -> outputs/04_validation
  -> outputs/05_gt_comparison
```

The numbered data/output folders express execution order. Python package folders remain semantic because importable module names cannot begin with digits. The older window-based model-input pipeline is retained only under `outputs/legacy/` and is not part of the active stage numbering.

## Repository layout

- `configs/`: detector/pipeline configuration and PoC configuration.
- `data/01_raw/`: local OD/LD/trajectory recordings.
- `data/02_gt/`: ground-truth label files.
- `outputs/01_canonical/`: synchronized canonical frames.
- `outputs/02_frame_inputs/`: one `frame.json` and same-frame explorer-aligned `bev.png` per selected timestamp.
- `outputs/03_tagging/`: local/server model results.
- `outputs/04_validation/`: schema and semantic validation results.
- `outputs/05_gt_comparison/`: GT comparison reports.
- `outputs/06_scenario_explorers/`: generated scenario-review explorers.
- `outputs/legacy/`: compatibility outputs for the deprecated window/refined model-input path.
- `src/ms_odd_tagging/canonical/`: public OD+LD+trajectory normalization boundary.
- `src/ms_odd_tagging/frame_inputs/`: public per-frame JSON and BEV generation boundary.
- `src/ms_odd_tagging/input_generator/`: deprecated compatibility aliases plus the legacy window pipeline; active canonical and frame-input implementations live in their owning packages.
- `src/ms_odd_tagging/tagger/`: rule-based and model-based tagging.
- `src/ms_odd_tagging/scenarios/`: scenario-specific geometry/detection pipelines such as following-lane.
- `src/ms_odd_tagging/validator/`: input/output validation and retry logic.
- `src/ms_odd_tagging/evaluation/`: public evaluation boundary.
- `src/ms_odd_tagging/gt_comparison/`: compatibility GT authoring/comparison implementations.
- `src/ms_odd_tagging/geometry/`: geometry implementation ownership and lifecycle registry.
- `src/ms_odd_tagging/vlm/`: transport-neutral VLM contracts and backend registry.
- `src/ms_odd_tagging/*_poc/`: isolated research/experimental implementations; these are not canonical runtime ownership boundaries.

### Public input-generation boundaries

The public canonical boundary is `ms_odd_tagging.canonical`. It always builds
the OD+LD+trajectory schema. The former OD-only mode is not exposed because the
supported tagging pipeline depends on LD context.

`canonical/core.py` is the internal shared core for OD/trajectory parsing and geometry used by `canonical/odld.py`; it is not a separate user-facing pipeline.

The public per-frame boundary is `ms_odd_tagging.frame_inputs`. It always
generates the centered, ego-heading-up `explorer_aligned` BEV and writes to
`outputs/02_frame_inputs` by default. The previous standard/revised renderer
choice is no longer exposed by the active pipeline.

Explorer-aligned generation and its shared helpers are physically owned by `frame_inputs/`. Legacy `input_generator` module names remain import-compatible aliases only.

## Install and validate

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

Without installation, set `PYTHONPATH=src` (PowerShell: `$env:PYTHONPATH = "src"`).

## Run the per-frame input pipeline

```bash
python run_pipeline.py Rec_Drv_GER_MACHET18_20260227_153128
```

By default, data and outputs are read/written under repo-local `data/` and
`outputs/`. For a machine-specific external data disk, create ignored `.env`
values or export them before running:

```bash
export MS_ODD_DATA_ROOT=/path/to/ms-odd-tagging-data/data
export MS_ODD_OUTPUT_ROOT=/path/to/ms-odd-tagging-data/outputs
```

Every recording must contain `annotations_OD.json`, `annotations_LD.json`, and
`traj_lcs.txt`; ODLD canonicalization is always used. Add `--frame-limit 1` for
a fast smoke run or `--stop-after canonical` while debugging. BEV/model inputs
are sampled by real timestamps at 1 frame per second by default. Change this with
`--frames-per-second 2` or use `--all-frames` when full-frame output is
required. Dynamic rule tagging still evaluates every canonical frame.

Add `--profile-generation` to write optional generation timing, processing FPS,
and storage metrics under `outputs/02_frame_inputs`.

Each stage is independently executable through a stable public dispatcher:

```bash
ms-odd --help
ms-odd canonical --help
ms-odd canonical RECORDING
ms-odd frame-inputs --help
ms-odd frame-inputs --recording RECORDING
python -m ms_odd_tagging.validator.frame_schema --help
python -m ms_odd_tagging.tagger.rule_based.registry --help
python -m ms_odd_tagging.visualization.scenario_explorer --help
```

The older `ms-odd-canonical`, `ms-odd-frame-inputs`, and `ms-odd-tagging` commands remain compatibility aliases.

Deterministic trajectory events are calculated over the complete recording and retain dynamic inclusive frame/time bounds. See [docs/phase1_rule_based.md](docs/phase1_rule_based.md) for the historical implementation notes, rule provenance, event semantics, and extension guidance.

Generate standalone tagged-scenario explorers from canonical JSON or a raw trajectory:

```bash
python -m ms_odd_tagging.visualization.scenario_explorer \
  outputs/01_canonical --output-dir outputs/06_scenario_explorers
```

This is also available as `ms-odd explore`. It is the canonical generic
visualization command. The richer event-tag and per-frame-tag ODLD generators
under `scripts/odld_explorer/` remain specialized developer tools with distinct
input contracts; see [docs/visualization_tools.md](docs/visualization_tools.md).

## Per-frame model inference

```bash
python -m ms_odd_tagging.tagger.model_based.local_vllm \
  --recording RECORDING \
  --model-input-root outputs/02_frame_inputs \
  --output-root outputs/03_tagging \
  --endpoint http://127.0.0.1:8001/v1/chat/completions
```

`tagger/model_based/local_vllm.py` is the older general model-facing tagger. `qwen_vlm_poc/` remains a separate research package because it contains scenario-specific prompts, evidence construction, candidate generation, validation, and review tooling that should not be silently merged into the canonical tagger.

## Per-frame ground-truth review

Generate one browser reviewer per recording from the sampled frame inputs (1 FPS
by default, or whichever rate was selected upstream):

```bash
python -m ms_odd_tagging.gt_comparison.authoring \
  --frame-input-root outputs/02_frame_inputs \
  --output-root outputs/frame_gt_authoring \
  --all
```

Open `outputs/frame_gt_authoring/index.html`. Each review item displays the one
BEV belonging to that exact source frame. Labels autosave in the browser and
download as `<recording>_frame_gt.json`; no motional windows, median speed, or
start/middle/end keyframes are used. Legacy window helpers remain importable for
old datasets but are not used by this reviewer or the active pipeline.
Deterministic recording rules plus the current lane/lead tracker are stored in
per-frame `gt_reference.json` sidecars and prefill directly derivable labels.
The reviewer groups implemented scenarios, keeps future taxonomy labels available but marked unsupported, and shows active-event evidence, ego/lane state, and nearby dynamic-object kinematics beside the synchronized BEV. Source frames 0–4 are visibly disabled and excluded from scoring because their detections are unreliable.
Traffic-light splits, slow-lead semantics, stopping split by lead, and lane-change lead/trail semantics remain unknown until dedicated rules exist.

To duplicate the full tagged ODLD + lane debugger and author GT directly at its
current synchronized frame:

```bash
python scripts/odld_explorer/add_gt_authoring_to_tagged_explorers.py \
  --source-dir outputs/scenarios/following_lane_phase2_all_tags/04_visualization \
  --output-dir outputs/06_odld_scenario_explorers_gt_authoring_all_tags \
  --frame-input-root outputs/02_frame_inputs \
  --gt-dir data/02_gt \
  --regenerate-existing
```

The integrated reviewer preserves the scenario filter and collapsed authoring
groups while moving between recordings in the same browser tab. It can also add
the explorer's exact current frame to the downloaded frame-GT JSON.

## Important contracts

- The canonical schema is `odld-trajectory-canonical-frame-v1`.
- OD `frameIndex` maps directly to the trajectory row; LD is treated as a recording-level static map spatially queried at each ego pose.
- Every selected timestamp produces one independent `frame.json` and BEV; default selection is 1 FPS and there is no temporal window sampling in the active per-frame pipeline.
- Recording rule events are stored separately from model-facing frame JSON to prevent label leakage.
- Numeric zero is valid data and must not become `null`.
- OD+LD BEV requires both `ld_feature_store` and frame-level `ld.nearby_feature_ids`.
- Unsupported semantic labels should remain unknown instead of being inferred from weak evidence.
- Generated artifacts, model weights, secrets, and machine-local configs should not be committed.
- Lane/topology PoCs remain isolated until equivalence and ownership are proven on representative real recordings.

See [docs/audit.md](docs/audit.md) for migration provenance, [docs/repo_cleanup_inventory.md](docs/repo_cleanup_inventory.md) for cleanup decisions, and [data/README.md](data/README.md) for data policy.
