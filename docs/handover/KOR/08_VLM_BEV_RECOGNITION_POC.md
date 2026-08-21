# VLM BEV Recognition PoC

## 1. 목적

이 PoC는 **VLM이 BEV 형태의 시각 표현에서 기본적인 spatial/pedestrian relation을 읽을 수 있는지** 확인하기 위한 실험이다.

- VLM: BEV image를 해석하는 Vision-Language Model
- vLLM: Linux GPU server에서 VLM endpoint를 제공하는 serving framework

> 현재 PoC는 production pipeline의 `bev.png`가 아니라 **controlled pseudo-BEV**를 사용한다. 따라서 이 결과는 production BEV 인식 성능을 직접 의미하지 않는다.

---

## 2. 사용한 pseudo-BEV

Pseudo-BEV는 실제 pipeline BEV보다 단순화되어 있으며, 다음 표현을 사용한다.

```text
Green vehicle     = ego vehicle
Orange circle     = pedestrian
Blue rectangle    = traffic vehicle
Red stripes       = crosswalk
Blue dashed lines = lane boundaries
Image up          = ahead relative to ego
```

대표 예시:

### Pedestrian crossing ahead

![positive crossing ahead](https://raw.githubusercontent.com/livmeraki/ms-odd-tagging/poc/vlm-understanding-audit/examples/pseudo_bev_pedestrian/positive_crossing_ahead.png)

### Pedestrian on sidewalk only

![negative sidewalk only](https://raw.githubusercontent.com/livmeraki/ms-odd-tagging/poc/vlm-understanding-audit/examples/pseudo_bev_pedestrian/negative_sidewalk_only.png)

### No pedestrian

![negative no pedestrian](https://raw.githubusercontent.com/livmeraki/ms-odd-tagging/poc/vlm-understanding-audit/examples/pseudo_bev_pedestrian/negative_no_pedestrian.png)

### Ego stopped behind lead vehicle

![negative stopped for lead](https://raw.githubusercontent.com/livmeraki/ms-odd-tagging/poc/vlm-understanding-audit/examples/pseudo_bev_pedestrian/negative_stopped_for_lead.png)

전체 pseudo-BEV fixture는 다음 branch에 있다.

```text
branch: poc/vlm-understanding-audit
examples/pseudo_bev_pedestrian/
```

---

## 3. 실험 내용

두 가지 실험을 사용한다.

### Spatial / legend ablation

VLM이 object의 상대 방향을 이해하는지 확인한다.

```text
ahead / behind / left / right / unknown
```

각 scene은 다음 legend 조건으로 반복한다.

```text
full_legend
no_color_legend
no_orientation_legend
no_legend
```

### Pedestrian understanding

다음 항목을 각각 질문한다.

```text
pedestrian_presence
spatial_relation
path_interaction
waiting_direct
waiting_evidence_gated
```

`waiting_evidence_gated`는 바로 scenario를 묻지 않고 다음 evidence를 순서대로 확인하도록 한다.

```text
pedestrian exists?
→ intersects / approaches ego path?
→ ego stopped?
→ waiting for pedestrian?
```

---

## 4. 현재까지 확인한 결과

초기 PoC에서 확인된 핵심 경향은 다음과 같다.

- legend가 충분히 제공된 경우 ego/object의 기본 spatial relation을 해석할 수 있었다.
- legend가 제거되면 spatial understanding이 불안정해지는 경우가 있었다.
- pedestrian이 없는 negative frame에서도 pedestrian 방향을 답하는 false positive가 관찰되었다.
- 따라서 scenario를 직접 질문하는 것보다 **object presence → spatial/path relation → scenario** 순서로 evidence를 확인하는 방식이 필요하다.

이 결과는 pseudo-BEV에 대한 exploratory result이며, production pipeline BEV에 대한 성능으로 해석하면 안 된다.

정량 결과는 Linux server에서 생성된 output artifact를 사용한다.

```text
outputs/vlm_understanding_experiment/presentation_summary.md
outputs/vlm_understanding_experiment/condition_summary.csv
outputs/vlm_understanding_experiment/failure_analysis.csv

outputs/vlm_understanding_pedestrian_experiment/pedestrian_condition_summary.csv
outputs/vlm_understanding_pedestrian_experiment/pedestrian_scene_results.csv
```

보고서에는 위 파일에서 실제 실행 결과를 확인한 뒤 accuracy / false-positive rate를 기록한다.

---

## 5. 다시 실행하는 방법

PoC 구현은 다음 branch에 있다.

```bash
git fetch origin
git switch poc/vlm-understanding-audit
git pull
```

주요 코드:

```text
src/ms_odd_tagging/vlm_understanding_poc/
├── experiment_cli.py
├── pedestrian_experiment_cli.py
├── pseudo_bev.py
└── runner.py
```

vLLM endpoint 확인:

```bash
lsof -i :8001
```

기본 endpoint:

```text
http://127.0.0.1:8001/v1/chat/completions
```

### Spatial / legend experiment

```bash
python -m ms_odd_tagging.vlm_understanding_poc.experiment_cli \
  --experiment examples/vlm_understanding_poc_manifest.json
```

### Pedestrian experiment

먼저 fixture 확인:

```bash
python -m ms_odd_tagging.vlm_understanding_poc.pedestrian_experiment_cli \
  --dry-run
```

실제 inference:

```bash
python -m ms_odd_tagging.vlm_understanding_poc.pedestrian_experiment_cli
```

---

## 6. Linux server 결과 위치

실험 종료 후 repository root에서 확인한다.

```bash
find outputs/vlm_understanding_experiment -maxdepth 1 -type f -print
find outputs/vlm_understanding_pedestrian_experiment -maxdepth 1 -type f -print
```

예를 들어 repository가 다음 위치에 있다면:

```text
/home/stradvision/Desktop/s_park/ms-odd-tagging
```

주요 결과는 다음과 같다.

```text
/home/stradvision/Desktop/s_park/ms-odd-tagging/outputs/vlm_understanding_experiment/presentation_summary.md
/home/stradvision/Desktop/s_park/ms-odd-tagging/outputs/vlm_understanding_pedestrian_experiment/pedestrian_condition_summary.csv
```

---

## 7. 후속 구현 시 필요한 것

다음 단계는 pseudo-BEV 실험을 더 복잡하게 만드는 것이 아니라, **현재 pipeline이 생성하는 실제 BEV에 동일한 validation을 적용하는 것**이다.

```text
outputs/02_frame_inputs/<RECORDING_ID>/frame_XXXXXX/bev.png
```

최소 다음을 다시 검증해야 한다.

1. ego 식별
2. pedestrian / vehicle 존재 여부
3. ahead / behind / left / right
4. ego path와 object의 relation
5. no-object negative case의 false positive
6. legend 의존도

Pseudo-BEV와 production BEV에서 같은 task를 실행해 성능 차이를 비교하면 VLM이 실제 pipeline visualization을 얼마나 이해하는지 확인할 수 있다.
