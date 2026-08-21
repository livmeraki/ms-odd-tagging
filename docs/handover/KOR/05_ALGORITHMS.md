# Algorithms

## 1. 목적

이 문서는 현재 rule / geometry 기반 Motional Scenario detector의 핵심 아이디어와, 후속 개발자가 반드시 다시 검증해야 하는 motion/lane 관련 가정을 설명한다. 정확한 threshold와 최신 runtime 동작은 source code와 `configs/direct_scenarios.yaml`을 기준으로 확인한다.

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

Motional Scenario는 한 frame의 순간 상태보다 일정 시간 동안 유지되는 behavior인 경우가 많다. 따라서 단일 threshold뿐 아니라 signal 품질, timestamp 정합, hysteresis, minimum duration, event boundary를 함께 봐야 한다.

## 3. Speed Band

관련 파일:

```text
features/ego_motion.py
tagger/rule_based/dynamics.py
```

현재 speed band는 고정 threshold를 사용한다.

- stationary: `0.0 <= v < 0.5 m/s`
- low: `0.5 <= v < 5.0 m/s`
- medium: `5.0 <= v < 15.0 m/s`
- high: `v >= 15.0 m/s`

현재 구조에서는 dataset 전체에 동일한 기준을 적용한다. 다만 실제 주행에서 저속/중속/고속의 의미는 도로의 제한속도와 주행 환경에 따라 달라질 수 있다.

향후 ALT에서 구간별 speed-limit 정보가 안정적으로 제공된다면, fixed global band를 그대로 유지할지 또는 **해당 도로 구간의 제한속도에 상대적인 dynamic speed band**로 바꿀지 재검토할 수 있다. 예를 들어 동일한 12 m/s라도 제한속도 30 km/h 도로와 80 km/h 도로에서 의미가 다를 수 있으므로, speed-limit 정보가 source data에 포함되는 시점에는 taxonomy/policy 정의와 함께 기준을 다시 정해야 한다.

중요한 점은 speed-limit data가 실제 source에 들어오기 전에는 임의로 제한속도를 추정해 band를 변경하지 않는 것이다.

## 4. Speed / Acceleration Signal 품질

Speed, acceleration, lateral acceleration, jerk 계열의 신호에는 일부 recording/frame에서 순간적인 spike가 관찰될 수 있다. 이 spike를 곧바로 실제 vehicle dynamics로 간주하면 `high_lateral_acceleration`, `high_magnitude_jerk`, speed-band 전환과 같이 derivative 또는 threshold에 민감한 scenario에서 false event가 발생할 수 있다.

후속 개발 시에는 filtering부터 추가하기 전에 먼저 spike의 원인을 확인해야 한다.

확인 순서:

1. source trajectory/odometry 자체에 spike가 있는지
2. timestamp interval 또는 frame gap이 비정상인지
3. velocity/acceleration 계산 과정에서 numerical differentiation이 spike를 증폭하는지
4. coordinate/heading 변환 과정에서 discontinuity가 있는지
5. 실제 vehicle motion인지 annotation/trajectory artifact인지

특히 이 부분은 **한수님과 source signal의 기대 특성, 허용 가능한 노이즈 범위, filtering 적용 가능 여부를 다시 확인한 뒤** 결정하는 것이 좋다.

Filtering이 필요하다고 판단되더라도 단순 smoothing을 먼저 넣지 않는다. 과도한 low-pass/median filtering은 실제 급가감속, 급회전, jerk event의 onset과 peak를 약화시키거나 event boundary를 지연시킬 수 있다. 따라서 raw signal과 filtered signal을 함께 비교하고, positive/negative GT에서 scenario precision/recall이 실제로 개선되는지 검증해야 한다.

## 5. Lateral Acceleration

`high_lateral_acceleration`은 ego motion에서 계산한 lateral acceleration의 절대값을 사용한다.

현재 config에는 entry/exit threshold를 다르게 두어 hysteresis를 적용한다. 순간적인 threshold crossing으로 event가 반복적으로 켜졌다 꺼지는 것을 줄이기 위한 목적이다.

후속 검증 항목:

- lateral acceleration 계산식과 heading/yaw convention 재확인
- source sampling interval 변화에 대한 안정성 확인
- spike가 실제 motion인지 derivative artifact인지 확인
- filtering이 필요한 경우 event peak와 duration 보존 여부 확인

## 6. Jerk

`high_magnitude_jerk`는 acceleration 변화량을 시간으로 나누어 계산하므로 source noise에 특히 민감하다.

중요 포인트:

- sample gap 검증
- isolated spike 처리
- minimum duration
- entry / exit hysteresis
- acceleration 자체의 품질 검증

Jerk는 derivative chain의 가장 뒤쪽에 있기 때문에 작은 trajectory/velocity 오차도 크게 증폭될 수 있다. 따라서 jerk threshold를 조정하기 전에 upstream speed/acceleration signal을 먼저 확인한다.

## 7. Turn Detection

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

`starting_low_speed_turn` / `starting_high_speed_turn`은 turn event에 trigger speed classification을 결합한다. 따라서 speed-band 정의를 변경하면 이 scenario들의 의미와 threshold도 함께 재검토해야 한다.

Lane continuity가 유지되는 상황에서 단순한 도로 curvature를 turn으로 잘못 잡는 문제를 줄이기 위해 accumulated heading change와 temporal condition을 함께 본다.

## 8. Lane Change

관련 파일:

```text
tagger/rule_based/lane_changes.py
```

핵심은 순간적인 lane ID 변경을 lane change로 바로 판단하지 않는 것이다.

