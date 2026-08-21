# VLM BEV Recognition PoC

## 1. 목적

이 PoC의 목적은 Motional Scenario를 VLM으로 직접 판별하기 전에, **VLM이 BEV 형태의 시각 표현에서 기본적인 spatial/semantic relation을 이해할 수 있는지**를 검증하는 것이다.

여기서 구분해야 할 용어는 다음과 같다.

- **VLM**: BEV image를 입력으로 받아 spatial/semantic 판단을 수행하는 Vision-Language Model
- **vLLM**: Linux GPU server에서 VLM inference endpoint를 제공하는 serving framework

즉, 이 실험은 "vLLM이 BEV를 이해하는가"를 보는 실험이 아니라, **vLLM으로 serving된 VLM이 BEV 형태의 visual representation을 이해할 수 있는가**를 확인하는 실험이다.

중요한 제한사항은 이 PoC에서 사용한 image가 **현재 production pipeline이 생성하는 BEV와 동일한 image가 아니라 controlled pseudo-BEV**라는 점이다. 따라서 이 결과를 그대로 production BEV 이해 성능으로 해석하면 안 된다.

이 PoC는 먼저 다음 질문에 답하기 위한 사전 검증이다.

> 단순화되고 통제된 BEV 표현에서 VLM이 ego, pedestrian, 방향, 상대 위치, path interaction 같은 기본 개념을 읽을 수 있는가?

실제 pipeline BEV에 대한 검증은 이 PoC와 별도로 수행해야 한다.

---

## 2. 현재 구현 위치

현재 BEV understanding PoC 구현은 별도 branch에 유지되어 있다.

```text
branch: poc/vlm-understanding-audit

src/ms_odd_tagging/vlm_understanding_poc/
├── cli.py
├── experiment_cli.py
├── pedestrian_experiment_cli.py
├── manifest.py
├── pseudo_bev.py
└── runner.py

examples/
├── vlm_understanding_experiment.example.json
├── vlm_understanding_poc_manifest.json
├── vlm_understanding_pedestrian_experiment.json
└── pseudo_bev_pedestrian/
```

이 코드는 main pipeline의 production VLM path와 구분되는 **understanding/validation PoC**이다.

---

## 3. 검증 대상

### 3.1 기본 BEV spatial understanding

Controlled BEV scene을 사용해 다음을 확인한다.

- target object가 ego 기준으로 `ahead / behind / left / right` 중 어디에 있는지
- target을 표시하지 않은 원본 BEV에서도 같은 관계를 이해하는지
- marked-target BEV에서 target 지정이 명확할 때 성능이 개선되는지

### 3.2 Legend ablation

각 scene을 다음 조건으로 반복한다.

```text
full_legend
no_color_legend
no_orientation_legend
no_legend
```

이를 통해 VLM이 BEV 자체의 geometry를 이해하는지, 아니면 legend의 color/orientation 설명에 크게 의존하는지를 확인한다.

### 3.3 Pedestrian understanding

별도의 balanced pseudo-BEV experiment에서는 다음 task를 분리해 평가한다.

```text
pedestrian_presence
spatial_relation
path_interaction
waiting_direct
waiting_evidence_gated
```

특히 `waiting_for_pedestrian_to_cross`와 같은 scenario를 바로 질문하는 것뿐 아니라,

```text
pedestrian exists?
→ pedestrian intersects/approaches ego path?
→ ego stopped?
→ waiting for pedestrian?
```

처럼 evidence를 단계적으로 확인하는 방식도 비교한다.

Negative scene을 포함해 pedestrian이 없을 때도 모델이 pedestrian을 있다고 판단하는 false positive가 발생하는지 확인한다.

### 3.4 Pseudo-BEV와 production pipeline BEV의 차이

이 실험에서 사용한 pseudo-BEV는 production pipeline에서 생성되는 BEV를 정확히 복제한 것이 아니라, 특정 시각 개념을 통제해서 시험하기 위한 simplified fixture이다.

현재 pseudo-BEV gallery에서 사용되는 표현은 다음과 같다.

```text
Green vehicle     = ego vehicle
Orange circle     = pedestrian
Blue rectangle    = traffic vehicle
Red stripes       = crosswalk
Blue dashed lines = lane boundaries
Image up          = ahead relative to ego
```

즉, object shape, color convention, road/lane 표현, visual density, scale, 주변 context가 실제 pipeline BEV와 다를 수 있다.

