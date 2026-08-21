# 개발자 인수인계 가이드

이 문서는 Motional Scenario ODD Tagging 프로젝트를 인수받아 **직접 실행하고, 문제를 분석하고, 이후 기능을 고도화할 개발자**를 위한 실무 중심 문서입니다. 프로젝트가 무엇을 하는지, 어떤 파일을 먼저 봐야 하는지, 각 툴을 언제 사용해야 하는지, 새로운 기능을 추가할 때 어디를 수정해야 하는지를 빠르게 이해하는 것을 목표로 합니다.

영문 버전은 다음 문서를 참고합니다.

```text
docs/handover/ENG/DEVELOPER_HANDOVER.md
```

세부 설계와 배경은 `docs/handover/KOR/` 아래의 00~09 문서를 기준으로 확인합니다.

---

## 1. 프로젝트가 하는 일

이 프로젝트는 다음 세 가지 입력을 이용해 자율주행 데이터의 Motional Scenario를 자동으로 tagging합니다.

```text
annotations_OD.json
annotations_LD.json
traj_lcs.txt
```

- **OD Annotation**: 주변 객체의 위치, 종류, 크기 등 object detection 정보
- **LD Annotation**: lane, road boundary, crosswalk, stopline 등 도로 구조 정보
- **Ego Trajectory**: ego vehicle의 위치, heading, 속도 등 시간에 따른 ego motion 정보

Motional Scenario는 단일 frame만 보고 판단하기 어려운 경우가 많습니다. 예를 들어 `changing_lane`, `starting_left_turn`, `waiting_for_pedestrian_to_cross`는 여러 frame에 걸친 변화와 주변 객체와의 관계를 함께 봐야 합니다.

따라서 현재 시스템은 다음을 결합합니다.

- geometry
- ego motion
- object relation
- lane/topology relation
- temporal filtering / hysteresis
- event segmentation
- 필요한 경우에만 VLM reasoning

전체 흐름은 다음과 같습니다.

```text
Raw Recording
    │
    ▼
Canonicalization
    │
    ▼
outputs/01_canonical
    │
    ├────────────── Rule / Geometry / Temporal analysis
    │
    └────────────── Frame / BEV generation
                         │
                         ▼
                  outputs/02_frame_inputs
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
        Rule scenario tags      VLM candidates
                                      │
                                      ▼
                               VLM inference
                                      │
                                      ▼
                               validation / merge
              └──────────┬───────────┘
                         ▼
               Motional Scenario tags
                         │
                         ▼
                    GT Workspace
```

기본 원칙은 **명시적인 geometry/data로 판단할 수 있는 것은 deterministic rule로 처리하고, semantic 판단이 필요한 일부 경우에만 VLM을 사용한다**는 것입니다.

---

## 2. 처음 인수받았을 때 읽을 순서

다음 순서로 읽는 것을 권장합니다.

```text
1. README.md
2. docs/handover/KOR/00_OVERVIEW.md
3. docs/handover/KOR/01_SETUP_AND_RUN.md
4. docs/handover/KOR/02_PIPELINE.md
5. docs/handover/KOR/04_SCENARIO_STATUS.md
6. docs/handover/KOR/07_KNOWN_ISSUES.md
7. docs/handover/KOR/08_NEXT_STEPS.md
```

새 detector를 만들거나 기존 detector를 수정할 경우에는 추가로 다음 문서를 봅니다.

```text
03_DATA_FORMAT.md
05_ALGORITHMS.md
06_EVALUATION.md
09_REFERENCES.md
```

---

## 3. Repository 구조

중요한 구조만 보면 다음과 같습니다.

