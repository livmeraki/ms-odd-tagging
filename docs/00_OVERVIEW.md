# Motional Scenario ODD Tagging Automation

## 1. 프로젝트 개요

### 1.1 프로젝트 배경

STRADVISION에서는 기존에 주행 환경과 주변 조건을 분류하는 **ODD (Operational Design Domain) Tagging** 작업을 수행하고 있었다.

기존 ODD Tagging은 도로 유형, 날씨, 시간대, 차선 및 주변 객체 상태 등 주행 환경을 기준에 따라 분류하는 작업이다. 특히 Dynamic ODD의 경우 각 **frame을 기준으로 해당 시점의 상태를 판단하여 tagging**할 수 있다.

반면, **Motional Scenario Tagging은 기존 ODD Tagging보다 차량의 시간적 움직임과 주변 객체와의 관계를 함께 이해해야 하는 작업**이다.

예를 들어 다음과 같은 scenario는 한 frame만으로는 정확하게 판단하기 어렵다.

* `changing_lane`
* `starting_left_turn`
* `starting_right_turn`
* `stopping_with_lead`
* `following_lane_with_lead`
* `waiting_for_pedestrian_to_cross`
* `traversing_intersection`

`changing_lane`을 판단하려면 Ego Vehicle이 이전에는 어느 lane에 있었고 이후 어느 lane으로 이동했는지를 확인해야 하며, `stopping_with_lead`는 Ego Vehicle의 감속 과정과 전방 차량의 존재를 함께 확인해야 한다.

즉, 일반적인 frame-level ODD Tagging과 달리 Motional Scenario Tagging은 **여러 frame에 걸친 차량의 상태 변화와 주변 환경의 temporal context를 함께 분석해야 한다.**

이 때문에 Motional Scenario를 사람이 직접 tagging할 경우 기존 ODD Tagging보다 판단 과정이 복잡하고, 데이터 확인에 더 많은 시간이 필요할 것으로 예상된다.

---

## 1.2 프로젝트 목적

본 프로젝트의 목적은 **기존에 자동화되어 있지 않았던 Motional Scenario Tagging을 주행 데이터 기반으로 자동화하는 파이프라인을 개발하는 것**이다.

주행 데이터에서 제공되는 다음 정보를 활용한다.

* Object Detection (OD)
* Lane Detection (LD)
* Ego Trajectory

이를 통해 Ego Vehicle의

* 속도 및 가감속
* 회전 및 주행 방향 변화
* 현재 주행 lane 및 lane transition
* 횡단보도 및 교차로와의 위치 관계
* 주변 차량 및 보행자와의 관계

등을 시간적으로 분석하여 Motional Scenario를 자동으로 판별한다.

Motional Scenario 중 데이터로부터 명확하게 계산할 수 있는 항목은 **Rule-based / Geometry-based algorithm**을 이용하여 처리하고, 단순한 수치 및 geometry만으로 판단하기 어려운 일부 scenario에 대해서는 **VLM을 보조적으로 활용하는 Hybrid 방식**을 실험하였다.

---

## 1.3 프로젝트 목표

최종적으로 다음과 같은 자동화 pipeline을 구축하는 것을 목표로 한다.

```text
OD + LD + Ego Trajectory
            │
            ▼
  Canonical Frame Data
            │
            ▼
Temporal / Geometric Analysis
            │
      ┌─────┴─────┐
      ▼           ▼
 Rule-based    VLM-assisted
 Detection      Detection
      │           │
      └─────┬─────┘
            ▼
   Motional Scenario
       JSON Output
```

이를 통해 기존에 사람이 여러 frame을 확인하면서 수행해야 하는 Motional Scenario Tagging 작업을 자동화하여,

* **Tagging 작업 시간 단축**
* **동일한 기준에 따른 일관된 tagging**
* **대규모 주행 데이터 처리 가능**
* **향후 scenario 기반 데이터 검색 및 활용**

이 가능하도록 하는 것을 목표로 한다.

---

## 1.4 기존 ODD Tagging과 Motional Scenario Tagging의 차이

| 구분               | 기존 ODD Tagging                      | Motional Scenario Tagging                        |
| ---------------- | ----------------------------------- | ------------------------------------------------ |
| 주요 목적            | 주행 환경 및 조건 분류                       | Ego Vehicle의 주행 행동 및 상호작용 분류                     |
| 주요 정보            | 도로, 날씨, 시간, 객체, 환경 상태               | 속도 변화, lane transition, maneuver, 객체와의 관계        |
| 판단 단위            | 주로 현재 frame의 상태                     | 여러 frame에 걸친 temporal behavior                   |
| 예시               | City, Night, Rainy, Vehicle Density | Changing Lane, Starting Turn, Stopping with Lead |
| Temporal Context | 상대적으로 낮음                            | 중요                                               |
| 수작업 난이도          | 기존 작업 process 존재                    | 상대적으로 높은 것으로 예상                                  |
| 본 프로젝트 범위        | 대상 아님                               | **자동화 대상**                                       |

> **핵심:** 본 프로젝트는 기존 ODD Tagging 자체를 자동화하는 프로젝트가 아니라, 기존 ODD보다 시간적 해석이 더 많이 필요한 **Motional Scenario ODD Tagging을 새롭게 자동화하기 위한 프로젝트**이다.

---

## 1.5 현재 접근 방식

프로젝트 초기에는 주행 정보를 LLM/VLM에 전달하여 Motional Scenario를 직접 추론하는 방식도 검토하였다.

그러나 개발을 진행하면서 모든 scenario를 모델에 의존하는 것보다, 입력 데이터에서 직접 계산 가능한 정보는 deterministic algorithm으로 처리하는 것이 정확도, 처리 속도 및 재현성 측면에서 유리하다고 판단하였다.

따라서 현재 구조는 다음 원칙을 따른다.

1. **OD / LD / Ego Trajectory를 공통 representation으로 정합**
2. **수치적으로 판단 가능한 scenario는 Rule-based 처리**
3. **Lane 및 Intersection 관련 scenario는 Geometry / Temporal logic 활용**
4. **Scene-level semantic reasoning이 필요한 일부 scenario만 VLM 활용**
5. **모든 결과를 동일한 Motional Scenario JSON format으로 출력**

즉, 현재 시스템은 **Rule-based를 중심으로 하되 필요한 경우 VLM을 보조적으로 사용하는 Hybrid Motional Scenario Tagging Pipeline**을 지향한다.
