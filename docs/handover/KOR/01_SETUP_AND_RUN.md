# Setup and Run

## 1. 목적

이 문서는 운영체제에 맞는 실행 문서를 선택하기 위한 시작점이다.

| 환경 | 문서 | Shell |
|---|---|---|
| Linux server / workstation | [01A_SETUP_AND_RUN_LINUX.md](./01A_SETUP_AND_RUN_LINUX.md) | Bash |
| Windows workstation | [01B_SETUP_AND_RUN_WINDOWS.md](./01B_SETUP_AND_RUN_WINDOWS.md) | PowerShell |

## 2. 공통 입력

각 recording은 다음 세 파일을 포함해야 한다.

```text
MS_ODD_DATA_ROOT/01_raw/<RECORDING_ID>/
├── annotations_OD.json
├── annotations_LD.json
└── traj_lcs.txt
```

## 3. 공통 실행 흐름

```text
MS_ODD_DATA_ROOT/01_raw
        │
        ▼
ms-odd-tagging
        │
        ├── outputs/01_canonical
        │
        └── outputs/02_frame_inputs
              ├── frame_XXXXXX/frame.json
              ├── frame_XXXXXX/bev.png
              └── recording_frame_tags_1fps/
```

기본 frame sampling은 1 FPS이다.

## 4. 주요 command

```text
ms-odd-tagging          전체 input pipeline
ms-odd-canonical        canonicalization
ms-odd-frame-inputs     per-frame input / BEV generation
ms-odd-rules            deterministic scenario detection
ms-odd-following-lane   following-lane analysis
ms-odd-ld-topology      LD topology analysis
ms-odd-qwen-vlm         VLM candidate / inference workflow
ms-odd-gt-workspace     Simplified Taxonomy GT Workspace
ms-odd-validate-frames  frame-input validation
```

## 5. Full ODLD Scenario Explorer

Full OD+LD Scenario Explorer를 생성할 때는 stage별 진행 상황을 표시하는 다음 runner를 기본으로 사용한다.

```text
scripts/odld_explorer/generate_odld_dataset_explorers_w_stage_progress.py
```

이 runner는 현재 ODLD Scenario Explorer 생성 과정을 그대로 실행하면서 recording별 stage 진행률과 각 stage의 소요 시간을 출력한다.

### Linux

```bash
python scripts/odld_explorer/generate_odld_dataset_explorers_w_stage_progress.py \
  --source-root "$MS_ODD_DATA_ROOT/01_raw" \
  --canonical-dir "$MS_ODD_OUTPUT_ROOT/01_canonical" \
  --output-dir "$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers" \
  --index-path "$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers/index.html" \
  --regenerate-existing
```

### Windows PowerShell

```powershell
python scripts/odld_explorer/generate_odld_dataset_explorers_w_stage_progress.py `
  --source-root (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") `
  --canonical-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "01_canonical") `
  --output-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "07_odld_scenario_explorers") `
  --index-path (Join-Path $env:MS_ODD_OUTPUT_ROOT "07_odld_scenario_explorers\index.html") `
  --regenerate-existing
```

생성된 explorer index:

```text
MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers/index.html
```

설치부터 smoke test까지는 운영체제별 문서를 따른다.