```text
configs/
    direct_scenarios.yaml
    following_lane.json
    ld_topology.json
    scenario_catalog.csv

data/
    README.md

docs/handover/
    ENG/DEVELOPER_HANDOVER.md
    KOREAN.md
    KOR/
        00_OVERVIEW.md
        01_SETUP_AND_RUN.md
        01A_SETUP_AND_RUN_LINUX.md
        01B_SETUP_AND_RUN_WINDOWS.md
        02_PIPELINE.md
        03_DATA_FORMAT.md
        04_SCENARIO_STATUS.md
        05_ALGORITHMS.md
        06_EVALUATION.md
        07_KNOWN_ISSUES.md
        08_NEXT_STEPS.md
        09_REFERENCES.md

scripts/odld_explorer/
    generate.py
    explorer.py
    odld_explorer_common.py

src/ms_odd_tagging/
    canonical/
    common/
    evaluation/
    features/
    frame_inputs/
    geometry/
    gt/
    ld_topology/
    scenarios/
    tagger/
    validator/
    vlm/
    pipeline.py

tests/
```

유지보수에서 가장 중요한 원칙은 **하나의 기능에 대해 다시 여러 버전의 구현을 만들지 않는 것**입니다. 현재 구조는 가능한 한 feature별로 하나의 현재 구현만 남기는 방향으로 정리되어 있습니다.

---

## 4. 가장 중요한 설정 파일

### `configs/scenario_catalog.csv`

Scenario 지원 상태의 source of truth입니다.

여기서 확인할 수 있는 내용:

- scenario 이름
- category
- 현재 처리 방식: `rule`, `vlm`, 또는 blank
- 상태: `active`, `experimental`, `unsupported`

새 scenario를 추가하거나 처리 방식을 변경하려면 가장 먼저 이 파일을 확인합니다.

### `configs/direct_scenarios.yaml`

Deterministic rule detector의 runtime 설정입니다.

주요 항목:

- threshold
- minimum duration
- hysteresis
- merge / inactive gap
- enabled scenario
- scenario별 detector parameter

정리하면:

```text
scenario_catalog.csv   = 어떤 scenario가 있고 누가 처리하는가
 direct_scenarios.yaml = rule detector가 어떤 조건으로 동작하는가
```

### `configs/following_lane.json`

Following-lane과 lane relation 관련 설정입니다.

다음 문제를 볼 때 우선 확인합니다.

- ego lane assignment
- left/right adjacent lane
- lane continuity
- lead/trail relation
- following-lane scenario

### `configs/ld_topology.json`

LD topology와 intersection geometry 관련 설정입니다.

이 영역을 수정하면 lane change, turn, following lane, intersection VLM candidate 등에 연쇄적으로 영향을 줄 수 있습니다.

---

## 5. 핵심 구현 파일과 역할

### A. Canonicalization

```text
src/ms_odd_tagging/canonical/
```

역할:

- OD + LD + Ego Trajectory 통합
- source frame alignment 유지
- ego motion field 구성
- recording-level LD geometry normalization
- `ld_feature_store` 구성
- frame별 nearby LD reference 제공

Canonical schema:

```text
odld-trajectory-canonical-frame-v1
```

후속 detector는 가능하면 raw OD/LD 파일을 직접 다시 읽지 말고 canonical data를 사용해야 합니다.

새 기능에 여러 detector가 함께 사용할 정보가 필요하다면 detector 내부에 중복 구현하기보다 canonical 또는 feature layer에 넣는 것이 좋습니다.

### B. Feature Extraction

```text
src/ms_odd_tagging/features/
```

주요 파일:

```text
ego_motion.py
object_relations.py
road_feature_relations.py
pedestrian_crosswalk_relations.py
object_path_crossing_relations.py
traffic_relations.py
traffic_light_context.py
```

이곳은 detector들이 공통으로 사용하는 evidence/relation을 생성합니다.

새 detector를 만들 때 먼저 기존 feature가 필요한 정보를 이미 제공하는지 확인해야 합니다.

### C. Rule Tagging

```text
src/ms_odd_tagging/tagger/rule_based/
```

일반적인 구조:

```text
Canonical frames
    ↓
Feature / Relation
    ↓
Frame-level State
    ↓
Temporal Filtering / Hysteresis
    ↓
Event Segmentation
    ↓
ScenarioEvent(start, end, evidence)
```

주요 영역:

