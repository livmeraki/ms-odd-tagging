# Motional Scenario ODD Tagging Automation

> **START HERE — PROJECT HANDOVER OVERVIEW**  
> 이 문서는 프로젝트를 처음 인수받은 사람이 전체 목적, 현재 구조, 구현 범위를 빠르게 파악하기 위한 시작 문서입니다.

## 1. 프로젝트 배경 및 목적

STRADVISION에서는 기존에 주행 환경과 주변 조건을 분류하는 ODD (Operational Design Domain) Tagging 작업을 수행하고 있었다. Dynamic ODD는 각 frame에서 관찰되는 상태를 기준으로 tagging할 수 있는 반면, Motional Scenario는 차량의 움직임과 주변 객체와의 관계가 시간에 따라 어떻게 변하는지를 함께 확인해야 하는 경우가 많다.

예를 들어 `changing_lane`, `starting_left_turn`, `waiting_for_pedestrian_to_cross`와 같은 scenario는 단일 frame만으로 안정적으로 판단하기 어렵다. 따라서 Motional Scenario Tagging은 여러 frame에 걸친 temporal context를 확인해야 하며, 수작업 시 기존 ODD Tagging보다 판단 과정이 복잡하고 시간이 더 많이 소요될 것으로 예상된다.

본 프로젝트의 목적은 **Motional Scenario Tagging을 주행 데이터 기반으로 자동화하는 파이프라인을 개발하는 것**이다.

## 2. 현재 시스템 구조

STRADVISION의 ALT (Auto Labeling Tool)를 통해 생성된 다음 데이터를 주요 입력으로 사용한다.
- OD Annotation: 주변 객체의 위치·종류 등 물체 감지 정보
- LD Annotation: 차선, 차선 경계, 정지선·횡단보도 등 도로 구조 감지 정보
- Ego Trajectory: Ego Vehicle의 시간에 따른 위치·진행 방향 변화 정보

이 입력을 이용해 Ego Vehicle의 속도/가감속, 회전, lane 관계, crosswalk/stopline/intersection과의 공간 관계, 주변 객체와의 상호작용을 시간적으로 분석하고 Motional Scenario를 판별한다.

전체 흐름은 다음과 같다.

```text
OD + LD + Ego Trajectory
          │
          ▼
   Canonical Data
          │
    ┌─────┴─────┐
    ▼           ▼
Rule / Geometry  VLM-assisted tagging
    │           │
    └─────┬─────┘
          ▼
Motional Scenario Output
```

## 3. Scenario 지원 현황

Scenario 이름, 처리 방식, 구현 상태는 다음 파일에서 관리한다.

```text
configs/scenario_catalog.csv
```

각 scenario가 다음 중 어떤 방식으로 처리되는지 확인할 수 있다.
- `rule`: Rule / Geometry / Temporal logic이 최종 scenario를 판별
- `vlm`: Rule 기반 candidate selection 후 VLM이 최종 scenario를 판별
- `unsupported`: 현재 자동 tagging path가 없음

Scenario별 상세 지원 현황과 상태 기준은 `04_SCENARIO_STATUS.md`를 확인한다.

## 4. 핵심 성과

- **데이터 처리 기반 구축**
  - OD, LD, Ego Trajectory를 통합하는 canonical pipeline 구축
  - 전체 tagging algorithm이 동일한 데이터 구조를 사용하도록 정리

- **Motional Scenario 자동 Tagging 구현**
  - Rule / Geometry / Temporal logic 중심의 자동 tagging 구조 구축
  - Lane, Crosswalk, Object Interaction 등 다양한 scenario로 지원 범위 확장
  - Rule만으로 판단하기 어려운 일부 scenario에 VLM 기반 판별 적용

- **검토 및 유지보수 환경 구축**
  - GT Reviewer / Scenario Explorer를 통해 자동 tagging 결과를 직접 확인·비교할 수 있도록 구성
  - Scenario별 지원 방식과 현재 상태를 하나의 `scenario_catalog.csv`에서 관리

## 5. Handover Document Guide

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

**Overview → Setup & Run → Pipeline → Scenario Status → Known Issues**

새 scenario를 구현하거나 detector를 수정할 경우에는 다음 순서로 추가 확인한다.

**Scenario Catalog → Pipeline → Data Format → Algorithms → Evaluation**
