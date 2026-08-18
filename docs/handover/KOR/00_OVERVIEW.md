# Motional Scenario ODD Tagging Automation

> **START HERE — PROJECT HANDOVER OVERVIEW**  
> 이 문서는 프로젝트를 처음 인수받은 사람이 전체 목적, 현재 구조, 구현 범위를 빠르게 파악하기 위한 시작 문서입니다.

## 1. 프로젝트 배경 및 목적

STRADVISION에서는 기존에 주행 환경과 주변 조건을 분류하는 ODD (Operational Design Domain) Tagging 작업을 수행하고 있었다. Dynamic ODD는 각 frame에서 관찰되는 상태를 기준으로 tagging할 수 있는 반면, Motional Scenario는 차량의 움직임과 주변 객체와의 관계가 시간에 따라 어떻게 변하는지를 함께 확인해야 하는 경우가 많다.

예를 들어 `changing_lane`, `starting_left_turn`, `stopping_with_lead`, `waiting_for_pedestrian_to_cross`와 같은 scenario는 단일 frame만으로 안정적으로 판단하기 어렵다. 따라서 Motional Scenario Tagging은 여러 frame에 걸친 temporal context를 확인해야 하며, 수작업 시 기존 ODD Tagging보다 판단 과정이 복잡하고 시간이 더 많이 소요될 것으로 예상된다.

본 프로젝트의 목적은 **Motional Scenario Tagging을 주행 데이터 기반으로 자동화하는 파이프라인을 개발하는 것**이다.

STRADVISION의 ALT (Auto Labeling Tool)를 통해 생성된 다음 데이터를 주요 입력으로 사용한다.

- OD (Object Detection) Annotation
- LD (Lane Detection) Annotation
- Ego Trajectory

이 입력을 이용해 Ego Vehicle의 속도/가감속, 회전, lane 관계, crosswalk/stopline/intersection과의 공간 관계, 주변 객체와의 상호작용을 시간적으로 분석하고 Motional Scenario를 판별한다.

## 2. 현재 시스템 구조

```text
OD Annotation + LD Annotation + Ego Trajectory
                    │
                    ▼
        OD+LD Canonicalization
                    │
                    ▼
        Canonical Frame JSON
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
  Rule-based Tagging     1 FPS Frame Input / BEV
          │                   │
          │              Optional VLM / PoC
          │                   │
          └─────────┬─────────┘
                    ▼
          Motional Scenario Output
```

`run_pipeline.py`의 현재 기본 역할은 canonical 생성과 timestamp 기반 frame input/BEV 생성을 순서대로 실행하는 것이다. OD+LD 입력에는 `--odld` 옵션을 사용한다. Rule-based tagging은 별도 registry에서 전체 canonical frame을 대상으로 실행된다.

현재 설계 원칙은 다음과 같다.

1. OD / LD / Ego Trajectory를 canonical representation으로 정합한다.
2. 수치적으로 명확한 scenario는 deterministic rule로 판별한다.
3. Lane, crosswalk, stopline, intersection 및 object relation은 geometry와 temporal logic을 사용한다.
4. 의미적 해석이 필요한 일부 scenario는 VLM을 보조적으로 사용하거나 PoC로 분리한다.
5. 현재 자동 tagging path가 없는 label은 억지로 추론하지 않고 `unsupported`로 남긴다.

## 3. Scenario Catalog — Single Source of Truth

Scenario 이름, 처리 방식, 구현 상태는 다음 파일에서 관리한다.

```text
configs/scenario_catalog.csv
```

Catalog는 의도적으로 최소한의 네 column만 사용한다.

```text
name | category | methods | status
```

각 column의 의미는 다음과 같다.

- `name`: Motional Scenario label
- `category`: taxonomy grouping (`dynamics`, `interaction`, `zone`, `maneuver`, `behavior`)
- `methods`: 자동 판별 방식 (`rule`, `vlm`, `rule+vlm`, 또는 빈 값)
- `status`: 현재 구현 상태 (`active`, `experimental`, `unsupported`)

`methods`가 빈 값이고 `status=unsupported`인 scenario는 현재 repository에서 Rule 또는 VLM 자동 tagging path가 지원되지 않는 항목이다.

따라서 Rule/VLM/unsupported 여부를 확인하기 위해 Python 파일이나 handover 문서에 별도 scenario list를 유지하지 않고 `scenario_catalog.csv`를 먼저 확인한다.

VLM candidate grouping과 traffic-light episode 구성은 catalog가 아니라 `qwen_vlm_poc` 내부 구현에서 관리한다. Rule registry와 catalog의 method 일치 여부는 unit test로 검증한다.

자세한 내용은 `04_SCENARIO_STATUS.md`를 확인한다.

## 4. 현재 구현 범위 요약

현재 자동화 방식은 크게 다음과 같이 구분된다.

