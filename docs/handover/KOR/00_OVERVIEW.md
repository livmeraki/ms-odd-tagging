# Motional Scenario ODD Tagging Automation

> **START HERE — PROJECT HANDOVER OVERVIEW**  
> 이 문서는 프로젝트를 처음 인수받은 사람이 **무엇을 만들었고, 어디서부터 보면 되는지** 빠르게 파악하기 위한 시작 문서입니다.

## 1. 이 프로젝트는 무엇인가?

Motional Scenario는 `changing_lane`, `starting_left_turn`, `stopping_with_lead`처럼 **여러 frame에 걸친 차량 움직임과 주변 객체 관계를 함께 봐야 하는 주행 상황**이다.

본 프로젝트는 STRADVISION ALT에서 생성된 다음 데이터를 이용해 이러한 Motional Scenario Tagging을 자동화한다.

- OD (Object Detection) Annotation
- LD (Lane Detection) Annotation
- Ego Trajectory

명확하게 수치화할 수 있는 scenario는 **Rule / Geometry / Temporal logic**으로 판별하고, 일부 복잡한 scenario는 **Rule 기반 candidate selection + VLM** 방식으로 보조 판별한다.

## 2. 전체 구조

```text
OD + LD + Ego Trajectory
          │
          ▼
   Canonical Data
          │
     ┌────┴────┐
     ▼         ▼
Rule / Geometry   VLM-assisted
     │         │
     └────┬────┘
          ▼
Motional Scenario Output
```

Scenario별 현재 처리 방식과 지원 상태는 `configs/scenario_catalog.csv`를 기준으로 확인한다.

## 3. 핵심 성과

- OD, LD, Ego Trajectory를 통합한 **canonical pipeline 구축**
- **Rule / Geometry 중심의 자동 tagging 구조** 구축
- 필요한 일부 scenario에 **VLM 보조 추론** 적용
- 결과 확인을 위한 **GT Reviewer / Scenario Explorer** 구축
- Lane, Crosswalk, Object Interaction 등으로 **자동 tagging 범위 확장**
- Scenario 지원 상태를 **하나의 lightweight catalog로 통합 관리**

## 4. 다음에 무엇을 읽어야 하나?

목적에 따라 필요한 문서부터 읽으면 된다.

| 알고 싶은 것 | 문서 |
|---|---|
| 프로젝트를 설치하고 실제로 실행하기 | [`01_SETUP_AND_RUN.md`](01_SETUP_AND_RUN.md) |
| 전체 pipeline과 module 흐름 이해하기 | [`02_PIPELINE.md`](02_PIPELINE.md) |
| OD / LD / Trajectory / Canonical 데이터 구조 보기 | [`03_DATA_FORMAT.md`](03_DATA_FORMAT.md) |
| 어떤 scenario가 Rule / VLM / Unsupported인지 확인하기 | [`04_SCENARIO_STATUS.md`](04_SCENARIO_STATUS.md) |
| Rule / Geometry 알고리즘이 어떻게 동작하는지 이해하기 | [`05_ALGORITHMS.md`](05_ALGORITHMS.md) |
| GT 작성 방법과 평가 결과 확인하기 | [`06_EVALUATION.md`](06_EVALUATION.md) |
| 현재 한계, 오류, 주의점 확인하기 | [`07_KNOWN_ISSUES.md`](07_KNOWN_ISSUES.md) |
| 다음 개발자가 이어서 할 작업 확인하기 | [`08_NEXT_STEPS.md`](08_NEXT_STEPS.md) |
| 원본 정책, 관련 문서, 코드 출처 찾기 | [`09_REFERENCES.md`](09_REFERENCES.md) |

처음 인수받았다면 다음 순서를 권장한다.

**Setup & Run → Pipeline → Scenario Status → Known Issues → Next Steps**

코드를 수정하기 전에는 관련 문서만 추가로 확인하면 된다. 모든 내용을 처음부터 읽을 필요는 없다.
