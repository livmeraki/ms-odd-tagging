# MS ODD Tagging

Autonomous-driving Motional Scenario tagging from OD/LD annotations and ego trajectory.

## Workflow

```text
annotations_OD.json + annotations_LD.json + traj_lcs.txt
        ↓
Canonicalization
        ↓
outputs/01_canonical
        ↓
Rule / geometry analysis + frame / BEV generation
        ↓
outputs/02_frame_inputs
        ├── frame_XXXXXX/frame.json
        ├── frame_XXXXXX/bev.png
        └── recording_frame_tags_1fps/
```

Semantic cases use candidate/episode selection before VLM inference. Ground-truth review uses the GT Workspace.

## Repository layout

```text
configs/                  scenario and geometry configuration
data/                     local data layout documentation
docs/handover/KOR/        project handover and developer documentation
scripts/odld_explorer/    OD+LD scenario explorer
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

## Commands

```bash
ms-odd-tagging --help
ms-odd-canonical --help
ms-odd-frames --help
ms-odd-rules --help
ms-odd-lane --help
ms-odd-topology --help
ms-odd-vlm --help
ms-odd-gt --help
ms-odd-validate --help
```

## ODLD Explorer

```bash
python scripts/odld_explorer/generate.py \
  --source-root "$MS_ODD_DATA_ROOT/01_raw" \
  --canonical-dir "$MS_ODD_OUTPUT_ROOT/01_canonical" \
  --output-dir "$MS_ODD_OUTPUT_ROOT/06_scenario_explorers/odld" \
  --index-path "$MS_ODD_OUTPUT_ROOT/06_scenario_explorers/odld/index.html" \
  --regenerate-existing
```

## GT Workspace

```bash
ms-odd-gt \
  --frame-root "$MS_ODD_OUTPUT_ROOT/02_frame_inputs" \
  --gt-root "$MS_ODD_OUTPUT_ROOT/05_gt_comparison/gt" \
  --source-hz 10 \
  --sample-hz 1 \
  --host 127.0.0.1 \
  --port 8765
```

Open `http://127.0.0.1:8765`.

## Documentation

The single handover entry point is:

```text
docs/handover/KOR/00_OVERVIEW.md
```

It explains the project purpose, architecture, important files, CLI/tools, debugging workflow, extension workflow, and the areas that still require implementation or validation.

Detailed documents:

```text
docs/handover/KOR/01_SETUP_AND_RUN.md
docs/handover/KOR/01A_SETUP_AND_RUN_LINUX.md
docs/handover/KOR/01B_SETUP_AND_RUN_WINDOWS.md
docs/handover/KOR/02_PIPELINE.md
docs/handover/KOR/03_DATA_FORMAT.md
docs/handover/KOR/04_SCENARIO_STATUS.md
docs/handover/KOR/05_ALGORITHMS.md
docs/handover/KOR/06_EVALUATION.md
docs/handover/KOR/07_REMAINING_WORK.md
docs/handover/KOR/08_VLM_BEV_RECOGNITION_POC.md
docs/handover/KOR/09_REFERENCES.md
```

English handover documentation is intentionally not maintained separately yet. Refine the Korean source first, then translate it once the content is stable so the two versions do not diverge.
