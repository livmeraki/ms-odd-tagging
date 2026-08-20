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
        ├── 06_scenario_explorers/odld
        └── 06_scenario_explorers/gt_authoring
~~~

필수 recording 구조:

~~~text
MS_ODD_DATA_ROOT/01_raw/<RECORDING_ID>/
├── annotations_OD.json
├── annotations_LD.json
└── traj_lcs.txt
~~~