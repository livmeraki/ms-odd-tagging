# Motional Scenario ODD Tagging Automation

> **START HERE — 개발자 인수인계 시작 문서**
>
> 이 문서는 프로젝트를 처음 인수받은 개발자가 **무엇을 하는 프로젝트인지, 어떤 파일을 봐야 하는지, 어떤 툴을 언제 사용하는지, 이후 어디를 고도화해야 하는지** 빠르게 파악하기 위한 진입점입니다.

## 1. 프로젝트 목적

이 프로젝트는 다음 세 가지 입력을 이용해 자율주행 데이터의 Motional Scenario를 자동 tagging합니다.

```text
annotations_OD.json
annotations_LD.json
traj_lcs.txt
```

- **OD Annotation**: 주변 객체의 위치, 종류, 크기 등 object detection 정보
- **LD Annotation**: lane, road boundary, crosswalk, stopline 등 도로 구조 정보
- **Ego Trajectory**: ego vehicle의 위치, heading, 속도 등 시간에 따른 ego motion 정보

Motional Scenario는 단일 frame보다 여러 frame의 변화와 주변 객체/도로 구조와의 관계를 함께 봐야 하는 경우가 많습니다. 예를 들어 `changing_lane`, `starting_left_turn`, `waiting_for_pedestrian_to_cross`는 temporal context가 중요합니다.

따라서 현재 시스템은 다음을 결합합니다.

- ego motion
- geometry
- object relation
- lane / topology relation
- temporal filtering / hysteresis
- event segmentation
- 필요한 경우 VLM reasoning

기본 원칙은 **명시적인 geometry/data로 판단할 수 있는 것은 deterministic rule로 처리하고, semantic 판단이 필요한 일부 경우에만 VLM을 사용하는 것**입니다.

## 2. 전체 흐름

```text
Raw Recording
├── annotations_OD.json
├── annotations_LD.json
└── traj_lcs.txt
        │
        ▼
Canonicalization
        │
        ▼
outputs/01_canonical
        │
        ├──────────────────────────┐
        │                          │
        ▼                          ▼
Rule / Geometry / Temporal    Frame Input / BEV
Analysis                     Generation
        │                          │
        ├──────────────┐           │
        │              │           │
        ▼              ▼           │
Rule Detection    VLM Candidate    │
                  / Episode        │
        │              │           │
        │              ▼           │
        │         Evidence / BEV ◄─┘
        │              │
        │              ▼
        │         VLM Inference
        │              │
        │              ▼
        │        Validation / Merge
        │              │
        └──────┬───────┘
               ▼
      Motional Scenario Tags
               │
               ▼
 recording_frame_tags_1fps
               │
               ▼
          GT Workspace
```

## 3. 먼저 확인할 파일

### Scenario 지원 상태

```text
configs/scenario_catalog.csv
```

Scenario 지원 상태의 source of truth입니다.

- `rule`: deterministic rule / geometry / temporal logic가 최종 판단
- `vlm`: candidate/episode selection 후 VLM이 최종 판단
- blank + `unsupported`: 현재 자동 tagging path 없음

상세 내용은 `04_SCENARIO_STATUS.md`를 확인합니다.

### Rule 설정

```text
configs/direct_scenarios.yaml
```

threshold, minimum duration, hysteresis, merge/inactive gap 등 rule detector의 runtime 조건을 관리합니다.

### Lane / topology 설정

```text
configs/following_lane.json
configs/ld_topology.json
```

Lane continuity, following-lane, intersection/topology 관련 동작을 조정할 때 확인합니다.

## 4. Repository에서 중요한 구현 위치

```text
src/ms_odd_tagging/
├── canonical/       OD + LD + Ego Trajectory 정합
├── features/        detector들이 공유하는 relation/evidence
├── frame_inputs/    frame.json / BEV / sampled frame output
├── gt/              GT Workspace
├── ld_topology/     intersection / topology 분석
├── scenarios/       scenario-specific subsystem (예: following_lane)
├── tagger/          rule-based Motional Scenario detector
├── validator/       frame input validation
├── vlm/             VLM candidate / evidence / inference / validation
└── pipeline.py      전체 pipeline entry point
```

