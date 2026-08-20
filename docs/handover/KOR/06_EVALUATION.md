# Evaluation

## 1. Current GT workflow

현재 GT 작성 entry point는 Simplified Taxonomy GT Workspace 하나이다.

```bash
ms-odd-gt-workspace \
  --frame-root "$MS_ODD_OUTPUT_ROOT/02_frame_inputs" \
  --gt-root "$MS_ODD_OUTPUT_ROOT/06_gt_comparison/gt" \
  --source-hz 10 \
  --sample-hz 1 \
  --host 127.0.0.1 \
  --port 8765
```

Workspace는 각 recording의 현재 `recording_frame_tags_1fps`를 prediction reference로 사용한다. Frame Input과 frame-tag exporter의 source frame index가 다를 수 있으므로 exact frame index를 먼저 사용하고, 없으면 timestamp nearest match를 사용한다.

Prediction이 있는 unreviewed frame은 simplified taxonomy 값으로 prefill되지만 사람이 저장하기 전까지 reviewed GT로 간주하지 않는다.

## 2. GT output

Recording별 GT는 다음 위치에 저장된다.

```text
outputs/06_gt_comparison/gt/<RECORDING_ID>_manual_gt.json
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

평가에는 `reviewed=true`인 frame만 사용한다.

## 3. 평가 단위

Metric을 기록할 때 평가 단위를 반드시 함께 명시한다.

- sampled frame-level comparison
- full-frame comparison
- event-range comparison
- recording-level presence/absence

서로 다른 평가 단위의 수치는 직접 비교하지 않는다.

## 4. 기본 지표

```text
Precision = TP / (TP + FP)
Recall    = TP / (TP + FN)
F1        = 2 * Precision * Recall / (Precision + Recall)
```

## 5. 프로젝트 발표에 사용된 대표 결과

| Metric | Value |
|---|---:|
| TP | 119 |
| FP | 10 |
| FN | 58 |
| Precision | 0.9225 |
| Recall | 0.6723 |
| F1 | 0.7778 |

이 값은 발표 과정에서 사용된 기록이며, 현재 cleanup branch에서 동일한 GT/recording/config 조합으로 즉시 재현되는 benchmark artifact는 아직 고정되어 있지 않다. 따라서 새 성능 결과의 기준값으로 사용할 때는 recording list, GT version, scenario subset, commit SHA를 함께 고정해야 한다.

초기 소규모 평가에서 기록된 micro accuracy 0.9371, micro F1 0.8604, macro F1 0.7696 역시 taxonomy와 coverage가 달랐으므로 위 결과와 직접 비교하지 않는다.

## 6. Runtime 기록

발표용 비교에서는 다음 값이 사용된 적이 있다.

- 수동: 1분 데이터에서 약 5개 scenario 확인에 약 3분
- 자동: 1분 데이터에서 약 20개 scenario 판별에 약 23초

이 역시 hardware, cache, enabled scenarios, commit이 완전히 고정된 benchmark는 아니므로 재측정 시 조건을 반드시 함께 저장한다.

## 7. 권장 평가 절차

1. evaluation recording list 고정
2. GT version 고정
3. commit SHA와 config 기록
4. scenario subset 기록
5. evaluation unit 기록
6. prediction 생성
7. reviewed GT와 비교
8. TP/FP/FN 및 Precision/Recall/F1 계산
9. FP/FN을 ODLD Explorer에서 visual review
10. 결과 JSON을 artifact로 보존

## 8. 반드시 남길 benchmark metadata

```json
{
  "commit": "<sha>",
  "gt_version": "<version-or-date>",
  "recordings": ["..."],
  "scenarios": ["..."],
  "evaluation_unit": "sampled_frame",
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

현재 repository에 새로운 evaluation path를 추가할 경우 이 metadata를 재현 가능하게 남기는 것을 우선한다.