- **Rule — active**: speed, jerk, turn, lane change, crosswalk/stopline relation, nearby object interaction, pedestrian-crosswalk interaction, object path crossing 등
- **Rule — experimental**: lead/trail 및 traffic interaction 계열 등 추가 calibration이 필요한 rule
- **VLM — experimental**: `on_intersection`, `starting_u_turn`, traffic-light 관련 semantic scenario 등
- **Rule + VLM — experimental**: 두 path가 모두 존재하는 scenario. 현재 대표적으로 `waiting_for_pedestrian_to_cross`
- **Unsupported**: 현재 Rule/VLM 자동 tagging path가 없는 scenario

특히 stop-sign, pickup/dropoff, protected/unprotected turn, narrow-lane 관련 일부 taxonomy scenario는 현재 `unsupported`로 관리한다. 예를 들어 `accelerating_at_stop_sign`, `on_stopline_stop_sign`, `on_all_way_stop_intersection`, `starting_protected_cross_turn`, `traversing_narrow_lane`, `traversing_pickup_dropoff` 등이 이에 해당한다. 전체 목록은 반드시 `configs/scenario_catalog.csv`를 source of truth로 확인한다.

`active`는 현재 자동 tagging path가 사용 가능한 상태를 의미하며, production-level validation이 모두 완료되었다는 의미는 아니다. `experimental`은 code path는 존재하지만 추가 calibration 또는 evaluation이 필요한 상태이다.

## 5. 핵심 성과

- OD + Trajectory뿐 아니라 LD geometry를 통합하는 canonical pipeline을 구축했다.
- 단일 모델 중심 접근에서 Rule / Geometry 중심 구조로 전환하고, VLM은 선택적 보조 수단으로 분리했다.
- full recording에서 dynamic rule event를 계산하고, 선택된 timestamp에는 독립적인 `frame.json`과 `bev.png`를 생성하는 구조를 정리했다.
- frame-level GT reviewer 및 tagged scenario explorer를 구축하여 rule 결과와 사람이 작성한 GT를 비교할 수 있는 기반을 마련했다.
- lane continuity, crosswalk/stopline, nearby object, traffic interaction 등 복수의 scenario family를 단계적으로 확장했다.
- Rule/VLM/unsupported 상태를 하나의 lightweight scenario catalog에서 관리하도록 정리했다.

> 정량 성능(F1, Precision/Recall)과 수동 대비 처리 시간 수치는 발표용 실험에서 사용된 값이 있으나, 현재 repository 자체에서 동일 조건의 최종 결과 파일을 바로 확인할 수 없는 항목은 `06_EVALUATION.md`에서 **검증 필요**로 표시한다.

## 6. Repository에서 먼저 알아둘 것

- 기본 canonical schema: `od-trajectory-canonical-frame-v1`
- OD+LD experimental schema: `odld-trajectory-canonical-frame-v1`
- frame input은 기본 1 FPS이며, 각 timestamp마다 독립적인 `frame.json` + `bev.png`를 생성한다.
- Rule-based dynamic tagging은 1 FPS 샘플만 보는 것이 아니라 전체 canonical frame을 평가한다.
- rule-derived label은 model-facing frame JSON과 분리하여 answer leakage를 방지한다.
- scenario method/status의 source of truth는 `configs/scenario_catalog.csv`이다.
- Rule threshold와 runtime enable 설정은 `configs/direct_scenarios.yaml`에서 관리한다.
- VLM candidate grouping은 `src/ms_odd_tagging/qwen_vlm_poc/` 내부에서 관리한다.
- `unsupported` scenario는 자동 결과에서 임의로 false 또는 inferred로 처리하지 않는다.
- 생성 결과, model weight, secret, machine-local config는 Git에 포함하지 않는 것을 원칙으로 한다.

## 7. Handover Document Guide

> **READ THIS FIRST, THEN FOLLOW THIS ORDER**

| 순서 | 문서 | 목적 |
|---:|---|---|
| 00 | `00_OVERVIEW.md` | 프로젝트 배경, 목적, 구조, 현재 범위 |
| 01 | `01_SETUP_AND_RUN.md` | 설치, 데이터 경로, 실행 명령 |
| 02 | `02_PIPELINE.md` | 단계별 pipeline과 module 관계 |
| 03 | `03_DATA_FORMAT.md` | OD / LD / Trajectory / Canonical 형식 |
| 04 | `04_SCENARIO_STATUS.md` | scenario catalog와 구현 상태 |
| 05 | `05_ALGORITHMS.md` | 주요 rule / geometry 알고리즘 |
| 06 | `06_EVALUATION.md` | GT 작성, 평가 방법, 정량 결과 |
| 07 | `07_KNOWN_ISSUES.md` | 현재 알려진 오류와 주의점 |
| 08 | `08_NEXT_STEPS.md` | 후속 개발 우선순위 |
| 09 | `09_REFERENCES.md` | 관련 코드, 기존 문서, 정책 자료 |

처음 인수받은 경우에는 다음 순서를 권장한다.

**Overview → Setup & Run → Scenario Status → Known Issues**

새 scenario를 구현하거나 detector를 수정할 경우에는 다음 순서로 추가 확인한다.

**Scenario Catalog → Pipeline → Data Format → Algorithms → Evaluation**
