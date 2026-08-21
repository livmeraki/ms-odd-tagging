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

## 8. 현재 고도화 시 우선 볼 영역

현재 후속 개발에서 특히 주의할 영역은 다음과 같습니다.

- lane continuity / reconstruction
- intersection에서 false lane change
- short / missing LD segment
- sparse traffic-light observation의 temporal persistence
- object association / velocity noise
- jerk / derivative noise
- frame input과 frame tag sampling alignment
- GT Workspace loading 성능
- VLM candidate recall / benchmark 재현성

상세 내용과 권장 우선순위는 다음 문서를 기준으로 합니다.

```text
07_KNOWN_ISSUES.md
08_NEXT_STEPS.md
```

## 9. 처음 인수받은 개발자가 따라갈 순서

```text
1. README.md
2. 00_OVERVIEW.md        ← 현재 문서
3. 01_SETUP_AND_RUN.md
4. 02_PIPELINE.md
5. 04_SCENARIO_STATUS.md
6. 07_KNOWN_ISSUES.md
7. 08_NEXT_STEPS.md
```

새 detector나 알고리즘을 수정할 경우 추가로 다음 문서를 확인합니다.

```text
03_DATA_FORMAT.md
05_ALGORITHMS.md
06_EVALUATION.md
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
| `05_ALGORITHMS.md` | 주요 rule / geometry 알고리즘 |
| `06_EVALUATION.md` | GT 작성과 평가 방법 |
| `07_KNOWN_ISSUES.md` | 현재 알려진 문제와 디버깅 주의점 |
| `08_NEXT_STEPS.md` | 후속 개발 우선순위 |
| `09_REFERENCES.md` | 관련 코드와 정책/참고 자료 |

영문 문서는 현재 별도로 유지하지 않습니다. 한국어 문서를 먼저 고도화한 뒤, 내용이 안정되면 동일 구조와 내용으로 번역하는 것을 권장합니다.