- speed / dynamics / jerk
- turn
- lane change
- crosswalk behavior
- object interaction
- pedestrian-crosswalk interaction
- object path crossing
- traffic interaction

Motional Scenario는 단순한 한 frame threshold 문제가 아니라 temporal boundary, lane continuity, evidence 품질 문제인 경우가 많습니다.

### D. Following Lane

```text
src/ms_odd_tagging/scenarios/following_lane/
```

Lane assignment와 following-lane relation을 처리합니다.

특히 다음 두 개념을 분리해서 이해해야 합니다.

- **physical lane assignment**: 현재 ego가 어떤 실제 lane geometry에 속하는가
- **logical continuity**: 여러 LD segment가 실제 주행 경로상 같은 lane으로 이어지는가

Lane change나 traffic interaction을 수정하기 전에 이 subsystem을 먼저 이해하는 것이 좋습니다.

### E. LD Topology

```text
src/ms_odd_tagging/ld_topology/
```

Intersection/topology 이해와 lane context를 지원합니다.

이 영역은 다음에 영향을 줄 수 있습니다.

- intersection lane-change suppression
- turn detection
- following lane
- VLM candidate generation

따라서 독립적인 visualization 기능이 아니라 shared infrastructure로 취급해야 합니다.

### F. Frame Input / BEV

```text
src/ms_odd_tagging/frame_inputs/
```

기본 출력은 1 FPS입니다.

```text
outputs/02_frame_inputs/<RECORDING_ID>/
    frame_XXXXXX/
        frame.json
        bev.png
    recording_frame_tags_1fps/
```

Frame Input은 다음에서 공통으로 사용됩니다.

- GT review
- debugging
- VLM evidence

중요한 점은 Rule detector는 full canonical sequence를 사용할 수 있지만 BEV는 sampled frame이라는 것입니다. 결과가 어긋나 보이면 frame index와 timestamp를 같이 확인해야 합니다.

### G. VLM

```text
src/ms_odd_tagging/vlm/
```

VLM은 전체 frame classifier가 아니라 hybrid verifier 역할을 합니다.

```text
Rule / Geometry Candidate
    ↓
Candidate / Episode Merge
    ↓
Evidence / BEV Selection
    ↓
VLM Inference
    ↓
Validation
    ↓
Event Merge
```

VLM을 고도화할 때는 prompt부터 고치기보다 candidate recall을 먼저 확인하는 것이 중요합니다.

### H. GT Workspace

```text
src/ms_odd_tagging/gt/
```

사람이 prediction을 확인하고 GT를 저장하는 도구입니다.

주요 용도:

- sampled frame의 BEV 확인
- prediction tag 확인
- 잘못된 label 수정
- reviewed GT 저장

Prediction은 unreviewed frame을 prefill할 수 있지만 최종 GT는 사람의 review 결과여야 합니다.

### I. ODLD Explorer

```text
scripts/odld_explorer/
```

실행:

```text
python scripts/odld_explorer/generate.py
```

Full recording의 문제를 분석할 때 사용합니다.

확인 가능한 영역:

- OD object
- LD geometry
- ego trajectory
- scenario interval
- lane relation
- topology
- road/object relation evidence

사용 기준:

```text
GT Workspace  = sampled frame의 label 검토
ODLD Explorer = recording 전체의 원인 분석
```

---

## 6. 어떤 툴을 언제 사용할지

| 목적 | 사용 툴 | 핵심 파일/명령 |
|---|---|---|
| 전체 pipeline 실행 | Main Pipeline | `ms-odd-tagging` |
| canonical만 생성/확인 | Canonical CLI | `ms-odd-canonical` |
| frame.json / BEV 생성 | Frame CLI | `ms-odd-frames` |
| deterministic tag 확인 | Rule CLI | `ms-odd-rules` |
| lane relation 분석 | Lane CLI | `ms-odd-lane` |
| intersection/topology 분석 | Topology CLI | `ms-odd-topology` |
| VLM candidate/inference | VLM CLI | `ms-odd-vlm` |
| 사람이 GT review | GT Workspace | `ms-odd-gt` |
| frame input schema 검증 | Validator | `ms-odd-validate` |
| full recording debugging | ODLD Explorer | `python scripts/odld_explorer/generate.py` |
| unit/integration regression | Pytest | `python -m pytest` |

