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

### 5. Traffic Interaction Calibration

추가 validation이 필요한 interaction scenario는 positive/negative GT를 확보한 뒤 threshold를 재조정한다.

특히 다음 영역을 우선 확인한다.

- lead / slow lead
- stopping with/without lead
- stationary in traffic
- waiting for pedestrian to cross
- crossed-by object

## P2 — Current architecture 단순화


### 6. Frame Input / Frame Tag Sampling Contract 고정

Frame Input과 `recording_frame_tags_1fps`는 같은 nominal timestamp를 다른 source frame index로 선택할 수 있다.

현재 GT Workspace는:

```text
exact frame index
→ nearest timestamp within half sample period
```

순서로 정합한다.

후속 작업에서는 두 exporter가 동일 sampling helper를 공유하도록 만드는 것이 가장 깔끔하다. 그렇게 되면 GT Workspace의 fallback alignment도 단순화할 수 있다.

### 7. GT Workspace 초기 로딩 최적화

Recording list 생성 시 모든 frame directory와 prediction tag를 매번 다시 읽으면 큰 dataset에서 초기 로딩이 느려질 수 있다.

개선 후보:

- recording summary cache
- frame manifest 재사용
- GT metadata 단일 read
- 필요할 때만 scenario tag index 생성

Profiler 전용 entry point를 다시 만들기보다 현재 workspace 내부에서 필요 시 timing/logging을 켤 수 있게 하는 편이 좋다.

## P3 — VLM

### 8. VLM BEV Image Recognition PoC
