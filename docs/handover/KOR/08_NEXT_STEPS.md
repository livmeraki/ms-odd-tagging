# Next Steps

이 문서는 **현재 cleanup branch 구조를 기준으로** 후속 개발 우선순위만 정리한다. 이미 제거한 legacy/PoC 구조를 다시 유지하는 작업은 포함하지 않는다.

## P0 — 먼저 고정할 것

### 1. 재현 가능한 Evaluation Baseline

현재 가장 먼저 필요한 것은 같은 조건에서 반복 가능한 benchmark이다.

고정할 항목:

- evaluation recording list
- GT version
- commit SHA
- `configs/direct_scenarios.yaml`
- scenario subset
- evaluation unit
- 결과 JSON artifact

이 baseline이 있어야 threshold나 algorithm 변경이 실제 개선인지 판단할 수 있다.

### 2. Lane / Intersection Regression Set

최소 다음 scene을 고정한다.

- straight road
- left/right lane change
- intersection straight
- intersection left/right turn
- short/missing LD segment
- split/merge lane

Following-lane과 lane-change 수정 시 이 set을 항상 함께 확인한다.

## P1 — Accuracy 개선

### 3. False Negative 분석

대표 평가에서는 Recall이 Precision보다 낮았다. 모든 threshold를 동시에 느슨하게 하기보다 FN을 scenario별로 분리한다.

확인 순서:

1. detector가 candidate를 만들었는가
2. 필요한 evidence가 canonical/features에 존재하는가
3. threshold 문제인가
4. temporal boundary 문제인가
5. lane/topology 오류의 downstream 영향인가

### 4. Traffic-light Temporal Persistence

현재 traffic-light OD가 sparse하게 나타나는 경우 1 FPS sampled BEV와 context가 어긋날 수 있다.

개선 후보:

- existence persistence
- missing-gap tolerance
- stopline/intersection association 유지
- confidence decay / expiry

Traffic-light state가 source annotation에 없으면 임의 state를 생성하지 않는다.

## P2 — Current architecture 단순화

### 5. Following-lane과 Main Rule Registry 관계 정리

현재 following-lane은 별도 package를 사용하면서 main rule pipeline과 연결된다.

확인할 것:

- detector source of truth
- duplicated relation calculation 여부
- `following_lane_with_lead/without_lead` wiring
- lane result가 lane-change/traffic interaction에 전달되는 경로

중복이 확인되면 하나의 implementation만 남긴다.

### 8. Frame Input / Frame Tag Sampling Contract 고정

Frame Input과 `recording_frame_tags_1fps`는 같은 nominal timestamp를 다른 source frame index로 선택할 수 있다.

현재 GT Workspace는:

```text
exact frame index
→ nearest timestamp within half sample period
```

순서로 정합한다.

후속 작업에서는 두 exporter가 동일 sampling helper를 공유하도록 만드는 것이 가장 깔끔하다. 그렇게 되면 GT Workspace의 fallback alignment도 단순화할 수 있다.


## Recommended Order

```text
1. fresh-clone + pytest 검증
2. evaluation baseline 고정
3. lane/intersection regression
4. FN 분석
5. traffic-light persistence
6. traffic interaction calibration
7. following-lane 중복 정리
8. frame sampling contract 통일
9. GT Workspace loading 최적화
10. VLM benchmark 고정
```
