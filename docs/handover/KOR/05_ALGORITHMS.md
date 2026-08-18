# Algorithms

## 1. 목적

이 문서는 현재 rule / geometry 기반 Motional Scenario detector의 핵심 아이디어를 설명한다. 정확한 threshold와 최신 구현은 반드시 source code와 `configs/direct_scenarios.yaml`을 기준으로 확인한다.

## 2. 공통 처리 원칙

대부분의 detector는 다음 순서를 따른다.

```text
Canonical Frames
      │
      ▼
Feature / Relation Extraction
      │
      ▼
Frame-level State
      │
      ▼
Temporal Filtering / Hysteresis
      │
      ▼
Event Segmentation
      │
      ▼
ScenarioEvent(start, end, evidence)
```

Motional Scenario는 한 frame의 순간 상태가 아니라 일정 시간 유지되는 behavior인 경우가 많으므로 threshold 하나보다 temporal filtering이 중요하다.

## 3. Speed Band

관련 파일:

```text
features/ego_motion.py
tagger/rule_based/dynamics.py
```

현재 speed band:

- stationary: 0.0 <= v < 0.5 m/s
- low: 0.5 <= v < 5.0 m/s
- medium: 5.0 <= v < 15.0 m/s
- high: v >= 15.0 m/s

speed band는 taxonomy-defined threshold로 config에 기록되어 있다.

## 4. Lateral Acceleration

`high_lateral_acceleration`은 ego motion에서 계산한 lateral acceleration의 절대값을 사용한다.

현재 config에는 entry/exit threshold를 다르게 두어 hysteresis를 적용한다. 순간적인 boundary crossing으로 event가 반복적으로 켜졌다 꺼지는 것을 줄이기 위한 목적이다.

## 5. Jerk

`high_magnitude_jerk`는 acceleration vector magnitude 변화량을 시간으로 나누어 계산한다.

중요 포인트:

- isolated spike rejection
- sample gap 검증
- minimum duration
- entry / exit hysteresis

Trajectory noise가 크면 jerk는 매우 민감하므로 raw derivative 결과만 사용하지 않는다.

## 6. Turn Detection

관련 파일:

```text
tagger/rule_based/turns.py
```

주요 evidence:

- yaw rate
- accumulated heading change
- event duration
- trigger frame speed

left/right는 heading change sign convention에 따라 결정한다.

`starting_low_speed_turn` / `starting_high_speed_turn`은 turn event에 trigger speed classification을 결합한다.

Lane continuity가 유지되는 상황에서 단순한 도로 curvature를 turn으로 잘못 잡는 문제를 줄이기 위해 별도 accumulated heading threshold가 존재한다.

## 7. Lane Change

관련 파일:

```text
tagger/rule_based/lane_changes.py
```

핵심은 순간 lane ID 변경을 lane change로 보지 않는 것이다.

대략적인 조건:

1. source lane에서 일정 시간 안정적으로 유지
2. target lane으로 assignment 변화
3. target lane에서도 일정 시간 안정적으로 유지
4. missing frame / temporary inconsistency 허용 범위 확인
5. minimum event duration 만족

Intersection에서는 lane topology가 복잡하게 변하므로 다음 suppression logic이 있다.

- intersection 내부 lane change 억제
- intersection turn 중 lane change 억제
- intersection exit 이후 lane stability 확인

## 8. Lane Reconstruction / Following Lane

Lane 관련 기능은 단순 line ID 비교만으로 안정적으로 처리하기 어렵다.

주요 개념:

- physical lane assignment
- logical lane continuity
- adjacent left/right lane relation
- lead / trail object relation

실제 하나의 주행 lane이 여러 LD segment로 나뉠 수 있으므로 logical route 연결이 필요하다. 반대로 logical continuity를 visualization의 physical ego lane과 동일하게 표시하면 인접 lane까지 ego lane처럼 보이는 문제가 발생할 수 있다.

관련 package:

```text
src/ms_odd_tagging/scenarios/following_lane/
src/ms_odd_tagging/ld_topology/
```

