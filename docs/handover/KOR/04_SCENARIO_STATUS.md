# Scenario Status

## 1. 이 문서를 읽는 방법

이 문서는 **현재 repository에 실제로 존재하는 구현 상태**를 중심으로 정리한다.

상태 표기:

- **Implemented**: active rule registry에 포함되어 있고 전용 detector/feature path가 존재
- **PoC / Calibration Needed**: code와 registry entry는 있으나 configuration provenance상 추가 calibration/검증 필요
- **VLM PoC**: Qwen VLM 실험 package에서 다루는 semantic scenario
- **Unsupported / Not wired**: taxonomy에는 있으나 현재 active rule registry에 연결되지 않음

> `enabled_scenarios`에 이름이 있다고 해서 충분한 production validation까지 완료되었다는 뜻은 아니다.

## 2. Ego Dynamics / Turn

| Scenario | 상태 | 방식 | 비고 |
|---|---|---|---|
| `stationary` | Implemented | Rule | ego speed band |
| `low_magnitude_speed` | Implemented | Rule | 0.5~5.0 m/s |
| `medium_magnitude_speed` | Implemented | Rule | 5.0~15.0 m/s |
| `high_magnitude_speed` | Implemented | Rule | >=15.0 m/s |
| `high_lateral_acceleration` | Implemented | Rule | lateral acceleration + hysteresis |
| `high_magnitude_jerk` | Implemented | Rule | acceleration-vector magnitude 기반 jerk |
| `starting_left_turn` | Implemented | Temporal Rule | yaw-rate / accumulated heading |
| `starting_right_turn` | Implemented | Temporal Rule | yaw-rate / accumulated heading |
| `starting_low_speed_turn` | Implemented | Temporal Rule | turn + trigger speed |
| `starting_high_speed_turn` | Implemented | Temporal Rule | turn + trigger speed |

## 3. Lane Change

| Scenario | 상태 | 방식 | 비고 |
|---|---|---|---|
| `changing_lane` | Implemented | Geometry + Temporal | logical lane stability 필요 |
| `changing_lane_to_left` | Implemented | Geometry + Temporal | target lane direction |
| `changing_lane_to_right` | Implemented | Geometry + Temporal | target lane direction |

Intersection 내부의 lane-ID 변화가 false lane change로 잡히지 않도록 suppression/stability logic이 존재한다.

## 4. Crosswalk / Stopline

| Scenario | 상태 | 방식 |
|---|---|---|
| `traversing_crosswalk` | Implemented | Ego footprint + crosswalk geometry |
| `on_stopline_crosswalk` | Implemented | Stopline / crosswalk spatial relation |
| `stationary_at_crosswalk` | Implemented | Geometry + ego speed |
| `stopping_at_crosswalk` | Implemented | Geometry + temporal deceleration |
| `accelerating_at_crosswalk` | Implemented | Geometry + temporal acceleration |

Threshold는 `configs/direct_scenarios.yaml`의 `road_feature_relations`를 확인한다.

## 5. Nearby Object Interaction

| Scenario | 상태 | 방식 |
|---|---|---|
| `near_high_speed_vehicle` | Implemented | Object relation + estimated/measured speed |
| `near_long_vehicle` | Implemented | Class/dimension + proximity |
| `near_multiple_bikes` | Implemented | Proximity count |
| `near_multiple_motorcycle` | Implemented | Proximity count |
| `near_multiple_pedestrians` | Implemented | Proximity count |
| `near_multiple_vehicles` | Implemented | Proximity count |

Object association과 velocity 추정 품질에 영향을 받으므로 visual review가 필요하다.

## 6. Pedestrian / Crosswalk Interaction

| Scenario | 상태 | 방식 |
|---|---|---|
| `near_pedestrian_on_crosswalk` | Implemented | Pedestrian-crosswalk overlap / edge distance |
| `near_pedestrian_on_crosswalk_with_ego` | Implemented | 위 조건 + ego proximity relation |

## 7. Object Path Crossing

| Scenario | 상태 | 방식 |
|---|---|---|
| `crossed_by_bike` | Implemented | Ego forward arc/path crossing |
| `crossed_by_motorcycle` | Implemented | Ego forward arc/path crossing |
| `crossed_by_vehicle` | Implemented | Ego forward arc/path crossing |

