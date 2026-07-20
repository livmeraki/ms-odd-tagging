# MS ODD Tagging

Modular autonomous-driving motional-scenario tagging from OD/LD annotations and ego trajectories.

```text
data/01_raw
  -> outputs/01_canonical
  -> outputs/02_windows
  -> outputs/03_model_inputs
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
- `outputs/02_windows/`: overlapping motional windows and rule candidates.
- `outputs/03_model_inputs/`: compact `refined.json` and BEV keyframes.
- `outputs/04_tagging/`: local/server model results.
- `outputs/05_validation/`: schema and semantic validation results.
- `outputs/06_gt_comparison/`: GT comparison reports.
- `src/ms_odd_tagging/input_generator/`: canonical, window, feature, BEV, and compaction code.
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

## Run stages 01-03

```bash
python run_pipeline.py --source-root data/01_raw \
  Rec_Drv_GER_MACHET18_20260227_153128
```

Use `--odld` for a recording containing `annotations_OD.json`, `annotations_LD.json`, and `traj_lcs.txt`. Add `--window-limit 1` for a fast smoke run or `--stop-after canonical|windows` while debugging.

Each stage is also independently executable:

```bash
python -m ms_odd_tagging.input_generator.canonical --help
python -m ms_odd_tagging.input_generator.canonical_odld --help
python -m ms_odd_tagging.input_generator.windows --help
python -m ms_odd_tagging.input_generator.model_input --help
python -m ms_odd_tagging.validator.schema --help
python -m ms_odd_tagging.tagger.model_based.local_vllm --help
```

## Important contracts

- Canonical schemas are `od-trajectory-canonical-frame-v1` and experimental `odld-trajectory-canonical-frame-v1`.
- Windows default to about 5 seconds with about 2.5-second stride.
- Formula/rule outputs stay in `preliminary_candidates`; model-facing `refined.json` excludes them by default to prevent label leakage.
- Numeric zero is valid data and must not become `null`.
- OD+LD BEV requires both `ld_feature_store` and frame-level `ld.nearby_feature_ids`.
- Unsupported semantic labels should remain unknown instead of being inferred from weak evidence.
- Generated artifacts, model weights, secrets, and machine-local configs are ignored by Git.

See [docs/audit.md](docs/audit.md) for migration provenance and [data/README.md](data/README.md) for data policy.