일반적인 조건:

1. source lane에서 일정 시간 안정적으로 유지
2. target lane으로 assignment 변화
3. target lane에서도 일정 시간 안정적으로 유지
4. missing frame / temporary inconsistency 허용 범위 확인
5. minimum event duration 만족

Intersection에서는 lane topology가 복잡하게 변하므로 intersection 내부/turn 구간의 suppression과 exit 이후 lane stability를 함께 확인한다.

## 9. Lane Geometry Reconstruction / Ego Lane Inference

이 프로젝트에서 흔히 말하는 "lane detection"은 raw sensor image에서 lane marking을 새로 검출하는 의미라기보다, **ALT LD에서 제공된 lane/boundary geometry를 바탕으로 ego가 어느 lane에 있는지와 lane continuity를 재구성하는 과정**에 가깝다. 따라서 문서에서는 가능하면 `lane geometry reconstruction` 또는 `ego lane inference`라고 표현한다.

관련 package:

```text
src/ms_odd_tagging/scenarios/following_lane/
src/ms_odd_tagging/ld_topology/
```

주요 개념:

- physical lane assignment
- logical lane continuity
- adjacent left/right lane relation
- lead / trail object relation

현재 주요 한계는 다음과 같다.

- 하나의 실제 lane이 여러 LD segment로 분리될 수 있음
- short/missing LD segment로 ego lane assignment가 불안정해질 수 있음
- intersection에서 physical lane geometry 자체가 명확하지 않을 수 있음
- **일부 구간은 주행 가능한 road 영역은 존재하지만 lane geometry 정보가 충분하지 않아 lane reconstruction이 사실상 불가능하거나 매우 약해질 수 있음**

마지막 경우는 threshold 조정만으로 해결하기 어렵다. LD lane 정보가 없는 구간에 대해서는 road boundary/driveable-area geometry, 이전/이후 lane continuity, ego trajectory, heading continuity 등 다른 evidence를 이용한 fallback reconstruction을 설계할 필요가 있다. 단, 이러한 fallback은 실제 lane을 source data보다 더 강하게 "추정"하게 되므로 confidence를 함께 관리하고 regression set에서 검증해야 한다.

또한 logical continuity를 visualization의 physical ego lane과 동일하게 표시하면 인접 lane까지 ego lane처럼 보이는 문제가 생길 수 있으므로 두 개념은 계속 분리한다.

## 10. Crosswalk / Stopline

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

## 11. Nearby Object Interaction

관련 파일:

```text
features/object_relations.py
tagger/rule_based/object_interactions.py
```

주요 처리:

1. OD class normalization
2. frame 간 object association
3. ego-relative position / distance 계산
4. object velocity 추정
5. proximity region 내 count 또는 속성 확인

`near_multiple_*`은 proximity region 내 객체 수를 사용한다. `near_long_vehicle`은 class/dimension evidence를 함께 사용하고, `near_high_speed_vehicle`은 object velocity 품질에 특히 민감하다.

## 12. Pedestrian on Crosswalk

관련 파일:

```text
features/pedestrian_crosswalk_relations.py
tagger/rule_based/pedestrian_crosswalks.py
```

Pedestrian bbox/footprint와 crosswalk geometry의 overlap 또는 edge distance를 이용해 association한다. 동일 crosswalk 유지, detection 누락, overlap ambiguity 때문에 hysteresis와 association tolerance가 중요하다.

## 13. Crossed-by Object

관련 파일:

```text
features/object_path_crossing_relations.py
tagger/rule_based/object_path_crossings.py
```

Ego 앞쪽의 future path/arc 영역과 object trajectory가 시간적으로 교차하는지를 확인한다.

사용 evidence 예:

- ego path look-ahead
- object ground speed
- crossing angle
- projected intersection horizon
- lateral displacement
- side stability

## 14. Traffic Interaction

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

이를 조합하여 slow lead, stopping with/without lead, stationary in traffic, behind object 등의 scenario를 판별한다. 이 영역은 추가 dataset/GT에서 calibration이 필요하다.

## 15. Traffic-light Context

관련 파일:

```text
features/traffic_light_context.py
```

Traffic-light detection은 scenario label 자체보다 다음 context를 구성하는 데 사용된다.

- relevant traffic-light candidate
- stopline ↔ traffic-light relation
- intersection approach context
- ego stationary/stopping/accelerating state

Traffic light OD가 sparse하게 제공되는 경우 single-frame 존재 여부만 사용하면 context가 끊길 수 있다. Temporal persistence는 후속 구현 대상으로 남아 있다. Source annotation에 traffic-light state가 없다면 state를 임의로 생성하지 않는다.

## 16. VLM

관련 package:

```text
src/ms_odd_tagging/vlm/
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

VLM은 전체 recording을 brute-force로 분류하기보다 deterministic candidate gating 뒤에 사용한다. 다만 현재는 **VLM이 BEV의 ego, object, orientation, relative position을 실제로 일관되게 이해하는지 별도의 controlled benchmark로 다시 확인해야 한다.** Scenario accuracy만 보고 BEV 이해 능력이 검증되었다고 간주하지 않는다.

## 17. 새 Detector 추가 절차

1. taxonomy / policy 정의 확인
2. 필요한 evidence 목록 작성
3. canonical/feature layer에 기존 evidence가 있는지 확인
4. 없으면 reusable feature layer에 추가
5. frame-level state 구현
6. temporal segmentation 적용
7. explorer visualization 추가
8. GT 생성/검토
9. fixed evaluation subset에서 평가
10. threshold/calculation 검증
11. registry/config/tests/documentation 업데이트
