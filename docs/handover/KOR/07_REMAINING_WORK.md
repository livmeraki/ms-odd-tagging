# Remaining Work

이 문서는 후속 개발 시 **우선적으로 해결해야 할 항목을 중요도 순으로** 정리한다. 순서는 단순한 구현 난이도가 아니라, 현재 결과의 신뢰성에 미치는 영향, 여러 scenario에 공통으로 영향을 주는 정도, 다른 개선 작업의 선행 조건 여부를 기준으로 한다.

---

## 1. Evaluation Methodology 재검증

### 현재 문제의식

현재까지 사용한 evaluation 결과는 참고는 가능하지만, **현재 시스템의 신뢰 가능한 공식 baseline이라고 보기에는 부족하다.**

특히 다음 요소가 결과를 바꿀 수 있다.

- GT 작성 기준
- prediction-prefill에 의한 reviewer bias
- frame input과 prediction tag의 sampling frame mismatch
- sampled-frame 평가인지 event-range 평가인지의 차이
- scenario imbalance
- event start/end tolerance
- evaluation recording list와 scenario subset

### 필요한 작업

먼저 evaluation contract를 고정해야 한다.

```text
1. 무엇을 평가하는가?
   - frame state
   - event interval
   - recording-level presence

2. 어떤 recording을 사용하는가?

3. 어떤 scenario subset을 평가하는가?

4. GT 작성 기준과 review process는 무엇인가?

5. event boundary tolerance는 어떻게 정의하는가?

6. sampling alignment는 어떻게 보장하는가?
```

### GT 신뢰성 확인

가능하면 작은 subset에서 동일 scene을 두 번 독립적으로 검토하거나 다른 reviewer가 재검토해 disagreement를 확인한다.

특히 event start/end가 중요한 scenario에서는 단순 Yes/No consistency뿐 아니라 boundary consistency도 확인한다.

### metric

단일 overall F1만 사용하지 말고 다음을 함께 기록한다.

- scenario별 positive GT count
- scenario별 Precision / Recall / F1
- micro metric
- macro metric
- FP/FN example review

Event-based evaluation을 도입한다면 temporal IoU 또는 start/end tolerance를 명시적으로 정의한다.

---

## 2. Lane Detection + Ego Lane Inference 개선

### 현재 상태

Lane 관련 기능은 ALT LD에서 제공되는 lane/boundary geometry를 기반으로 ego lane, adjacent lane, lane continuity를 추론한다.

이 과정은 raw image에서 lane marking을 새로 검출하는 전통적인 lane detection과는 다르다. 현재 프로젝트에서 실제 문제의 핵심은 **lane geometry reconstruction과 ego lane inference**이다.

### 현재 부족한 부분

다음과 같은 구간에서 reconstruction 품질이 떨어질 수 있다.

- 실제 하나의 lane이 여러 LD segment로 끊겨 있음
- lane segment가 너무 짧거나 일부 boundary만 존재함
- intersection 내부에서 lane geometry가 약하거나 급격히 바뀜
- split/merge 구간
- **주행 가능한 road 영역은 존재하지만 lane geometry 자체가 제공되지 않거나 충분하지 않은 구간**

마지막 경우는 현재 방식에서 가장 중요한 미해결 항목 중 하나다. 명시적인 lane geometry가 없으면 단순 lane-ID continuity만으로는 ego lane을 안정적으로 유지하기 어렵다.

### 필요한 구현 방향

Lane 정보가 충분하지 않은 구간에 대해 fallback reconstruction을 설계할 필요가 있다. 검토할 수 있는 evidence는 다음과 같다.

- road boundary / driveable-area geometry
- 이전 frame과 이후 frame의 valid lane geometry
- ego trajectory
- ego heading 및 curvature continuity
- nearby lane direction
- predecessor/successor relation
- intersection entry/exit geometry

이때 실제 source에 없는 lane을 과도하게 생성하지 않도록 confidence 개념이 필요하다. 예를 들면:

```text
explicit_ld_lane
inferred_from_continuity
inferred_from_road_geometry
unknown
```

