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


## 3. Scenario Catalog — Single Source of Truth

Scenario 이름, 처리 방식, 구현 상태는 다음 파일에서 관리한다.

```text
configs/scenario_catalog.csv
```

각 scenario에 대해:

- `rule`
- `vlm`
- `rule+vlm`
- `unsupported`

여부를 확인할 수 있다.

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