## 9. Crosswalk / Stopline

관련 파일:

```text
features/road_feature_relations.py
tagger/rule_based/crosswalks.py
```

Point distance 하나만 사용하지 않고 ego footprint와 road feature geometry의 spatial relation을 이용한다.

주요 상태:

- approaching
- overlap / on feature
- traversing
- stopped near feature
- accelerating / decelerating near feature

중복 detection이나 frame 간 누락을 처리하기 위해 feature association과 missing-gap tolerance를 적용한다.

## 10. Nearby Object Interaction

관련 파일:

```text
features/object_relations.py
tagger/rule_based/object_interactions.py
```

주요 처리:

1. OD class를 vehicle / pedestrian / bicycle / motorcycle 등 normalized category로 mapping
2. frame 간 object association
3. ego-relative position / distance 계산
4. object velocity 추정
5. proximity region 내 count 또는 속성 확인

`near_multiple_*`은 proximity region 내 객체 수를 사용한다.

`near_long_vehicle`은 class 및 dimension threshold를 함께 사용한다.

`near_high_speed_vehicle`은 object velocity 품질에 민감하다.

## 11. Pedestrian on Crosswalk

관련 파일:

```text
features/pedestrian_crosswalk_relations.py
tagger/rule_based/pedestrian_crosswalks.py
```

Pedestrian bbox/footprint와 crosswalk geometry의 overlap 또는 edge distance를 이용해 association한다.

주요 문제는 동일 crosswalk 유지, detection 누락, overlap ambiguity이므로 hysteresis와 association tolerance를 둔다.

## 12. Crossed-by Object

관련 파일:

```text
features/object_path_crossing_relations.py
tagger/rule_based/object_path_crossings.py
```

Ego 앞쪽의 future path/arc 영역과 object trajectory가 교차하는지를 시간적으로 확인한다.

사용 evidence 예:

- ego path look-ahead
- object ground speed
- crossing angle
- projected intersection horizon
- lateral displacement
- side stability

단순히 object가 ego 앞을 한 번 지나간 frame만 보는 것이 아니라 실제 crossing motion을 확인한다.

## 13. Traffic Interaction

관련 파일:

```text
features/traffic_relations.py
tagger/rule_based/traffic_interactions.py
```

주요 relation:

- same-lane lead
- trail
- lead gap
- relative speed
- driveable corridor
- surrounding vehicle density

이를 조합하여 slow lead, stopping with/without lead, stationary in traffic, behind object 등의 scenario를 판별한다.

현재 이 영역은 config provenance가 `poc_requires_calibration`이므로 dataset 확장 후 threshold 재검증이 필요하다.

## 14. Traffic-light Context

관련 파일:

```text
features/traffic_light_context.py
```

현재 traffic-light detection은 scenario label 그 자체보다 다음 context를 구성하는 데 사용된다.

- relevant traffic light candidate
- stopline ↔ traffic-light relation
- intersection approach context
- ego stationary/stopping/accelerating state

OD traffic light는 static-like sparse detection으로 제공될 수 있으므로 single-frame 존재 여부만 이용하면 context가 끊길 수 있다. 향후 temporal persistence가 핵심 개선 항목이다.

## 15. VLM

관련 package:

```text
src/ms_odd_tagging/qwen_vlm_poc/
```

구조:

```text
Candidate Generation
      ↓
Evidence Construction
      ↓
Prompt + BEV
      ↓
VLM Inference
      ↓
Validation
      ↓
Episode Merging
```

VLM에 entire recording을 무조건 전달하는 방식보다 deterministic candidate gating을 먼저 수행하는 것을 권장한다.

## 16. 새 Detector 추가 절차

1. taxonomy / policy 정의 확인
2. 필요한 evidence 목록 작성
3. existing canonical/feature에서 evidence가 있는지 확인
4. 없으면 reusable feature layer에 추가
5. frame-level state 구현
6. temporal segmentation 적용
7. explorer visualization 추가
8. GT 생성
9. small-set evaluation
10. threshold calibration
11. registry/config/tests/documentation 업데이트
