# Evaluation

## 1. 목적

이 문서는 현재 GT 작성과 성능 평가 방법을 설명한다. 다만 **현재까지 사용한 평가 수치는 최종적으로 검증된 benchmark로 간주하지 않는다.** GT 구성, sampling alignment, evaluation unit, scenario coverage가 결과에 영향을 줄 수 있으므로 후속 개발자는 evaluation methodology 자체를 먼저 다시 확인해야 한다.

## 2. Current GT workflow

현재 GT review entry point는 다음이다.

```bash
ms-odd-gt \
  --frame-root "$MS_ODD_OUTPUT_ROOT/02_frame_inputs" \
  --gt-root "$MS_ODD_OUTPUT_ROOT/05_gt_comparison/gt" \
  --source-hz 10 \
  --sample-hz 1 \
  --host 127.0.0.1 \
  --port 8765
```

Workspace는 각 recording의 `recording_frame_tags_1fps`를 prediction reference로 사용한다. Prediction이 있는 unreviewed frame은 label이 prefill될 수 있지만 사람이 저장하기 전까지 reviewed GT로 간주하지 않는다.

Frame Input과 frame-tag exporter의 source frame index가 다를 수 있으므로 현재 workspace는 exact frame index를 먼저 사용하고, 필요한 경우 timestamp-nearest matching을 사용한다.

## 3. GT output

Recording별 GT는 다음 위치를 사용한다.

```text
outputs/05_gt_comparison/gt/<RECORDING_ID>_manual_gt.json
```

주요 정보:

```text
schema_version
recording_id
sampling_hz
gt_finished
frames[]
  ├── frame_index
  ├── timestamp
  ├── gt
  └── reviewed
```

평가 시에는 reviewed 상태와 실제 GT 작성 범위를 명확히 구분해야 한다.

## 4. Evaluation unit을 먼저 고정해야 하는 이유

Motional Scenario는 event/range 개념을 가지므로 어떤 단위로 비교하느냐에 따라 metric이 크게 달라질 수 있다.

가능한 단위:

- sampled frame-level comparison
- full-frame comparison
- event-range comparison
- recording-level presence/absence

예를 들어 같은 event라도 시작/종료 frame이 몇 frame 어긋나면 frame-level FN/FP가 많이 발생할 수 있지만, event-level 관점에서는 동일한 event를 잡은 것으로 볼 수 있다. 반대로 recording-level presence만 사용하면 event boundary가 완전히 틀려도 correct로 처리될 수 있다.

따라서 새 benchmark를 만들기 전에 **프로젝트가 실제로 평가하려는 대상이 frame state인지, event interval인지, recording-level presence인지 먼저 합의해야 한다.**

## 5. 현재 평가 방법에서 다시 확인해야 할 부분

### 5.1 GT 자체의 신뢰성

수동 GT는 reviewer 판단에 의존하므로 다음을 확인해야 한다.

- scenario definition이 reviewer에게 충분히 명확했는지
- 동일 scene을 다른 reviewer가 봐도 같은 label을 주는지
- event start/end 기준이 일관적인지
- prediction prefill이 reviewer 판단에 bias를 주지 않는지

가능하면 일부 subset에서 independent double review 또는 disagreement review를 수행해 GT consistency를 확인한다.

### 5.2 Sampling alignment

현재 Frame Input/BEV와 prediction tag가 nominally 1 FPS여도 source frame index가 정확히 같지 않을 수 있다. Timestamp-nearest fallback이 있더라도 event boundary 근처에서는 0.1~0.5초 차이가 metric에 영향을 줄 수 있다.

후속 작업에서는 frame input exporter와 frame-tag exporter가 동일한 sampling helper와 timestamp selection policy를 사용하도록 통일하는 것이 바람직하다.

### 5.3 Scenario별 imbalance

전체 TP/FP/FN만 합치면 자주 발생하는 scenario가 metric을 지배할 수 있다. 따라서 최소한 다음을 함께 기록한다.

- overall/micro metric
- scenario별 Precision / Recall / F1
- positive GT count
- FP/FN count

### 5.4 Event boundary tolerance

Event-level 평가를 사용할 경우 exact frame match만 고집할지, temporal IoU 또는 start/end tolerance를 둘지 정의해야 한다. 이 기준 없이 서로 다른 실험의 F1을 비교하면 신뢰하기 어렵다.

## 6. 기본 지표

```text
Precision = TP / (TP + FP)
Recall    = TP / (TP + FN)
F1        = 2 * Precision * Recall / (Precision + Recall)
```

이 공식 자체보다 TP/FP/FN을 어떤 evaluation unit에서 정의했는지가 더 중요하다.

## 7. 기존 발표 수치의 취급

발표 과정에서 다음 수치가 사용된 기록이 있다.

| Metric | Value |
|---|---:|
| TP | 119 |
| FP | 10 |
| FN | 58 |
| Precision | 0.9225 |
| Recall | 0.6723 |
| F1 | 0.7778 |

이 값은 현재 repository에서 동일한 recording list, GT version, scenario subset, sampling policy, evaluation unit을 고정한 reproducible benchmark artifact로 보존되어 있지 않다. 따라서 **현재 성능의 공식 baseline으로 사용하지 않는다.**

초기 소규모 평가에서 기록된 micro accuracy 0.9371, micro F1 0.8604, macro F1 0.7696 역시 taxonomy/coverage가 달랐으므로 직접 비교하지 않는다.

발표용 runtime 비교 수치 역시 hardware, cache, enabled scenarios, commit이 완전히 고정된 benchmark가 아니므로 참고 기록으로만 본다.

## 8. 권장 재평가 절차

1. evaluation 목적과 unit 합의
2. fixed recording list 선정
3. scenario subset 고정
4. GT 작성 기준 문서화
5. 일부 subset double-review로 GT consistency 확인
6. frame/timestamp sampling alignment 검증
7. prediction 생성
8. scenario별 TP/FP/FN 계산
9. overall/macro/micro metric 계산
10. event-based metric이 필요하면 temporal matching rule 별도 정의
11. FP/FN을 ODLD Explorer에서 visual review
12. commit/config/GT metadata와 결과 artifact 저장

## 9. 반드시 남길 benchmark metadata

```json
{
  "commit": "<sha>",
  "gt_version": "<version-or-date>",
  "recordings": ["..."],
  "scenarios": ["..."],
  "sampling_hz": 1.0,
  "evaluation_unit": "sampled_frame | full_frame | event",
  "event_matching_rule": "<if applicable>",
  "metrics": {
    "tp": 0,
    "fp": 0,
    "fn": 0,
    "precision": 0.0,
    "recall": 0.0,
    "f1": 0.0
  }
}
```

후속 개선의 우선순위는 새로운 metric을 만드는 것보다 **동일 조건에서 반복 가능한 evaluation contract를 먼저 고정하는 것**이다.
