# Setup and Run

## 1. 목적

이 문서는 운영체제에 맞는 실행 문서를 선택하기 위한 시작점이다. Linux와 Windows의 shell 문법이 다르므로 두 문서의 명령을 섞어 사용하지 않는다.

## 2. 실행 환경 선택

| 환경 | 문서 | Shell |
|---|---|---|
| Linux server / workstation | [01A_SETUP_AND_RUN_LINUX.md](./01A_SETUP_AND_RUN_LINUX.md) | Bash |
| Windows workstation | [01B_SETUP_AND_RUN_WINDOWS.md](./01B_SETUP_AND_RUN_WINDOWS.md) | PowerShell |

프로젝트의 주요 검증 환경은 Linux와 Windows이다. macOS는 Python package 일부를 실행할 수 있지만, Lanelet2와 local vLLM을 포함한 전체 workflow는 검증되지 않았다. macOS 사용자는 Linux 문서를 참고하되 shell과 dependency 차이를 별도로 확인한다.

## 3. 공통 Pipeline

두 환경 모두 동일한 논리적 pipeline과 output stage를 사용한다.

~~~text
MS_ODD_DATA_ROOT/01_raw
        │
        ▼
MS_ODD_OUTPUT_ROOT/01_canonical
        │
        ▼
MS_ODD_OUTPUT_ROOT/02_frame_inputs
        │
        ├── 07_odld_scenario_explorers
        └── 07_odld_scenario_explorers_gt_authoring_all_tags
~~~

필수 recording 구조:

~~~text
MS_ODD_DATA_ROOT/01_raw/<RECORDING_ID>/
├── annotations_OD.json
├── annotations_LD.json
└── traj_lcs.txt
~~~

## 4. 권장 실행 순서

1. 운영체제별 문서에서 Python environment를 설치한다.
2. MS_ODD_DATA_ROOT와 MS_ODD_OUTPUT_ROOT를 설정한다.
3. recording 1개, frame 1개로 Smoke Test를 실행한다.
4. output JSON과 BEV를 확인한다.
5. recording 전체 또는 batch를 실행한다.
6. 필요할 때 ODLD Explorer, GT Authoring, VLM 기능을 실행한다.

## 5. 주의사항

- Bash prompt에서 PowerShell의 Get-ChildItem, Join-Path, $env:... 문법을 실행하지 않는다.
- PowerShell에서 Bash의 export, source, 배열 확장 문법을 실행하지 않는다.
- machine-specific absolute path를 source code에 hard-code하지 않는다.
- 처음부터 전체 dataset을 실행하지 말고 반드시 Smoke Test를 먼저 수행한다.
- run_pipeline.py의 전체 실행은 Canonicalization과 Frame Input/BEV 생성을 의미한다. Rule-based tagging, ODLD Explorer, GT Authoring, VLM은 필요에 따라 별도로 실행한다.

## 6. 관련 문서

- [00_OVERVIEW.md](./00_OVERVIEW.md)
- [02_PIPELINE.md](./02_PIPELINE.md)
- [03_DATA_FORMAT.md](./03_DATA_FORMAT.md)
- [05_ALGORITHMS.md](./05_ALGORITHMS.md)
- [07_KNOWN_ISSUES.md](./07_KNOWN_ISSUES.md)