문제가 발생했을 때 바로 detector threshold를 바꾸기보다 적절한 툴로 upstream 원인을 확인하는 것이 중요합니다.

---

## 7. 설치 및 데이터 준비

### Linux

```bash
git clone https://github.com/livmeraki/ms-odd-tagging.git
cd ms-odd-tagging
git switch refactor/repo-cleanup-20260813

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### Windows PowerShell

```powershell
git clone https://github.com/livmeraki/ms-odd-tagging.git
Set-Location ms-odd-tagging
git switch refactor/repo-cleanup-20260813

python -m venv .venv-win
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv-win\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

환경 변수:

Linux:

```bash
export MS_ODD_DATA_ROOT=/absolute/path/to/data
export MS_ODD_OUTPUT_ROOT=/absolute/path/to/outputs
```

Windows:

```powershell
$env:MS_ODD_DATA_ROOT = "D:\path\to\data"
$env:MS_ODD_OUTPUT_ROOT = "D:\path\to\outputs"
```

Raw recording 구조:

```text
$MS_ODD_DATA_ROOT/01_raw/<RECORDING_ID>/
    annotations_OD.json
    annotations_LD.json
    traj_lcs.txt
```

---

## 8. 기본 실행 방법

CLI 목록:

```text
ms-odd-tagging
ms-odd-canonical
ms-odd-frames
ms-odd-rules
ms-odd-lane
ms-odd-topology
ms-odd-vlm
ms-odd-gt
ms-odd-validate
```

먼저 help를 확인합니다.

```bash
ms-odd-tagging --help
```

Smoke test:

```bash
ms-odd-tagging <RECORDING_ID> \
  --frame-limit 1 \
  --existing-output regenerate
```

일반 실행:

```bash
ms-odd-tagging <RECORDING_ID>
```

주요 옵션:

```bash
ms-odd-tagging <RECORDING_ID> --frames-per-second 2
ms-odd-tagging <RECORDING_ID> --all-frames
ms-odd-tagging <RECORDING_ID> --existing-output resume
ms-odd-tagging <RECORDING_ID> --existing-output regenerate
ms-odd-tagging <RECORDING_ID> --stop-after canonical
```

---

## 9. ODLD Explorer 사용법

Linux:

```bash
python scripts/odld_explorer/generate.py \
  --source-root "$MS_ODD_DATA_ROOT/01_raw" \
  --canonical-dir "$MS_ODD_OUTPUT_ROOT/01_canonical" \
  --output-dir "$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers" \
  --index-path "$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers/index.html" \
  --regenerate-existing
```

Windows PowerShell:

```powershell
python scripts/odld_explorer/generate.py `
  --source-root (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") `
  --canonical-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "01_canonical") `
  --output-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "07_odld_scenario_explorers") `
  --index-path (Join-Path $env:MS_ODD_OUTPUT_ROOT "07_odld_scenario_explorers\index.html") `
  --regenerate-existing
```

생성 후:

```text
<MS_ODD_OUTPUT_ROOT>/07_odld_scenario_explorers/index.html
```

Detector 결과가 이상할 때 다음 순서로 원인을 좁힙니다.

```text
raw OD / LD
→ canonical
→ lane / topology
→ relation feature
→ detector state
→ temporal event
```

---

## 10. GT Workspace 사용법

```bash
ms-odd-gt \
  --frame-root "$MS_ODD_OUTPUT_ROOT/02_frame_inputs" \
  --gt-root "$MS_ODD_OUTPUT_ROOT/06_gt_comparison/gt" \
  --source-hz 10 \
  --sample-hz 1 \
  --host 127.0.0.1 \
  --port 8765
```

Browser:

```text
http://127.0.0.1:8765
```

권장 순서:

