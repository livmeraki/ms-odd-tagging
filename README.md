# MS ODD Tagging

Autonomous-driving Motional Scenario tagging from OD/LD annotations and ego trajectory.

## Repository layout

```text
configs/                  scenario and pipeline configuration
data/                     local input layout and data policy
docs/                     handover and technical documentation
prompts/                  VLM prompts
scripts/                  operational and visualization scripts
src/ms_odd_tagging/       Python package
 tests/                    automated tests
```

The active input path is:

```text
annotations_OD.json + annotations_LD.json + traj_lcs.txt
        ↓
Canonicalization
        ↓
outputs/01_canonical
        ↓
Frame Input / BEV generation
        ↓
outputs/02_frame_inputs
```

The canonical schema is `odld-trajectory-canonical-frame-v1`.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

After installation, use the package CLIs rather than repository-root wrapper scripts.

## Run the pipeline

```bash
ms-odd-tagging <RECORDING_ID>
```

Smoke test:

```bash
ms-odd-tagging <RECORDING_ID> --frame-limit 1
```

Useful options:

```bash
ms-odd-tagging <RECORDING_ID> --frames-per-second 2
ms-odd-tagging <RECORDING_ID> --all-frames
ms-odd-tagging <RECORDING_ID> --existing-output resume
ms-odd-tagging <RECORDING_ID> --existing-output regenerate
ms-odd-tagging <RECORDING_ID> --stop-after canonical
```

Data and output roots can be supplied through environment variables:

```bash
export MS_ODD_DATA_ROOT=/path/to/data
export MS_ODD_OUTPUT_ROOT=/path/to/outputs
```

Each recording under `$MS_ODD_DATA_ROOT/01_raw/<RECORDING_ID>/` must contain:

```text
annotations_OD.json
annotations_LD.json
traj_lcs.txt
```

## Main CLIs

```bash
ms-odd-tagging --help
ms-odd-canonical --help
ms-odd-frame-inputs --help
ms-odd-rules --help
ms-odd-ld-topology --help
ms-odd-qwen-vlm-poc --help
```

`ms-odd-tagging` maps directly to `ms_odd_tagging.pipeline:main`, and `ms-odd-ld-topology` maps directly to `ms_odd_tagging.ld_topology.cli:main` through `pyproject.toml`.

## Full ODLD Scenario Explorer

```bash
python scripts/odld_explorer/generate_odld_dataset_explorers_w_scenario_tag.py \
  --source-root "$MS_ODD_DATA_ROOT/01_raw" \
  --canonical-dir "$MS_ODD_OUTPUT_ROOT/01_canonical" \
  --output-dir "$MS_ODD_OUTPUT_ROOT/06_scenario_explorers/odld" \
  --index-path "$MS_ODD_OUTPUT_ROOT/06_scenario_explorers/odld/index.html" \
  --regenerate-existing
```

## GT Workspace

The current frame reviewer is the Simplified Taxonomy GT Workspace:

```bash
python -m ms_odd_tagging.simplified_taxonomy.gt_workspace_profiled \
  --frame-root "$MS_ODD_OUTPUT_ROOT/02_frame_inputs" \
  --gt-root "$MS_ODD_OUTPUT_ROOT/06_gt_comparison/gt" \
  --source-hz 10 \
  --sample-hz 1 \
  --host 127.0.0.1 \
  --port 8765
```

Open `http://127.0.0.1:8765`.

## Documentation

Start with:

```text
docs/handover/KOR/00_OVERVIEW.md
docs/handover/KOR/01_SETUP_AND_RUN.md
docs/handover/KOR/02_PIPELINE.md
docs/handover/KOR/03_DATA_FORMAT.md
```