따라서 pseudo-BEV 결과가 좋다는 것은 다음 정도만 의미한다.

> 모델이 **단순화된 controlled BEV vocabulary**에서는 기본 spatial relation과 pedestrian-related concept을 읽을 가능성이 있다.

다음과 같은 결론은 이 PoC만으로 내리면 안 된다.

- production pipeline BEV를 안정적으로 이해한다
- 실제 OD/LD object visualization을 정확히 읽는다
- 실제 frame에서 작은 pedestrian/object를 안정적으로 찾는다
- production BEV 기반 Motional Scenario tagging이 신뢰 가능하다

후속 검증에서는 반드시 **실제 `outputs/02_frame_inputs/.../bev.png`를 사용한 동일한 literacy test**를 별도로 수행해야 한다.

---

## 4. Linux server에서 실행

PoC는 현재 `poc/vlm-understanding-audit` branch에 있으므로 Linux server에서 해당 branch로 전환한다.

```bash
git fetch origin
git switch poc/vlm-understanding-audit
git pull
```

vLLM server가 OpenAI-compatible endpoint로 실행 중인지 확인한다.

```bash
lsof -i :8001
```

기본 endpoint는 다음과 같다.

```text
http://127.0.0.1:8001/v1/chat/completions
```

### 4.1 Controlled BEV spatial experiment

```bash
python -m ms_odd_tagging.vlm_understanding_poc.experiment_cli \
  --experiment examples/vlm_understanding_poc_manifest.json
```

기본 model 설정은 코드 기준:

```text
Qwen/Qwen3-VL-8B-Instruct
```

특정 model 또는 endpoint를 사용할 경우:

```bash
python -m ms_odd_tagging.vlm_understanding_poc.experiment_cli \
  --experiment examples/vlm_understanding_poc_manifest.json \
  --model <MODEL_NAME> \
  --endpoint http://127.0.0.1:8001/v1/chat/completions
```

### 4.2 Pedestrian pseudo-BEV experiment

먼저 fixture가 정상인지 inference 없이 확인할 수 있다.

```bash
python -m ms_odd_tagging.vlm_understanding_poc.pedestrian_experiment_cli \
  --dry-run
```

실제 inference:

```bash
python -m ms_odd_tagging.vlm_understanding_poc.pedestrian_experiment_cli
```

---

## 5. Linux server에서 생성되는 결과 파일

이 PoC 결과는 repository의 `outputs/` 아래에 생성된다. 따라서 Linux server의 repository 위치가 예를 들어:

```text
/home/stradvision/Desktop/s_park/ms-odd-tagging
```

라면 아래 경로에서 결과를 확인한다.

### 5.1 Controlled BEV spatial experiment

기본 output directory:

```text
/home/stradvision/Desktop/s_park/ms-odd-tagging/outputs/vlm_understanding_experiment/
```

생성되는 주요 파일:

```text
outputs/vlm_understanding_experiment/
├── scene_results.csv
├── condition_summary.csv
├── confusion_matrix.csv
├── failure_analysis.csv
└── presentation_summary.md
```

보고서 작성 시 **가장 먼저 확인할 파일**은 다음이다.

```text
outputs/vlm_understanding_experiment/presentation_summary.md
```

이 파일은 task/legend condition별 Accuracy, Unknown rate, Mean confidence를 바로 복사해서 사용할 수 있는 Markdown summary로 생성된다.

세부 분석에는 다음 파일을 사용한다.

- `scene_results.csv`: scene별 expected/answer/correct/confidence/elapsed time
- `condition_summary.csv`: task + legend condition별 aggregate accuracy
- `confusion_matrix.csv`: `ahead/behind/left/right/unknown` confusion 확인
- `failure_analysis.csv`: `unknown`, response inconsistency, wrong direction/target 등 failure type 확인

### 5.2 Pedestrian pseudo-BEV experiment

기본 output directory:

```text
/home/stradvision/Desktop/s_park/ms-odd-tagging/outputs/vlm_understanding_pedestrian_experiment/
```

생성되는 파일:

```text
outputs/vlm_understanding_pedestrian_experiment/
├── pedestrian_scene_results.csv
└── pedestrian_condition_summary.csv
```

보고서에는 우선 다음 파일을 사용한다.