현재 config의 detector version 문자열은 `phase3c-forward-arc-crossing-v3`이다. 이는 개발 이력에서 이어진 이름이며, 현재 handover에서는 별도의 Phase 구분으로 사용하지 않는다.

## 8. Traffic / Lead-Trail Interaction

아래 항목은 active rule registry에는 포함되어 있으나 configuration provenance가 `poc_requires_calibration`으로 명시되어 있다. 따라서 **구현됨 = 검증 완료**로 해석하지 않는다.

| Scenario | 상태 | 주요 근거 |
|---|---|---|
| `following_lane_with_slow_lead` | PoC / Calibration Needed | same-lane lead + lead speed |
| `changing_lane_with_lead` | PoC / Calibration Needed | lane-change episode + lead relation |
| `changing_lane_with_trail` | PoC / Calibration Needed | lane-change episode + trail relation |
| `stopping_with_lead` | PoC / Calibration Needed | stopping transition + lead |
| `stopping_without_lead` | PoC / Calibration Needed | stopping transition + no lead |
| `stationary_in_traffic` | PoC / Calibration Needed | stationary ego + surrounding vehicles |
| `behind_bike` | PoC / Calibration Needed | same corridor / lead-like relation |
| `behind_long_vehicle` | PoC / Calibration Needed | long vehicle ahead relation |
| `behind_pedestrian_on_driveable` | PoC / Calibration Needed | pedestrian corridor relation |
| `waiting_for_pedestrian_to_cross` | PoC / Calibration Needed | ego stop/yield + pedestrian conflict relation |
| `near_barrier_on_driveable` | PoC / Calibration Needed | barrier intrusion / distance |

## 9. Following-lane 계열

Repository에는 별도 `src/ms_odd_tagging/scenarios/following_lane/` package가 존재한다. README와 기존 문서에서 `following_lane` 관련 pipeline을 별도로 설명하고 있으므로, 다음 label의 실제 wiring 여부는 해당 package와 current GT reviewer를 함께 확인한다.

- `following_lane_with_lead`
- `following_lane_without_lead`

이 두 항목은 **현재 `RULE_BASED_SCENARIOS` constant에는 포함되어 있지 않으므로**, main rule registry와 별도 following-lane pipeline을 혼동하지 않는다.

## 10. Traffic-light 관련 상태

`configs/direct_scenarios.yaml`에는 `traffic_light_context` feature configuration이 존재하지만, 현재 `RULE_BASED_SCENARIOS` 목록에는 traffic-light behavior label이 직접 포함되어 있지 않다.

따라서 다음과 같은 label은 현재 문서에서 **active direct-rule 구현 완료로 표시하지 않는다.**

예:

- `on_stopline_traffic_light`
- `on_traffic_light_intersection`
- `traversing_traffic_light_intersection`
- `accelerating_at_traffic_light*`
- `stationary_at_traffic_light*`
- `stopping_at_traffic_light*`

Traffic-light context는 VLM episode candidate 또는 향후 direct behavior detector의 evidence로 사용하는 구조가 포함되어 있으므로 추가 wiring/검증이 필요하다.

## 11. VLM PoC

`src/ms_odd_tagging/qwen_vlm_poc/`에는 다음 기능이 분리되어 있다.

- candidate generation
- evidence construction
- prompt
- client
- validation
- merging
- visualization

VLM 결과는 rule-based scenario와 동일한 신뢰 수준으로 간주하지 말고 scenario별 evaluation 후 사용한다.

## 12. Explicit Exclusion

registry에는 다음 개념이 explicit exclusion으로 정의되어 있다.

- `pickup_dropoff`
- `pickup_with_pedestrian`
- `dropoff_with_pedestrian`

관련 taxonomy label을 추가할 때 기존 exclusion 목적을 먼저 확인한다.

## 13. 유지보수 원칙

새 scenario를 추가하거나 상태를 변경하면 이 문서와 함께 다음을 수정한다.

1. `configs/direct_scenarios.yaml`
2. `registry.py`
3. detector / feature module
4. tests
5. GT reviewer support status
6. 본 `04_SCENARIO_STATUS.md`