처럼 reconstruction provenance 또는 confidence를 유지하면 downstream detector가 inferred lane을 explicit lane과 동일하게 신뢰하는 문제를 줄일 수 있다.

### 반드시 함께 검증할 downstream 기능

Lane reconstruction 수정은 다음 기능을 동시에 regression test 해야 한다.

- `following_lane_with_lead`
- `following_lane_without_lead`
- `changing_lane`
- `changing_lane_to_left`
- `changing_lane_to_right`
- lead/trail relation
- turn detection
- intersection exit lane stability

### 권장 regression set

최소 다음 scene을 고정해서 사용한다.

- straight road with clear lanes
- left lane change
- right lane change
- lane split
- lane merge
- intersection straight traversal
- intersection left/right turn
- short lane segment
- missing boundary
- road-only / insufficient-lane-information section

---

## 3. Speed / Lateral Acceleration / Jerk Signal Spike 검증

### 현재 확인된 우려

Speed, acceleration, lateral acceleration, jerk 계열에서 일부 frame에 순간적인 spike가 나타날 수 있다.

이 문제가 실제 vehicle dynamics인지, source trajectory의 noise인지, derivative 계산 과정에서 증폭된 artifact인지는 충분히 확정되지 않았다.

### 먼저 해야 할 일

Filtering을 바로 추가하기보다 아래 순서로 원인을 추적해야 한다.

1. raw trajectory/odometry에 동일한 spike가 존재하는지
2. timestamp 또는 frame interval이 순간적으로 비정상인지
3. speed 계산 단계에서 spike가 생기는지
4. acceleration 계산에서 증폭되는지
5. lateral acceleration 계산의 heading/yaw convention에 문제가 없는지
6. jerk differentiation에서 작은 오차가 확대되는지

이 부분은 **한수와 source signal의 기대 특성과 filtering 허용 범위를 다시 확인할 필요가 있다.**

### Filtering을 적용한다면

Filtering을 넣는 목적은 spike를 제거하는 것이 아니라 **실제 dynamic event를 보존하면서 measurement/computation artifact만 줄이는 것**이어야 한다.

따라서 다음 비교가 필요하다.

```text
raw signal
vs
filtered signal
vs
GT event boundary
```

검토 후보:

- median filter
- bounded outlier rejection
- sample-gap-aware derivative
- short isolated spike rejection
- hysteresis / minimum-duration 강화

특정 filter를 먼저 정답으로 가정하지 않는다.

특히 aggressive smoothing은 실제 급회전/급가감속 onset과 jerk peak를 약화시킬 수 있으므로 detector metric과 waveform을 함께 비교해야 한다.

---

## 4. Frame Sampling Contract 통일

Frame Input과 `recording_frame_tags_1fps`는 같은 nominal sampling rate를 사용하더라도 source frame 선택 방식이 다르면 정확한 frame index가 달라질 수 있다.

현재 GT Workspace는 exact frame index를 먼저 사용하고 timestamp-nearest fallback을 사용하지만, 장기적으로는 두 exporter가 같은 sampling helper를 사용하도록 통일하는 것이 가장 안전하다.

목표:

```text
one sampling policy
→ one selected source frame
→ same frame.json / BEV / prediction tag / GT reference
```

이렇게 되면 evaluation alignment와 GT Workspace logic을 모두 단순화할 수 있다.

---

## 5. VLM의 BEV 이해 능력 검증

### 현재 필요한 질문

VLM scenario 성능을 보기 전에 먼저 다음을 확인해야 한다.

> **모델이 BEV image의 기본 표현 자체를 실제로 올바르게 이해하고 있는가?**

현재 BEV에는 ego, surrounding objects, orientation, LD geometry, legend 등이 포함될 수 있다. Scenario prompt에 정답을 맞추더라도 이미지 자체를 잘 이해해서 맞춘 것인지, prompt/priors를 이용해 추측한 것인지 분리해야 한다.

### 별도로 검증해야 할 BEV literacy

Controlled test set을 만들어 최소 다음을 확인한다.

- ego vehicle 식별
- ego forward orientation 이해
- object 존재 여부
- ahead / behind / left / right 관계
- pedestrian 존재 여부
- pedestrian 위치 방향
- lane/road geometry의 기본 위치 관계
- legend 유무에 따른 성능 변화