Full recording 디버깅용 explorer는 별도로 다음 위치에 있습니다.

```text
scripts/odld_explorer/
├── generate.py
├── explorer.py
└── odld_explorer_common.py
```

유지보수 원칙은 **하나의 기능에 대해 여러 버전의 구현을 다시 만들지 않는 것**입니다. 기존 구현을 개선하고, 중복되는 계산이 있다면 공통 layer로 정리합니다.

## 5. 어떤 툴을 언제 사용할지

| 목적 | 사용 명령 / 툴 |
|---|---|
| 전체 pipeline 실행 | `ms-odd-tagging` |
| canonical만 생성/확인 | `ms-odd-canonical` |
| `frame.json` / BEV 생성 | `ms-odd-frames` |
| deterministic scenario 확인 | `ms-odd-rules` |
| lane relation / following-lane 분석 | `ms-odd-lane` |
| intersection / topology 분석 | `ms-odd-topology` |
| VLM candidate / inference | `ms-odd-vlm` |
| 사람이 prediction/GT 검토 | `ms-odd-gt` |
| frame input validation | `ms-odd-validate` |
| full recording 시각 디버깅 | `python scripts/odld_explorer/generate.py` |
| unit / integration regression | `python -m pytest` |

실행 방법은 `01_SETUP_AND_RUN.md`와 OS별 문서를 따릅니다.

## 6. 문제를 디버깅하는 순서

잘못된 scenario 결과를 발견했을 때 바로 threshold부터 수정하지 않습니다.

```text
1. source OD / LD / trajectory에 필요한 정보가 있는가?
2. canonical alignment가 맞는가?
3. reusable feature / relation이 올바른가?
4. lane / topology 결과가 올바른가?
5. detector의 frame-level state가 맞는가?
6. temporal segmentation이 event를 잘못 줄이거나 제거했는가?
7. VLM scenario라면 candidate가 생성되었는가?
8. 필요한 evidence / BEV가 VLM에 전달되었는가?
9. validation / merge에서 결과가 제거되었는가?
10. GT 자체가 맞는가?
```

이 순서를 지키면 downstream false positive/false negative의 실제 원인이 upstream geometry, sampling, relation, candidate generation 중 어디에 있는지 구분하기 쉽습니다.

## 7. 새 기능을 추가할 때

### Rule scenario

권장 순서:

```text
Taxonomy / policy 확인
→ scenario_catalog.csv 확인/수정
→ 필요한 evidence 정의
→ 기존 canonical/features 재사용 여부 확인
→ 필요한 공통 feature 추가
→ frame-level state 구현
→ temporal segmentation 적용
→ config 추가
→ tests 추가
→ ODLD Explorer에서 확인
→ GT 작성/검토
→ 고정된 recording set으로 평가
→ 문서 업데이트
```

### VLM scenario

권장 순서:

```text
scenario_catalog.csv 확인/수정
→ high-recall deterministic candidate 정의
→ candidate/episode merge 정의
→ 필요한 evidence 정의
→ 대표 BEV frame 선택
→ prompt / output contract 정의
→ structured response validation
→ event merge
→ positive + hard-negative GT 구성
→ candidate recall과 VLM accuracy를 분리 평가
```

VLM 개선 시 **candidate recall과 VLM decision quality를 별도로 측정**하는 것이 중요합니다.

## 8. 아직 해결되지 않은 핵심 개발 항목

현재 후속 개발에서 가장 중요하게 확인해야 할 항목은 다음과 같습니다.

