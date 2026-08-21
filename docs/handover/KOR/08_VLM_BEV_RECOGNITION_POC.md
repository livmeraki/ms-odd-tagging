# VLM BEV Recognition PoC

## 1. 목적

이 PoC는 Motional Scenario를 VLM으로 직접 판별하기 전에, **VLM이 BEV 형태의 시각 표현에서 기본적인 spatial relation을 이해할 수 있는지** 확인하기 위한 사전 실험이다.

이 실험에 사용한 이미지는 현재 production pipeline의 `bev.png`와 동일하지 않은 **controlled pseudo-BEV**이다. 따라서 아래 결과는 production BEV 성능을 직접 의미하지 않는다.

---

## 2. 사용한 pseudo-BEV

Pseudo-BEV는 다음처럼 단순화된 표현을 사용한다.

```text
Green vehicle     = ego vehicle
Orange circle     = pedestrian
Blue rectangle    = traffic vehicle
Red stripes       = crosswalk
Blue dashed lines = lane boundaries
Image up          = ahead relative to ego
```

대표 fixture:

<p align="center">
  <img src="https://raw.githubusercontent.com/livmeraki/ms-odd-tagging/poc/vlm-understanding-audit/examples/pseudo_bev_pedestrian/positive_crossing_ahead.png" alt="Pedestrian crossing ahead" width="420">
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/livmeraki/ms-odd-tagging/poc/vlm-understanding-audit/examples/pseudo_bev_pedestrian/positive_multiple_one_crossing.png" alt="Multiple pedestrians, one crossing" width="420">
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/livmeraki/ms-odd-tagging/poc/vlm-understanding-audit/examples/pseudo_bev_pedestrian/negative_no_pedestrian.png" alt="No pedestrian" width="420">
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/livmeraki/ms-odd-tagging/poc/vlm-understanding-audit/examples/pseudo_bev_pedestrian/negative_stopped_for_lead.png" alt="Stopped behind lead vehicle" width="420">
</p>

> 위 fixture image는 `main`이 아니라 `poc/vlm-understanding-audit` branch에 있다. 따라서 이 문서에서는 해당 branch의 raw image를 직접 참조한다.

---

## 3. 실험 결과

제공된 결과는 **8개 scene × 4개 legend condition = 32 runs**의 `spatial_relation` task에 대한 결과이다.

| Condition | N | Correct | Accuracy | False Positive Rate |
|---|---:|---:|---:|---:|
| `full_legend` | 8 | 8 | 1.000 | 0.000 |
| `no_color_legend` | 8 | 8 | 1.000 | 0.000 |
| `no_legend` | 8 | 8 | 1.000 | 0.000 |
| `no_orientation_legend` | 8 | 7 | 0.875 | 0.000 |

32회 중 31회가 정답으로, 전체 accuracy는 **96.875%**였다.

오답은 1건이었다.

```text
scene:      positive_multiple_one_crossing
condition:  no_orientation_legend
expected:   ahead
answer:     left
```

이 scene은 여러 pedestrian이 있는 distractor case였으며, orientation information을 제거했을 때 target spatial relation을 잘못 판단했다.

반면 이번 결과에서는 `no_legend` 조건도 8/8 정답이었다. 따라서 **이 결과만으로 legend가 반드시 필요하다고 결론내릴 수는 없다.** 현재 확인된 failure는 `no_orientation_legend`의 multi-pedestrian distractor scene 한 건이다.

또한 제공된 CSV는 `spatial_relation` task만 포함한다. 따라서 pedestrian presence, path interaction, `waiting_for_pedestrian_to_cross` 정확도는 이 결과에서 보고하지 않는다.

---

## 4. 결과 파일

Linux server에서 pedestrian experiment를 실행하면 기본적으로 다음 결과가 생성된다.

```text
outputs/vlm_understanding_pedestrian_experiment/
├── pedestrian_scene_results.csv
└── pedestrian_condition_summary.csv
```

보고서용 요약은 다음 파일을 먼저 확인한다.

```text
outputs/vlm_understanding_pedestrian_experiment/pedestrian_condition_summary.csv
```

개별 failure를 확인할 때는:

```text
outputs/vlm_understanding_pedestrian_experiment/pedestrian_scene_results.csv
```

를 사용한다.

---

## 5. 다시 실행하는 방법

PoC 구현은 다음 branch에 있다.

```text
poc/vlm-understanding-audit
```

Linux server에서:

```bash
git fetch origin
git switch poc/vlm-understanding-audit
git pull
```

vLLM endpoint 확인:

```bash
lsof -i :8001
```

실행:

```bash
python -m ms_odd_tagging.vlm_understanding_poc.pedestrian_experiment_cli
```

관련 파일:

```text
src/ms_odd_tagging/vlm_understanding_poc/pedestrian_experiment_cli.py
src/ms_odd_tagging/vlm_understanding_poc/runner.py
examples/vlm_understanding_pedestrian_experiment.json
examples/pseudo_bev_pedestrian/
```

---

## 6. 다음에 필요한 검증

이 PoC는 pseudo-BEV에서 spatial relation을 읽을 수 있는 가능성을 확인한 것이다. 다음 단계에서는 같은 종류의 test를 실제 pipeline BEV에 적용해야 한다.

실제 입력 예:

```text
outputs/02_frame_inputs/<RECORDING_ID>/frame_XXXXXX/bev.png
```

권장 순서:

```text
Pseudo-BEV spatial test
→ Production BEV spatial test
→ pedestrian presence / path interaction test
→ candidate recall
→ final VLM scenario accuracy
```

Production BEV에서도 동일한 성능이 재현되는지 확인한 뒤에만 VLM 기반 Motional Scenario tagging 성능으로 해석한다.
