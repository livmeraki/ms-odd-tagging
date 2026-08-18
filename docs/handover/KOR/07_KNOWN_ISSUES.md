# Known Issues

## 1. 목적

이 문서는 현재 pipeline에서 이미 확인되었거나 구조상 주의가 필요한 문제를 정리한다. 새 담당자가 동일한 문제를 다시 처음부터 조사하지 않도록 **현상 / 원인 / 영향 / 권장 확인 방법** 중심으로 작성한다.

## 2. Lane Reconstruction / Continuity

### 현상

- 실제로 같은 lane인데 LD segment가 분리되어 lane ID가 바뀜
- 짧은 lane 또는 일부 boundary만 존재하는 구간에서 ego lane이 불안정해짐
- 인접 lane이 ego lane처럼 보이는 visualization 오류/혼동이 발생할 수 있음

### 원인

LD는 physical segment 단위로 제공되며 실제 주행 continuity와 1:1로 일치하지 않는다. logical route를 만들기 위해 segment를 연결하면 physical assignment와 logical continuity가 서로 다른 개념이 된다.

### 영향

- `changing_lane*`
- `following_lane*`
- lead/trail relation
- intersection exit lane stability

### 확인 방법

- physical `lane_id`와 logical route ID를 따로 확인
- explorer에서 left / ego / right lane geometry를 동시에 확인
- lane endpoint, heading continuity, predecessor/successor relation 확인

## 3. Intersection에서 False Lane Change

### 현상

교차로 진입/통과 중 lane ID가 크게 바뀌면서 실제 차선 변경이 아닌데 `changing_lane`으로 판단될 수 있다.

### 현재 대응

config에 다음 logic이 존재한다.

- intersection 내부 lane change suppression
- intersection turn 중 suppression
- intersection exit 후 target lane stability 확인

### 주의

threshold를 낮추면 recall은 올라갈 수 있지만 intersection false positive가 다시 증가할 수 있다.

## 4. Intersection Look-ahead / Activation

과거 topology 실험에서 ego가 아직 일반 도로를 주행 중인데 먼 intersection component가 너무 일찍 활성화되는 문제가 있었다.

권장:

- inside polygon 여부 우선
- entry tolerance 제한
- approach distance gating
- hysteresis 적용
- geometry result를 explorer로 확인

## 5. LD Missing / Short Segment

LD line이 짧거나 frame마다 일부 사라지는 경우 lane polygon 또는 topology reconstruction이 불안정하다.

단순히 현재 frame의 line만 사용하는 것보다 temporal continuity를 활용할 필요가 있지만, 과도한 persistence는 잘못된 geometry를 오래 유지할 수 있다.

## 6. Traffic-light Detection의 Temporal Sparsity

### 현상

Traffic light OD가 실제 scene에는 계속 존재하지만 annotation에서는 특정 frame에만 등장하고 이후 사라질 수 있다.

Frame input/BEV는 기본 1 FPS sampling이므로, 10 FPS source에서 traffic-light annotation이 잠깐만 존재하면 sampled BEV에서는 traffic light를 전혀 보지 못할 수 있다.

### 영향

- traffic-light context
- stopline ↔ traffic-light association
- `on_traffic_light_intersection`
- traffic-light stopping/stationary/accelerating behavior

### 권장 개선

Traffic light를 단순 frame-local object로만 사용하지 말고 다음을 고려한다.

- track/geometry 기반 temporal persistence
- 일정 missing gap 동안 last-known static traffic light 유지
- stopline/intersection geometry와 association 유지
- confidence decay / expiry rule

단, traffic-light **state** 정보가 OD annotation에 없는 경우 state를 임의 생성하지 않는다.

## 7. 1 FPS Visualization vs Full-frame Rule Evaluation

현재 model-facing frame input/BEV는 기본 1 FPS지만 deterministic dynamic rule은 full canonical sequence를 사용할 수 있다.

따라서:

- explorer에 안 보인 object가 rule 계산에는 존재할 수 있음
- 반대로 sampled BEV만 보고 event start/end를 판단하면 오해할 수 있음

Debug 시 source frame index와 sampling policy를 확인한다.

## 8. Object Velocity / Tracking Noise

Nearby object 및 crossing scenario는 frame 간 object association과 velocity 추정 품질에 영향을 받는다.

특히:

- track association 실패
- frame gap
- 동일 object duplicate observation
- position jitter

는 `near_high_speed_vehicle`, `crossed_by_*`, slow-lead 판단에 직접 영향을 줄 수 있다.

현재 config에는 plausible speed limit, association distance, track age, optional median filter 등이 있다.

## 9. Jerk / Derivative Noise

Trajectory의 미세한 position/velocity noise는 acceleration과 jerk에서 크게 증폭될 수 있다.

`high_magnitude_jerk`의 FP가 발생하면 threshold를 바로 올리기 전에:

1. timestamp interval
2. acceleration calculation
3. isolated spike
4. source trajectory discontinuity

를 먼저 확인한다.

## 10. Phase 4 Traffic Interaction Calibration

`traffic_interactions` configuration provenance는 `poc_requires_calibration`이다.

즉 아래 계열은 code가 존재해도 충분한 dataset validation 없이 production rule로 고정하면 안 된다.

- slow lead
- lane change with lead/trail
- stopping with/without lead
- stationary in traffic
- behind bike/long vehicle/pedestrian
- waiting for pedestrian
- barrier interaction

## 11. VLM Runtime

VLM은 rule보다 처리 비용이 훨씬 크다. candidate gating 없이 많은 frame/BEV를 전달하면 recording당 inference 시간이 크게 증가한다.

권장:

- rule/geometry candidate filtering
- candidate episode merge
- image 수 최소화
- cache 사용
- semantic ambiguity가 실제 존재하는 scenario에만 적용

## 12. VLM Evidence 부족

Prompt를 수정해도 필요한 evidence가 입력에 없으면 성능이 개선되지 않는다.

예를 들어 pedestrian interaction에는 단순 current position뿐 아니라:

- displacement
- velocity
- trajectory/history
- ego stopping/yielding state
- crosswalk relation

등이 필요할 수 있다.

문제가 발생하면 prompt보다 evidence schema를 먼저 확인한다.

## 13. Unsupported Label을 강제로 추론하지 않기

README의 중요한 contract 중 하나는 evidence가 부족한 semantic label을 unknown으로 유지하는 것이다.

GT reviewer에서도 future taxonomy label을 unsupported 상태로 보여줄 수 있다. unsupported를 false와 동일하게 처리하면 evaluation interpretation이 왜곡될 수 있다.

## 14. OD-only vs OD+LD Canonicalizer

두 canonicalizer는 아직 별도로 유지된다. 한쪽의 field/behavior를 다른 쪽에도 자동으로 동일하다고 가정하면 안 된다.

변경 시 두 mode의 regression test가 필요하다.

## 15. Repository Cleanup 관련 주의

Repository에는 active module 외에도 revised generator, PoC package, legacy helper, 과거 experiment 문서가 남아 있다.

삭제 전에 반드시 다음을 확인한다.

- README에서 참조하는지
- tests에서 import하는지
- GT/explorer가 legacy helper를 import하는지
- current pipeline이 아니라도 재현용 artifact인지

인수인계 완료 전에는 대규모 cleanup을 별도 branch에서 수행하는 것을 권장한다.
