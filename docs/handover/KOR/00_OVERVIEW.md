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

- `rule`: Rule / Geometry / Temporal logic이 최종 scenario를 판별
- `vlm`: Rule 기반 candidate selection 후 VLM이 최종 scenario를 판별
- `unsupported`: 현재 자동 tagging path가 없음

여부를 확인할 수 있다.

자세한 내용은 `04_SCENARIO_STATUS.md`를 확인한다.

## 4. 핵심 성과

- OD, LD, Ego Trajectory를 통합한 **canonical pipeline 구축**
- **Rule / Geometry 중심의 자동 tagging 구조 구축**
- 필요한 scenario에 대해 **VLM 보조 추론 적용**
- 자동 결과를 확인하기 위한 **GT Reviewer / Scenario Explorer 구축**
- Lane, Crosswalk, Object Interaction 등으로 **지원 scenario 범위 확장**
- Scenario 지원 상태를 **하나의 catalog로 통합 관리**

Scenario별 상세 구현 방식과 상태는 `configs/scenario_catalog.csv`와
`04_SCENARIO_STATUS.md`를 확인한다.

## 5. Handover Document Guide

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
