# Setup and Run

운영체제별 상세 실행 방법은 다음 문서를 사용한다.

| 환경 | 문서 |
|---|---|
| Linux | [01A_SETUP_AND_RUN_LINUX.md](./01A_SETUP_AND_RUN_LINUX.md) |
| Windows PowerShell | [01B_SETUP_AND_RUN_WINDOWS.md](./01B_SETUP_AND_RUN_WINDOWS.md) |

## 입력

```text
MS_ODD_DATA_ROOT/01_raw/<RECORDING_ID>/
├── annotations_OD.json
├── annotations_LD.json
└── traj_lcs.txt
```

## 기본 실행

```text
Raw recording
    ↓
ms-odd-tagging
    ├── 01_canonical
    └── 02_frame_inputs
          ├── frame_XXXXXX/frame.json
          ├── frame_XXXXXX/bev.png
          └── recording_frame_tags_1fps/
```

기본 sampling은 1 FPS이다.

## Commands

```text
ms-odd-tagging    전체 pipeline
ms-odd-canonical  canonical 생성
ms-odd-frames     frame input / BEV 생성
ms-odd-rules      rule-based tagging
ms-odd-lane       following-lane 분석
ms-odd-topology   LD topology 분석
ms-odd-vlm        VLM candidate / inference
ms-odd-gt         GT Workspace
ms-odd-validate   frame input 검증
```