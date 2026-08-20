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

설치부터 smoke test까지는 운영체제별 문서를 따른다.
