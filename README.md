# MS ODD Tagging

Autonomous-driving Motional Scenario tagging from OD/LD annotations and ego trajectory.

## Current workflow

```text
annotations_OD.json + annotations_LD.json + traj_lcs.txt
        ↓
OD+LD+Trajectory Canonicalization
        ↓
outputs/01_canonical
        ↓
Rule / geometry analysis + per-frame input / BEV generation
        ↓
outputs/02_frame_inputs
        ├── frame_XXXXXX/frame.json
        ├── frame_XXXXXX/bev.png
        └── recording_frame_tags_1fps/
```

Semantic cases that require VLM reasoning use candidate/episode selection before Qwen VLM inference. Ground-truth review uses the Simplified Taxonomy GT Workspace.

## Repository layout

```text
configs/                  active scenario and geometry configuration
data/                     local data layout documentation
docs/handover/KOR/        current project documentation
scripts/odld_explorer/    full OD+LD scenario explorer
src/ms_odd_tagging/       implementation
tests/                    automated tests
```

The canonical schema is `odld-trajectory-canonical-frame-v1`.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Run

```bash
ms-odd-tagging <RECORDING_ID>
```

Smoke test:

```bash
ms-odd-tagging <RECORDING_ID> --frame-limit 1
```

Common options:

```bash
ms-odd-tagging <RECORDING_ID> --frames-per-second 2
ms-odd-tagging <RECORDING_ID> --all-frames
ms-odd-tagging <RECORDING_ID> --existing-output resume
ms-odd-tagging <RECORDING_ID> --existing-output regenerate
ms-odd-tagging <RECORDING_ID> --stop-after canonical
```

Set external data/output roots when needed:

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

## Current CLIs

```bash
ms-odd-tagging --help
ms-odd-canonical --help
ms-odd-frame-inputs --help
ms-odd-rules --help
ms-odd-following-lane --help
ms-odd-ld-topology --help
ms-odd-qwen-vlm --help
ms-odd-gt-workspace --help
ms-odd-validate-frames --help
```

## Full ODLD Scenario Explorer

```bash
python scripts/odld_explorer/generate_odld_dataset_explorers_w_stage_progress.py \
  --source-root "$MS_ODD_DATA_ROOT/01_raw" \
  --canonical-dir "$MS_ODD_OUTPUT_ROOT/01_canonical" \
  --output-dir "$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers" \
  --regenerate-existing
```

## GT Workspace

```bash
ms-odd-gt-workspace \
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