- **Evaluation methodology**: 현재까지 사용한 수치가 reproducible/reliable baseline인지 다시 확인해야 하며, GT consistency, sampling alignment, evaluation unit, event boundary 기준을 고정해야 함
- **Lane geometry reconstruction / ego lane inference**: lane 정보가 끊기거나, road 영역만 있고 명시적인 lane geometry가 부족한 구간에서 reconstruction이 약함
- **Motion signal 품질**: speed, acceleration, lateral acceleration, jerk 계열에서 spike가 나타날 수 있어 source signal과 derivative 계산을 다시 확인해야 함
- **Frame sampling contract**: frame input, prediction tag, GT reference가 동일한 source frame을 사용하도록 sampling policy를 통일할 필요가 있음
- **VLM BEV literacy**: VLM이 ego, object, 방향, 상대 위치, legend를 실제로 이해하는지 scenario accuracy와 별도로 검증해야 함
- **VLM candidate/decision 분리 평가**: candidate recall과 실제 VLM decision quality를 별도로 측정해야 함
- traffic-light temporal persistence
- **Speed band 정의**: 현재 fixed band를 사용하지만, 향후 ALT에서 speed-limit 정보가 제공되면 구간별 제한속도를 반영한 dynamic band를 검토할 수 있음
- GT Workspace 확장성/로딩 성능

각 항목의 현상, 원인 가설, 확인 절차, 구현 방향, regression 범위는 다음 문서에 통합되어 있습니다.

```text
07_REMAINING_WORK.md
```

VLM이 BEV 표현을 실제로 이해하는지 검증하기 위한 별도 PoC와 Linux server 결과 artifact 위치는 다음 문서에 정리되어 있습니다.

```text
08_VLM_BEV_RECOGNITION_POC.md
```

후속 개발자는 `07_REMAINING_WORK.md`를 단순 TODO list가 아니라 **현재 프로젝트에서 아직 충분히 검증되지 않은 부분의 기술적 인수인계 문서**로 사용합니다.

## 9. 처음 인수받은 개발자가 따라갈 순서

```text
1. README.md
2. 00_OVERVIEW.md        ← 현재 문서
3. 01_SETUP_AND_RUN.md
4. 02_PIPELINE.md
5. 04_SCENARIO_STATUS.md
6. 05_ALGORITHMS.md
7. 06_EVALUATION.md
8. 07_REMAINING_WORK.md
9. 08_VLM_BEV_RECOGNITION_POC.md   ← VLM/BEV 고도화 시
```

필요 시 다음 문서를 추가로 확인합니다.

```text
03_DATA_FORMAT.md
09_REFERENCES.md
```

## 10. Handover 문서 구성

| 문서 | 목적 |
|---|---|
| `00_OVERVIEW.md` | 개발자 인수인계 진입점: 목적, 구조, 파일, 툴, 개발 방향 |
| `01_SETUP_AND_RUN.md` | 공통 실행 흐름과 OS별 runbook 안내 |
| `01A_SETUP_AND_RUN_LINUX.md` | Linux Bash 설치 및 실행 |
| `01B_SETUP_AND_RUN_WINDOWS.md` | Windows PowerShell 설치 및 실행 |
| `02_PIPELINE.md` | pipeline 단계와 module 관계 |
| `03_DATA_FORMAT.md` | OD / LD / Trajectory / Canonical 형식 |
| `04_SCENARIO_STATUS.md` | scenario catalog와 현재 구현 상태 |
| `05_ALGORITHMS.md` | 주요 rule / geometry 알고리즘과 motion/lane 가정 |
| `06_EVALUATION.md` | GT 작성, evaluation contract, 현재 평가 신뢰성 주의점 |
| `07_REMAINING_WORK.md` | 아직 검증/구현이 필요한 항목과 구체적인 고도화 방향 |
| `08_VLM_BEV_RECOGNITION_POC.md` | VLM BEV understanding PoC, 실행 방법, Linux server output artifact |
| `09_REFERENCES.md` | 관련 코드와 정책/참고 자료 |

영문 문서는 현재 별도로 유지하지 않습니다. 한국어 문서를 먼저 고도화한 뒤, 내용이 안정되면 동일 구조와 내용으로 번역하는 것을 권장합니다.