### 권장 실험 구조

```text
Full legend
No color legend
No orientation legend
No legend
```

와 같은 legend ablation을 유지하되, scene-level scenario accuracy와 별개로 **BEV symbol literacy / spatial understanding metric**을 기록한다.

또한 object가 실제로 존재하지 않는 negative frame을 충분히 포함해야 한다. 존재하지 않는 pedestrian이나 vehicle을 추측하는 false positive가 있으면 scenario-level inference에 직접 영향을 준다.

### 다음 단계

BEV literacy가 불안정하면 다음 중 어떤 문제가 있는지 분리한다.

- BEV drawing convention
- legend 표현
- resolution / object size
- selected image frame
- prompt wording
- model capability

모델을 바꾸기 전에 visualization/evidence 자체가 읽을 수 있는 형태인지 먼저 확인해야 한다.

---

## 6. VLM Candidate Recall과 VLM Decision Accuracy 분리

VLM pipeline은 다음 두 문제를 별도로 평가해야 한다.

### A. Candidate Recall

정답 event가 VLM inference 대상으로 실제 전달되었는가?

Candidate가 생성되지 않았다면 prompt나 model을 아무리 개선해도 FN은 해결되지 않는다.

### B. Decision Accuracy

정답 candidate가 주어졌을 때 VLM이 올바른 scenario를 판단했는가?

따라서 benchmark에는 최소 다음을 분리해서 기록한다.

```text
GT events
candidate hit rate
candidate count
VLM accepted/rejected count
VLM TP / FP / FN
```

---

## 7. Traffic-light Temporal Persistence

Traffic-light OD는 실제 scene에 존재해도 annotation에서는 sparse하게 나타날 수 있다. 기본 1 FPS sampled BEV에서는 해당 observation을 놓칠 수도 있다.

향후에는 다음을 검토한다.

- existence persistence
- missing-gap tolerance
- stopline ↔ traffic-light association persistence
- intersection context와의 연계
- confidence decay / expiry

Source annotation에 traffic-light state가 없으면 state를 임의 생성하지 않는다.

---

## 8. Speed Band의 고정값 사용 여부 재검토

### 현재 상태

현재 speed scenario는 fixed global speed band를 사용한다.

```text
stationary: 0.0 <= v < 0.5 m/s
low:        0.5 <= v < 5.0 m/s
medium:     5.0 <= v < 15.0 m/s
high:       v >= 15.0 m/s
```

이 기준은 현재 data에서 일관된 rule 적용이 가능하다는 장점이 있지만, 실제 주행 context를 완전히 반영하지는 않는다.

### 향후 개선 가능성

ALT에서 **해당 도로 구간의 speed-limit 정보가 안정적으로 제공되는 경우**, fixed global threshold 대신 speed limit에 상대적인 dynamic speed categorization을 검토할 수 있다.

예를 들어 동일한 ego speed라도:

- 제한속도 30 km/h 구간
- 제한속도 50 km/h 구간
- 제한속도 80 km/h 구간

에서 `low / medium / high`의 의미가 동일하지 않을 수 있다.

단, speed-limit data가 실제 source contract에 포함되기 전에는 추정 speed limit을 사용해 rule을 변경하지 않는다.

### 변경 시 함께 확인할 항목

Speed band는 단순 speed label에만 영향을 주지 않는다.

특히:

- `low_magnitude_speed`
- `medium_magnitude_speed`
- `high_magnitude_speed`
- `starting_low_speed_turn`
- `starting_high_speed_turn`

과 같이 speed classification을 직접 사용하는 scenario를 함께 재검증해야 한다.

---

## 9. GT Workspace 확장성과 성능

Dataset이 커질수록 초기 recording scan과 prediction/GT indexing 비용이 커질 수 있다.

필요 시 다음을 검토한다.

- recording manifest
- summary cache
- lazy loading
- GT metadata single-read
- scenario index cache

별도 profiler 버전을 다시 만들기보다 현재 workspace 내부에서 optional timing/logging을 제공하는 방향이 좋다.
