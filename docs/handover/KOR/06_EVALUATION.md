# Evaluation

## 1. 목적

이 문서는 자동 Motional Scenario Tagging 결과를 Ground Truth(GT)와 비교하는 방법과, 현재까지 사용된 평가 수치를 정리한다.

## 2. 현재 GT 작성 방식

현재 기본 GT 작성 도구는 다음 module이다.

```text
ms_odd_tagging.simplified_taxonomy.gt_workspace_profiled
```

`run_pipeline.py`를 기본 option으로 실행하면 Canonicalization과 Frame Input / BEV generation이 완료된 뒤 이 GT Workspace가 자동으로 실행된다.

직접 실행:

```powershell
python -m ms_odd_tagging.simplified_taxonomy.gt_workspace_profiled `
  --frame-root (Join-Path $env:MS_ODD_OUTPUT_ROOT "02_frame_inputs") `
  --gt-root (Join-Path $env:MS_ODD_OUTPUT_ROOT "06_gt_comparison/gt") `
  --source-hz 10 `
  --sample-hz 1 `
  --host 127.0.0.1 `
  --port 8765
```

browser:

```text
http://127.0.0.1:8765
```

### Prediction source

Prediction은 별도 exported simplified prediction JSON을 기본 source로 사용하지 않는다.

현재 source:

```text
outputs/02_frame_inputs/<recording>/recording_frame_tags_1fps/
```

각 frame의 active Motional Scenario를 simplified taxonomy로 mapping해 Prediction으로 보여 준다.

### Frame alignment

Frame Input과 frame-tag exporter가 서로 다른 1 FPS sampling policy를 사용할 수 있으므로 prediction matching은 다음 순서로 수행한다.

1. exact frame index
2. exact match가 없으면 nearest timestamp
3. 1 FPS sample period의 절반 이내인 경우만 accept

따라서 evaluation/debug 시 BEV frame과 prediction source frame이 같은 시점을 나타내는지 확인해야 한다.

### Prediction prefill과 reviewed GT

- unreviewed frame은 current prediction으로 GT control을 prefill
- prefill 상태는 `UNREVIEWED`
- 사용자가 `Save` 또는 `Save + Next`를 수행해야 reviewed GT가 됨
- 기존 reviewed GT는 prediction으로 덮어쓰지 않음

### Autosave

```text
outputs/06_gt_comparison/gt/<recording>_manual_gt.json
```

GT Workspace process는 annotation 중 계속 실행해 두고, 종료할 때 `Ctrl+C`를 사용한다.

과거 `ms_odd_tagging.gt_comparison.authoring` standalone reviewer와 Full ODLD Explorer에 GT authoring panel을 주입하는 tool은 historical/debug 용도로 남아 있으나 현재 default GT workflow는 아니다.

## 3. 평가 기본 단위

Motional Scenario는 event range를 가지므로 평가 시 다음 중 어느 단위를 사용하는지 반드시 기록한다.

- sampled frame-level label comparison
- full-frame label comparison
- event-level range matching
- recording-level presence/absence

서로 다른 평가 단위의 metric을 직접 비교하면 안 된다.

현재 Simplified Taxonomy GT Workspace는 기본적으로 1 FPS sampled frame review workflow이다.

## 4. 기본 지표

- TP: GT와 prediction이 모두 positive
- FP: prediction만 positive
- FN: GT만 positive

```text
Precision = TP / (TP + FP)
Recall    = TP / (TP + FN)
F1        = 2 * Precision * Recall / (Precision + Recall)
```

## 5. 발표에서 사용한 대표 정량 결과

프로젝트 발표 준비 과정에서 사용한 대표 집계 값:

| Metric | Value |
|---|---:|
| TP | 119 |
| FP | 10 |
| FN | 58 |
| Precision | 0.9225 |
| Recall | 0.6723 |
| F1 | **0.7778** |

해석:

- Precision은 비교적 높아 prediction이 발생한 경우의 신뢰도는 높은 편이었다.
- Recall이 Precision보다 낮아 놓치는 scenario(FN)를 줄이는 것이 주요 개선 방향이었다.

> **검증 상태:** 위 수치는 프로젝트 발표에 사용된 대표 결과이다. 현재 repository에서 동일 evaluation fixture와 결과 artifact가 직접 추적되지 않으므로, 재현 가능한 최종 benchmark로 사용하려면 평가 대상 recording, GT version, scenario subset, commit SHA를 다시 연결해 기록해야 한다.

## 6. 과거 평가 기록

초기 dynamic GT 소규모 평가에서는 다음 수치가 기록된 적이 있다.

- micro accuracy: 0.9371
- micro F1: 0.8604
- macro F1: 0.7696

이 수치는 이후 taxonomy와 detector coverage가 확장되기 전 단계의 결과이므로 최종 F1 0.7778과 직접 비교하지 않는다.

## 7. 수동 대비 처리 시간

발표용 측정에서 사용한 비교:

- 수동: 1분 데이터에서 약 5개 scenario를 확인하는 데 약 3분
- 자동: 1분 데이터에서 약 20개 scenario를 판별하는 데 약 23초

이 수치는 자동화의 throughput 이점을 설명하기 위한 대표 측정값이다.

> **검증 상태:** 23초의 정확한 hardware, commit, enabled scenario set, cache 상태를 repository artifact에서 다시 확인할 수 있도록 benchmark script 또는 profiling 결과를 보존하는 것이 필요하다.

## 8. VLM Runtime 참고

VLM을 broad candidate set에 적용한 실험에서는 rule-based pipeline보다 훨씬 큰 inference 비용이 발생했다. 따라서 평가 시 accuracy뿐 아니라 아래를 함께 기록해야 한다.

- candidate count
- images per candidate/episode
- model name
- GPU
- average seconds / recording
- cache 사용 여부

VLM을 전체 frame에 직접 적용하는 것보다 rule gating 후 제한적으로 사용하는 설계가 필요한 이유이다.

## 9. 권장 평가 절차

새 detector 또는 threshold를 변경할 때:

1. commit SHA 기록
2. config version 기록
3. GT version 고정
4. prediction source가 current `recording_frame_tags_1fps`인지 확인
5. GT Workspace에서 frame/timestamp alignment 확인
6. scenario subset 명시
7. small-set regression test
8. TP/FP/FN 계산
9. FP/FN case visual review
10. threshold 수정 후 같은 GT에서 재실행
11. 결과 artifact 저장

## 10. 앞으로 반드시 추가할 것

재현 가능한 benchmark manifest를 추가하는 것을 권장한다.

예:

```json
{
  "commit": "<sha>",
  "config_version": "...",
  "gt_version": "...",
  "prediction_source": "recording_frame_tags_1fps",
  "sampling_hz": 1.0,
  "recordings": ["..."],
  "scenarios": ["..."],
  "evaluation_unit": "frame",
  "metrics": {
    "tp": 119,
    "fp": 10,
    "fn": 58
  }
}
```

이렇게 해야 발표용 숫자와 현재 code 상태가 분리되는 문제를 방지할 수 있다.