```text
prediction 생성
→ GT Workspace 실행
→ prefilled label 확인
→ 오류 수정
→ reviewed 상태 저장
→ evaluation에 사용
```

Frame input과 frame tag가 서로 다른 source frame을 선택할 가능성이 있으므로 정합 문제를 볼 때는 frame index뿐 아니라 timestamp도 확인합니다.

---

## 11. VLM 사용법과 개발 방법

옵션 확인:

```bash
ms-odd-vlm --help
```

현재 VLM workflow는 OpenAI-compatible endpoint를 호출하는 구조이며 local inference는 vLLM/Qwen 기반으로 설계되어 있습니다.

개발 루프:

```text
1. candidate 생성
2. candidate recall 확인
3. evidence 확인
4. BEV 확인
5. VLM inference
6. validation 결과 확인
7. GT와 비교
8. candidate / prompt / validation 수정
```

중요:

- correct event가 candidate로 생성되지 않으면 prompt를 개선해도 FN을 해결할 수 없습니다.
- candidate recall과 VLM decision accuracy를 별도로 측정해야 합니다.
- native Windows에서는 client는 실행할 수 있지만 local vLLM server는 Linux/WSL2/remote Linux GPU 환경을 사용합니다.

---

## 12. 잘못된 Scenario 결과를 디버깅하는 순서

Threshold부터 바꾸지 말고 다음 순서로 확인합니다.

```text
1. source data가 실제로 존재하는가?
2. canonical alignment가 맞는가?
3. feature/relation 계산이 맞는가?
4. lane/topology가 맞는가?
5. detector frame-level state가 맞는가?
6. temporal segmentation에서 사라지거나 잘렸는가?
7. VLM scenario라면 candidate가 생성되었는가?
8. VLM에 올바른 evidence/BEV가 전달되었는가?
9. validation이 model output을 reject했는가?
10. GT가 올바른가?
```

이 순서를 지키면 downstream detector 문제처럼 보이는 현상이 실제로는 lane reconstruction이나 candidate generation 문제였다는 것을 빠르게 구분할 수 있습니다.

---

## 13. 후속 고도화에서 중요한 영역

### Lane continuity / reconstruction

LD segment가 실제 physical lane과 1:1로 대응하지 않을 수 있습니다.

영향:

- `changing_lane*`
- `following_lane*`
- lead/trail relation
- intersection exit stability

Physical lane assignment와 logical continuity를 분리해서 유지해야 합니다.

### Intersection false lane change

Intersection 진입/통과 과정의 lane ID 변화가 lane change처럼 보일 수 있습니다. 관련 suppression logic을 수정할 때 regression set이 반드시 필요합니다.

### Short / missing LD

짧은 boundary나 missing segment는 lane/topology reconstruction을 불안정하게 만듭니다. Persistence를 넣을 수 있지만 잘못된 geometry를 너무 오래 유지하지 않도록 expiry 기준이 필요합니다.

### Traffic-light temporal sparsity

Traffic-light object가 일부 source frame에서만 관측될 수 있습니다. 1 FPS BEV에는 해당 관측이 빠질 수 있습니다.

개선 시 고려:

- temporal existence persistence
- missing-gap tolerance
- stopline/intersection association 유지
- confidence decay / expiry

Source에 traffic-light state가 없으면 state를 임의 생성하면 안 됩니다.

### Object velocity / association noise

특히 다음 영역에 민감합니다.

- `near_high_speed_vehicle`
- `crossed_by_*`
- slow-lead logic

Threshold 조정 전에 association quality와 frame gap을 먼저 확인합니다.

### Jerk / derivative noise

Trajectory의 작은 noise가 acceleration/jerk에서 크게 증폭될 수 있으므로 temporal filtering, sample-gap validation, hysteresis가 중요합니다.

### VLM runtime

VLM은 deterministic rule보다 비용이 큽니다. 다음 구조를 유지하는 것이 좋습니다.

- candidate gating
- episode merge
- image 수 제한
- cache

---

## 14. 새로운 Rule Scenario를 추가하는 방법

