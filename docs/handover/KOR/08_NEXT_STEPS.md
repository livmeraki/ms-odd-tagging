# Next Steps

## 1. 목적

이 문서는 현재 구현 상태를 기준으로 후속 개발 시 우선적으로 확인할 작업을 정리한다. 우선순위는 정확도, 재현성, 유지보수성, 확장성을 기준으로 제안한다.

## P0 — 반드시 먼저 확인

### 1. 재현 가능한 Evaluation Baseline 고정

현재 발표용 metric은 존재하지만 repository와 동일 조건으로 즉시 재현할 benchmark manifest가 부족하다.

해야 할 일:

- evaluation recording list 고정
- GT version 고정
- commit SHA / config version 저장
- scenario subset 명시
- frame/event evaluation unit 명시
- 결과 JSON artifact 저장

이 작업이 먼저 되어야 이후 threshold 변경이 실제 개선인지 판단할 수 있다.

### 2. Traffic-light Temporal Persistence

현재 가장 명확한 data issue 중 하나는 traffic-light OD의 sparse annotation과 1 FPS BEV sampling 간 mismatch이다.

해야 할 일:

- static-like traffic light track persistence
- missing-gap tolerance
- stopline/intersection association 유지
- expiry / confidence decay rule
- state 정보와 existence 정보를 분리

### 3. Lane / Intersection Regression Test

Lane continuity와 intersection에서의 lane-ID 변화는 여러 detector에 영향을 준다.

최소 regression set을 만들어 다음을 고정 검증한다.

- straight road
- lane change left/right
- intersection straight
- left/right turn intersection
- short/missing LD segment
- split/merge lane

## P1 — Accuracy / Coverage 개선

### 4. False Negative 중심 Recall 개선

대표 평가에서는 Precision보다 Recall이 낮았다.

권장 절차:

1. FN을 scenario별로 분리
2. detector가 candidate를 만들지 못한 이유 확인
3. data/evidence 부족과 threshold 문제를 구분
4. temporal boundary error 확인
5. scenario별 threshold calibration

모든 threshold를 한 번에 느슨하게 하지 않는다.

### 5. Traffic Interaction Calibration

현재 `poc_requires_calibration` 상태인 scenario를 우선 검증한다.

예:

- `following_lane_with_slow_lead`
- `stopping_with_lead`
- `stopping_without_lead`
- `stationary_in_traffic`
- `waiting_for_pedestrian_to_cross`

각 scenario에 최소 positive/negative GT set을 확보한 후 active/stable 여부를 결정한다.

### 6. Following-lane Pipeline과 Main Registry 관계 정리

현재 `following_lane`은 별도 scenario package와 main rule registry가 분리되어 있다.

해야 할 일:

- source of truth 명확화
- duplicate logic 여부 확인
- `following_lane_with_lead/without_lead` wiring 명확화
- GT reviewer support와 registry status 동기화

## P2 — Architecture 정리

### 7. Canonicalizer 차이 정리

OD-only와 OD+LD canonicalizer의 차이를 비교하여:

- 반드시 분리해야 하는 부분
- shared module로 이동 가능한 부분
- schema compatibility

를 문서화하고 test를 추가한다.

무리하게 즉시 하나로 합치기보다 behavior parity를 먼저 확인한다.

### 8. PoC / Active / Legacy 구분 강화

Repository에 다음이 공존한다.

- active pipeline
- revised experiment
- qwen VLM PoC
- Lanelet2 PoC
- legacy window helper

폴더 또는 README badge/documentation으로 상태를 명시해 잘못된 entry point 사용을 줄인다.

### 9. Config Provenance 표준화

현재 config에 `taxonomy_defined`, `engineering_default`, `provisional`, `poc_requires_calibration` 등이 존재한다.

좋은 방향이므로 scenario-level status에도 동일 provenance를 연결하고 threshold 변경 이력을 남긴다.

## P3 — VLM 개선

### 10. VLM은 Candidate Verifier 역할로 제한

VLM을 full-frame classifier로 확장하기보다 다음 구조를 유지/개선한다.

```text
Rule / Geometry Candidate
          ↓
Episode Merge
          ↓
Evidence Selection
          ↓
VLM Verification
```

### 11. Evidence Quality 개선

Semantic scenario별로 필요한 evidence를 정의한다.

예: `waiting_for_pedestrian_to_cross`

- pedestrian trajectory
- crosswalk relation
- ego deceleration/stationary history
- conflict path
- lead vehicle 여부

### 12. VLM Benchmark 고정

- model version
- prompt version
- legend mode
- image count
- candidate count
- GPU/runtime
- accuracy/F1

를 동일 manifest에 저장한다.

## P4 — 사용성

### 13. One-command Full Pipeline

현재 `run_pipeline.py`는 canonical + frame input 중심이다.

향후 필요하다면 별도 orchestration layer에서:

```text
canonical
→ rules
→ visualization
→ optional VLM
→ validation
→ GT comparison
```

을 명시적으로 실행하도록 확장할 수 있다.

단, 각 stage가 독립 실행 가능하다는 장점은 유지한다.

## Recommended Order

```text
1. Evaluation baseline 고정
2. Traffic-light persistence
3. Lane/intersection regression
4. FN 분석 및 Recall 개선
5. Traffic interaction calibration
6. Following-lane/main registry 정리
7. PoC/legacy 구조 정리
8. VLM evidence/runtime 개선
```
