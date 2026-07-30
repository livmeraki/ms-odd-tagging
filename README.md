# MS ODD Tagging

Modular autonomous-driving motional-scenario tagging from OD/LD annotations and ego trajectories.

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

- `configs/`: machine-specific configuration examples (documentation only).
- `data/01_raw/`: local OD/LD/trajectory recordings.
- `data/02_gt/`: ground-truth label files.
- `outputs/01_canonical/`: synchronized canonical frames.
- `outputs/02_frame_inputs/`: one `frame.json` and same-frame `bev.png` per selected timestamp.
- `outputs/04_tagging/`: local/server model results.
- `outputs/05_validation/`: schema and semantic validation results.
- `outputs/06_gt_comparison/`: GT comparison reports.
- `src/ms_odd_tagging/input_generator/`: canonical, per-frame model-input, feature, and BEV code.
- `src/ms_odd_tagging/tagger/`: rule-based and model-based tagging.
- `src/ms_odd_tagging/validator/`: input/output validation and retry logic.
- `src/ms_odd_tagging/gt_comparison/`: GT label generation, matching, metrics, and reports.

The OD-only and OD+LD canonicalizers remain separate until their experimental differences are deliberately reconciled.

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

Use `--odld` for a recording containing `annotations_OD.json`, `annotations_LD.json`, and `traj_lcs.txt`. Add `--frame-limit 1` for a fast smoke run or `--stop-after canonical` while debugging. BEV/model inputs are sampled by real timestamps at 1 frame per second by default. Change this with `--frames-per-second 2` or use `--all-frames` when full-frame output is required. Dynamic rule tagging still evaluates every canonical frame.

Add `--profile-generation` to write optional generation timing, processing FPS,
and storage metrics under `outputs/02_frame_inputs/profiling/`.

Each stage is also independently executable:

```bash
python -m ms_odd_tagging.input_generator.canonical --help
python -m ms_odd_tagging.input_generator.canonical_odld --help
python -m ms_odd_tagging.input_generator.frame_input --help
python -m ms_odd_tagging.validator.frame_schema --help
python -m ms_odd_tagging.tagger.model_based.local_vllm --help
python -m ms_odd_tagging.tagger.rule_based.registry --help
python -m ms_odd_tagging.visualization.scenario_explorer --help
```

Phase 1 deterministic trajectory events are calculated over the complete
recording and retain dynamic inclusive frame/time bounds. See
[docs/phase1_rule_based.md](docs/phase1_rule_based.md) for rules, provenance,
event semantics, and extension guidance.

An additive revised BEV experiment keeps the 95 m ahead / 25 m behind,
ego-heading-up camera while aligning OD/LD geometry handling with the explorer:

```bash
python -m ms_odd_tagging.input_generator.frame_input_revised \
  --frames-per-second 1
```

It does not replace the current generator. It also writes
`outputs/02_frame_inputs_revised/revised_bev_review.html`. Revised BEVs annotate
ego speed/velocity, the latest logical-lane and stable-lead
assignments, and the configured 30.0 m ego-footprint proximity boundary.

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

## Per-frame ground-truth review

Generate one browser reviewer per recording from the sampled frame inputs (1 FPS
by default, or whichever rate was selected upstream):

```bash
python -m ms_odd_tagging.gt_comparison.authoring \
  --frame-input-root outputs/02_frame_inputs_revised \
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
The reviewer groups all implemented Phase 1–3C scenarios, keeps future taxonomy
labels available but marked unsupported, and shows active-event evidence,
ego/lane state, and nearby dynamic-object kinematics beside the synchronized
BEV. Source frames 0–4 are visibly disabled and excluded from scoring because
their detections are unreliable.
Traffic-light splits, slow-lead semantics, stopping split by lead, and
lane-change lead/trail semantics remain unknown until dedicated rules exist.

## Important contracts

- Canonical schemas are `od-trajectory-canonical-frame-v1` and experimental `odld-trajectory-canonical-frame-v1`.
- Every selected timestamp produces one independent `frame.json` and `bev.png`; default selection is 1 FPS and there is no temporal window sampling.
- Recording rule events are stored separately from model-facing frame JSON to prevent label leakage.
- Numeric zero is valid data and must not become `null`.
- OD+LD BEV requires both `ld_feature_store` and frame-level `ld.nearby_feature_ids`.
- Unsupported semantic labels should remain unknown instead of being inferred from weak evidence.
- Generated artifacts, model weights, secrets, and machine-local configs are ignored by Git.

See [docs/audit.md](docs/audit.md) for migration provenance and [data/README.md](data/README.md) for data policy.