```text
outputs/vlm_understanding_pedestrian_experiment/pedestrian_condition_summary.csv
```

여기에는 task/legend condition별 다음 값이 포함된다.

- `n`
- `correct`
- `accuracy`
- `false_positive`
- `false_positive_rate`

`pedestrian_scene_results.csv`는 개별 scene의 expected answer, model answer, correct 여부, confidence, elapsed time을 확인할 때 사용한다.

> 위 `/home/stradvision/Desktop/s_park/ms-odd-tagging` 경로는 Linux server에서 repository를 해당 위치에 두었을 때의 예시다. 실제 clone 위치가 다르면 repository root 뒤의 `outputs/...` 상대 경로를 기준으로 찾는다.

결과 위치를 바로 확인하려면 실험 종료 후 다음 명령을 사용할 수 있다.

```bash
pwd
find outputs/vlm_understanding_experiment -maxdepth 1 -type f -print
find outputs/vlm_understanding_pedestrian_experiment -maxdepth 1 -type f -print
```

---

## 6. 보고서에서 해석할 때 주의할 점

이 PoC의 목적은 production scenario tagging 성능을 직접 증명하는 것이 아니다.

특히 현재 결과는 **pseudo-BEV fixture에 대한 결과**이므로 production pipeline BEV 결과와 분리해 기록해야 한다.

권장 해석 단계는 다음과 같다.

```text
Pseudo-BEV literacy
→ Production-BEV literacy
→ candidate recall
→ VLM decision quality
→ final scenario accuracy
```

따라서 pseudo-BEV understanding 결과가 높더라도 production BEV에서 동일한 spatial/object understanding이 재현되는지 먼저 확인해야 한다.

Production BEV 검증에서 성능이 낮다면 다음을 확인한다.

- BEV drawing convention
- ego orientation 표현
- object color/shape/size
- legend wording
- resolution
- visual clutter
- selected frame
- model capability

반대로 production BEV literacy는 높지만 scenario 성능이 낮다면 candidate generation, scenario prompt, evidence selection 또는 validation 단계가 원인일 가능성이 높다.

보고서에서는 다음과 같이 표현하는 것이 적절하다.

> Controlled pseudo-BEV를 이용한 사전 실험에서는 VLM의 기본 spatial/pedestrian understanding 가능성을 확인하였다. 다만 해당 fixture는 production pipeline BEV와 시각적 표현이 다르므로, 이 결과는 production BEV 인식 성능을 직접 의미하지 않는다. 실제 pipeline BEV를 사용한 별도 validation이 필요하다.

---

## 7. 현재까지 확인한 경향

초기 pseudo-BEV PoC에서는 legend가 없는 조건에서 ego/spatial understanding이 불안정해지는 경우가 확인되었고, pedestrian이 없는 frame에서도 pedestrian 방향을 답하는 false positive가 관찰된 적이 있다.

따라서 후속 실험에서는 단순 positive example뿐 아니라 다음을 반드시 포함해야 한다.

- no-pedestrian negative scene
- object direction이 명확히 다른 scene
- left/right/ahead/behind가 균형 잡힌 scene
- legend ablation
- direct scenario question과 evidence-gated question 비교
- 실제 production pipeline BEV

단, 이 문서에는 특정 accuracy 값을 고정해서 기록하지 않는다. 최종 수치는 Linux server에서 생성된 output artifact를 기준으로 보고한다.

---

## 8. 후속 개발자에게 필요한 작업

1. Linux server에서 pseudo-BEV PoC를 재실행해 결과 artifact를 보존한다.
2. `presentation_summary.md`와 CSV 결과를 인수인계/보고서에 포함한다.
3. model name, endpoint, commit SHA, experiment manifest를 같이 기록한다.
4. pseudo-BEV 결과를 production BEV 성능과 명확히 구분해서 보고한다.
5. **현재 pipeline의 실제 `bev.png`를 입력으로 사용하는 production-BEV literacy experiment를 추가한다.**
6. 동일 task/legend condition을 pseudo-BEV와 production BEV 양쪽에 적용해 domain gap을 비교한다.
7. negative scene을 충분히 포함해 hallucination/false-positive를 측정한다.
8. production BEV literacy가 확보된 뒤 production VLM scenario accuracy를 평가한다.
9. 필요하면 PoC를 main의 current naming/structure에 맞게 port하되, production inference code와 validation experiment code의 책임은 분리한다.
