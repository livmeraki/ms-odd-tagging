# Evaluation

## 1. 목적

이 문서는 자동 Motional Scenario Tagging 결과를 Ground Truth(GT)와 비교하는 방법과, 현재까지 사용된 평가 수치를 정리한다.

## 2. 현재 GT 작성 방식

현재 repository에는 frame-level GT reviewer가 있다.

실행 예:

```bash
python -m ms_odd_tagging.gt_comparison.authoring \
  --frame-input-root outputs/02_frame_inputs_revised \
  --output-root outputs/frame_gt_authoring \
  --all
```

Reviewer의 주요 특징:

- selected source frame과 정확히 대응하는 BEV 사용
- browser에서 label 작성
- recording별 `<recording>_frame_gt.json` 다운로드
- deterministic rule / lane reference를 sidecar evidence로 제공
- unsupported taxonomy label은 unknown으로 유지
- source frame 0~4는 detection 신뢰도가 낮아 scoring에서 제외하도록 표시

과거 5초 motional window 기반 GT helper는 legacy로 남아 있으나 active frame reviewer의 기본 방식은 아니다.

## 3. 평가 기본 단위

Motional Scenario는 event range를 가지므로 평가 시 다음 중 어느 단위를 사용하는지 반드시 기록한다.

- sampled frame-level label comparison
- full-frame label comparison
- event-level range matching
- recording-level presence/absence

서로 다른 평가 단위의 metric을 직접 비교하면 안 된다.

## 4. 기본 지표

- TP: GT와 prediction이 모두 positive
- FP: prediction만 positive
- FN: GT만 positive

```text
Precision = TP / (TP + FP)
Recall    = TP / (TP + FN)
F1        = 2 * Precision * Recall / (Precision + Recall)
```

## 5. 정량 결과

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
4. scenario subset 명시
5. small-set regression test
6. TP/FP/FN 계산
7. FP/FN case explorer로 visual review
8. threshold 수정
9. 같은 GT에서 재실행
10. 결과 artifact 저장

## 10. 앞으로 반드시 추가할 것

재현 가능한 benchmark manifest를 추가하는 것을 권장한다.

예:

```json
{
  "commit": "<sha>",
  "config_version": "...",
  "gt_version": "...",
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
