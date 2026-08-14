# MS ODD Tagging

Modular autonomous-driving motional-scenario tagging from OD/LD annotations and ego trajectories.

The optional, isolated Lanelet2 ego/adjacent-lane proof of concept is documented
in [docs/lanelet2_poc.md](docs/lanelet2_poc.md). It remains disabled unless its
dedicated CLI receives `--enable-lanelet2-poc`.

```text
data/01_raw
  -> outputs/01_canonical
  -> outputs/02_frame_inputs
  -> outputs/04_tagging
  -> outputs/05_validation
  -> outputs/06_gt_comparison
```

The numbered data/output folders express execution order. Python package folders remain semantic because importable module names cannot begin with digits.

## Repository layout

- `configs/`: detector/pipeline configuration and PoC configuration.
- `data/01_raw/`: local OD/LD/trajectory recordings.
- `data/02_gt/`: ground-truth label files.
- `outputs/01_canonical/`: synchronized canonical frames.
- `outputs/02_frame_inputs/`: one `frame.json` and same-frame explorer-aligned BEV per selected timestamp.
- `outputs/04_tagging/`: local/server model results.
- `outputs/05_validation/`: schema and semantic validation results.
- `outputs/06_gt_comparison/`: GT comparison reports.
- `src/ms_odd_tagging/input_generator/`: canonicalization, per-frame model-input, feature, and BEV code.
- `src/ms_odd_tagging/tagger/`: rule-based and model-based tagging.
- `src/ms_odd_tagging/scenarios/`: scenario-specific geometry/detection pipelines such as following-lane.
- `src/ms_odd_tagging/validator/`: input/output validation and retry logic.
- `src/ms_odd_tagging/gt_comparison/`: GT label generation, matching, metrics, and reports.
- `src/ms_odd_tagging/*_poc/`: isolated research/experimental implementations; these are not canonical runtime ownership boundaries.

### Public input-generation boundaries

The public canonical entrypoint is `canonical_builder.py`:

- `--mode od`: OD annotations + trajectory using `canonical.py`.
- `--mode odld`: the same OD/trajectory semantics plus LD static-map normalization and per-frame LD spatial context using `canonical_odld.py`.

`canonical_odld.py` intentionally extends the OD canonicalizer; it is not an independent competing rewrite.

The public per-frame input entrypoint is `frame_input_builder.py`. It has one canonical BEV representation: `explorer_aligned`, centered on ego with ego heading up and metric-preserving x/y scale. There is no public BEV-style selector. By default, generated per-frame inputs are written to `outputs/02_frame_inputs` using a 900x1200 canvas for the default 90 m x 120 m centered physical extent.

The historical standard renderer remains only as an internal compatibility/helper layer while cleanup is in progress; it is not exposed as a selectable installed CLI.

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

Use `--canonical-mode odld` (or the compatibility alias `--odld`) for a recording containing `annotations_OD.json`, `annotations_LD.json`, and `traj_lcs.txt`. Add `--frame-limit 1` for a fast smoke run or `--stop-after canonical` while debugging. BEV/model inputs are sampled by real timestamps at 1 frame per second by default. Change this with `--frames-per-second 2` or use `--all-frames` when full-frame output is required. Dynamic rule tagging still evaluates every canonical frame.

The active per-frame renderer is always explorer-aligned:

```bash
python run_pipeline.py RECORDING --canonical-mode odld
```

Add `--profile-generation` to write optional generation timing, processing FPS,
and storage metrics under `outputs/02_frame_inputs/profiling`.

Each stage is independently executable through a stable public dispatcher:

```bash
python -m ms_odd_tagging.input_generator.canonical_builder --help
python -m ms_odd_tagging.input_generator.canonical_builder --mode odld RECORDING
python -m ms_odd_tagging.input_generator.frame_input_builder --help
python -m ms_odd_tagging.input_generator.frame_input_builder --recording RECORDING
python -m ms_odd_tagging.validator.frame_schema --help
python -m ms_odd_tagging.tagger.rule_based.registry --help
python -m ms_odd_tagging.visualization.scenario_explorer --help
```

The installed CLI equivalents are `ms-odd-canonical`, `ms-odd-frame-inputs`, and `ms-odd-tagging`.

Phase 1 deterministic trajectory events are calculated over the complete
recording and retain dynamic inclusive frame/time bounds. See
[docs/phase1_rule_based.md](docs/phase1_rule_based.md) for rules, provenance,
event semantics, and extension guidance.

Generate standalone tagged-scenario explorers from canonical JSON or a raw trajectory:

```bash
python -m ms_odd_tagging.visualization.scenario_explorer \
  outputs/01_canonical --output-dir outputs/07_scenario_explorers
```

## Per-frame model inference

```bash
python -m ms_odd_tagging.tagger.model_based.local_vllm \
  --recording RECORDING \
  --model-input-root outputs/02_frame_inputs \
  --output-root outputs/04_tagging \
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
  --output-dir outputs/07_odld_scenario_explorers_gt_authoring_all_tags \
  --frame-input-root outputs/02_frame_inputs \
  --gt-dir data/02_gt \
  --regenerate-existing
```

The integrated reviewer preserves the scenario filter and collapsed authoring
groups while moving between recordings in the same browser tab. It can also add
the explorer's exact current frame to the downloaded frame-GT JSON.

## Important contracts

- Canonical schemas remain `od-trajectory-canonical-frame-v1` and `odld-trajectory-canonical-frame-v1`.
- OD `frameIndex` maps directly to the trajectory row; LD is treated as a recording-level static map spatially queried at each ego pose.
- Every selected timestamp produces one independent `frame.json` and explorer-aligned BEV under `outputs/02_frame_inputs`; default selection is 1 FPS and there is no temporal window sampling in the active per-frame pipeline.
- Recording rule events are stored separately from model-facing frame JSON to prevent label leakage.
- Numeric zero is valid data and must not become `null`.
- OD+LD BEV requires both `ld_feature_store` and frame-level `ld.nearby_feature_ids`.
- Unsupported semantic labels should remain unknown instead of being inferred from weak evidence.
- Generated artifacts, model weights, secrets, and machine-local configs should not be committed.
- Lane/topology PoCs remain isolated until equivalence and ownership are proven on representative real recordings.

See [docs/audit.md](docs/audit.md) for migration provenance, [docs/repo_cleanup_inventory.md](docs/repo_cleanup_inventory.md) for cleanup decisions, and [data/README.md](data/README.md) for data policy.