```text
1. taxonomy / policy 정의 확인
2. scenario_catalog.csv 추가 또는 수정
3. 필요한 evidence 정의
4. 기존 feature/relation에 evidence가 있는지 확인
5. 없으면 reusable feature layer에 추가
6. frame-level state 구현
7. temporal segmentation 구현
8. direct_scenarios.yaml 설정 추가
9. unit test 추가
10. ODLD Explorer로 결과 확인
11. GT 작성/검토
12. 고정 recording set에서 evaluation
13. threshold calibration
14. 문서 업데이트
```

Geometry 계산을 여러 detector에 복제하지 말고 공통 feature layer를 우선 사용합니다.

---

## 15. 새로운 VLM Scenario를 추가하는 방법

```text
1. scenario_catalog.csv 추가/수정
2. high-recall deterministic candidate rule 정의
3. candidate episode merge 정의
4. 필요한 evidence 정의
5. 대표 BEV frame 선택
6. prompt / output contract 정의
7. structured response validation 구현
8. accepted decision을 event로 merge
9. positive + hard-negative GT 구성
10. candidate recall과 VLM accuracy를 별도로 평가
```

VLM 성능을 평가할 때는 반드시 다음 두 가지를 분리합니다.

```text
Candidate Recall
= 정답 event가 VLM까지 도달했는가?

VLM Decision Quality
= 올바른 candidate가 주어졌을 때 model이 맞게 판단했는가?
```

---

## 16. 테스트와 Regression 원칙

전체 test:

```bash
python -m pytest
```

Lane/topology 변경 시에는 unit test만으로 충분하지 않습니다. 최소한 다음 recording 유형을 고정 regression set으로 유지하는 것이 좋습니다.

```text
straight road
left lane change
right lane change
straight intersection traversal
left/right intersection turn
short/missing LD segment
split/merge lane
```

평가 결과를 기록할 때는 최소한 다음을 같이 저장합니다.

- commit SHA
- GT version
- config version
- recording list
- scenario subset
- evaluation unit
- result artifact

---

## 17. 다음 개발자가 지켜야 할 유지보수 원칙

1. 하나의 feature에 하나의 current implementation만 유지합니다.
2. Scenario 지원 상태는 `scenario_catalog.csv`를 기준으로 관리합니다.
3. Threshold는 문서가 아니라 config에 둡니다.
4. Detector가 raw 데이터를 각각 재해석하지 않고 canonical/features를 재사용합니다.
5. Full-frame rule evaluation과 sampled-frame review는 다른 개념으로 유지합니다.
6. Source에 없는 정보를 임의로 추론해 저장하지 않습니다. 특히 traffic-light state에 주의합니다.
7. Lane/topology 변경은 shared infrastructure 변경으로 보고 downstream regression을 확인합니다.
8. VLM candidate recall과 VLM accuracy를 분리해 측정합니다.
9. 정량 결과에는 commit/config/GT version을 함께 기록합니다.
10. Public command, path, schema, workflow가 바뀌면 handover 문서도 같이 수정합니다.

---

## 18. 인수 후 첫 주 권장 순서

### Day 1

- fresh clone
- 설치
- one-recording smoke test
- `outputs/01_canonical` 확인
- `outputs/02_frame_inputs` 확인

### Day 2

- ODLD Explorer 생성
- 정상 lane case 1개와 오류 case 1개 확인
- `05_ALGORITHMS.md`, `07_KNOWN_ISSUES.md` 읽기

### Day 3

- GT Workspace 실행
- 작은 recording set review
- `scenario_catalog.csv`, `direct_scenarios.yaml` 이해

### Day 4

- false positive 1개, false negative 1개 선택
- source → canonical → features → detector → event 전체 trace

### Day 5

- reproducible evaluation subset 고정
- `python -m pytest` 실행
- 측정된 failure case를 기준으로 첫 개선 과제 선택

이 정도까지 수행하면 전체 repository를 다시 reverse engineering하지 않고도 이후 lane/topology, rule detector, GT/evaluation, VLM 개선 작업을 이어갈 수 있습니다.
