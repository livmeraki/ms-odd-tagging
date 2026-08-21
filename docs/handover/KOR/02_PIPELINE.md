# Pipeline

## 1. 문서 목적

이 문서는 Motional Scenario tagging 시스템의 각 처리 단계를 **실제 코드의 입력·출력 계약(interface contract)** 기준으로 설명한다.

인수자는 이 문서를 통해 다음을 확인할 수 있어야 한다.

- 어느 명령이 어느 단계까지 실행하는가
- 각 단계가 읽는 파일과 생성하는 파일은 무엇인가
- upstream과 downstream이 공유하는 schema와 정합 조건은 무엇인가
- 오류가 발생했을 때 어느 경계부터 확인해야 하는가

세부 JSON field와 자료형은 [03_DATA_FORMAT.md](./03_DATA_FORMAT.md)를 함께 참고한다.

## 2. 논리적 전체 흐름과 실제 실행 범위

### 2.1 논리적 전체 시스템

```text
Raw OD + Raw LD + Ego Trajectory
                  │
                  ▼
            Canonicalization
                  │
                  ▼
       Full-rate Canonical Recording
                  │
        ┌─────────┴─────────┐
        ▼                   ▼
Rule / Geometry / Lane   Sampled Frame Input / BEV
Temporal Analysis        (기본 1 FPS)
        │                   │
        ▼                   ├──────────────┐
ScenarioEvent              │              │
        │                   ▼              ▼
        │               GT Workspace   VLM Evidence
        │                                  │
        ▼                                  ▼
1 FPS Frame Tags                      Qwen VLM Inference
                                           │
                                           ▼
                                    Validation / Event Merge
```

### 2.2 `ms-odd-tagging` 명령이 실제로 수행하는 범위

`ms-odd-tagging`은 코드상 두 개의 orchestration stage를 실행한다.

| 실행 단계 | 호출 모듈 | 실제 수행 내용 |
|---|---|---|
| Stage 1 | `ms_odd_tagging.canonical.builder` | OD + LD + Trajectory canonical 생성 |
| Stage 2 | `ms_odd_tagging.frame_inputs.builder` | rule/lane recording 분석, rule event 생성, 1 FPS tag 생성, sampled `frame.json`/`bev.png` 생성 |

따라서 Stage 2는 이름이 “Frame Input / BEV Generation”이지만 내부적으로 deterministic tagging 결과도 만든다.

다음 항목은 `ms-odd-tagging`에 자동 포함되지 않으며 별도 실행해야 한다.

- Qwen VLM candidate 생성 및 inference: `ms-odd-vlm`
- GT 검토 및 저장: `ms-odd-gt`
- 전체 recording 시각화: `scripts/odld_explorer/generate.py`
- 독립 lane 분석 artifact 생성: `ms-odd-lane`
- 독립 topology 결과 생성: `ms-odd-topology`

## 3. 전체 명령의 공통 입력과 출력

### 입력

```text
<MS_ODD_DATA_ROOT>/01_raw/<RECORDING_ID>/
├── annotations_OD.json
├── annotations_LD.json
└── traj_lcs.txt
```

세 파일은 모두 필수이다.

### 기본 실행

```bash
ms-odd-tagging <RECORDING_ID>
```

### 기본 출력

```text
<MS_ODD_OUTPUT_ROOT>/
├── 01_canonical/
│   ├── <RECORDING_ID>_canonical_odld_frames.json
│   └── manifest.json
├── 02_frame_inputs/
│   ├── manifest.json
│   ├── bev_review.html
│   └── <RECORDING_ID>/
│       ├── recording_rule_events.json
│       ├── recording_frame_tags_1fps/
│       │   ├── manifest.json
│       │   └── frame_<SOURCE_FRAME_INDEX>.json
│       └── frame_<SOURCE_FRAME_INDEX>/
│           ├── frame.json
│           ├── bev.png
│           └── gt_reference.json
└── runtime_logs/
    └── pipeline_<YYYYMMDD_HHMMSS>.json
```

`<SOURCE_FRAME_INDEX>`는 1 FPS 순번이 아니라 원본 canonical frame index이다.

## 4. Stage 1 — Canonicalization

### 구현

```text
src/ms_odd_tagging/canonical/builder.py
src/ms_odd_tagging/canonical/odld.py
```

### CLI

```bash
ms-odd-canonical \
  --source-root <RAW_ROOT> \
  --output-root <CANONICAL_ROOT> \
  --ld-radius-m 100 \
  <RECORDING_ID>
```

### 입력 계약

| 입력 | 필수 | 계약 |
|---|---:|---|
| `annotations_OD.json` | Yes | `scene.frameCount`와 frame별 OD object state 제공 |
| `annotations_LD.json` | Yes | recording-level lane/road geometry 제공 |
| `traj_lcs.txt` | Yes | 각 source frame에 대응하는 ego pose row 제공 |
| `--ld-radius-m` | No | 양의 유한 실수, 기본 100 m |
| `--include-clipped-ld-geometry` | No | frame LD context에 clipped geometry 포함 여부 |

Canonicalizer가 강제하는 주요 정합 조건:

- `OD scene.frameCount == LD scene.frameCount == trajectory row count`
- trajectory timestamp는 strictly increasing이어야 한다.
- OD `frameIndex`는 trajectory row index와 직접 대응한다.
- LD는 timestamp별 sensor stream이 아니라 recording-level static/shared map으로 처리한다.
- OD/LD scene id 또는 name 불일치는 warning으로 기록하지만, frame count가 맞으면 처리를 계속할 수 있다.

### 출력 계약

| 출력 | Schema | 설명 |
|---|---|---|
| `<RECORDING_ID>_canonical_odld_frames.json` | `odld-trajectory-canonical-frame-v1` | full-rate recording canonical |
| `manifest.json` | `odld-trajectory-canonical-manifest-v1` | recording 목록, 경로, 길이, frame rate, LD quality |

Canonical 파일의 핵심 top-level field:

```text
schema_version
recording_id
source
recording
scenario_taxonomy
ld_configuration
ld_feature_store
data_quality
frames[]
```

`frames[]`의 핵심 field:

```text
frame_index
timestamp_unix_s
time_since_start_s
ego
objects
scenario_signals
interaction_candidates
ld
```

성공 시 recording canonical과 manifest를 기록한다. 필수 파일 누락, frame-count 불일치, timestamp 오류, 잘못된 LD point/reference 등은 실패 원인이 된다.

## 5. Stage 2 — Recording Analysis, Frame Input, BEV, Frame Tags

### 구현

```text
src/ms_odd_tagging/frame_inputs/builder.py
src/ms_odd_tagging/frame_inputs/generator.py
src/ms_odd_tagging/frame_inputs/_generator.py
src/ms_odd_tagging/frame_inputs/model_input.py
src/ms_odd_tagging/frame_inputs/frame_tags.py
```

### CLI

```bash
ms-odd-frames \
  --input-dir <CANONICAL_ROOT> \
  --output-dir <FRAME_INPUT_ROOT> \
  --recording <RECORDING_ID> \
  --frames-per-second 1 \
  --existing-output regenerate
```

### 입력 계약

| 입력 | 필수 | 계약 |
|---|---:|---|
| `*_canonical_odld_frames.json` | Yes | Stage 1 canonical schema |
| `configs/direct_scenarios.yaml` | Yes | rule detector 및 temporal parameter |
| `configs/following_lane.json` | Subsystem | following-lane 분석 설정 |
| `--frames-per-second` | No | timestamp 기반 sampling, 기본 1.0 |
| `--all-frames` | No | sampling 없이 모든 canonical frame 출력 |
| `--max-objects` | No | `frame.json`에 유지할 object 최대 수, 기본 80 |
| BEV extent/size | No | width, height, left/right/back/forward 범위 |

`--frames-per-second`와 `--all-frames`는 동시에 사용할 수 없다.

### 5.1 Recording-wide rule/lane analysis

Frame Input 생성 전에 full canonical sequence를 사용하여 다음을 계산한다.

- 공통 feature/relation
- rule-based scenario event
- following-lane frame state와 interval
- data-quality summary

내부 cache:

```text
<FRAME_INPUT_ROOT>/<RECORDING_ID>/.cache/recording_analysis.json
```

Cache signature가 canonical/config/code와 맞으면 재사용한다. `--refresh-analysis`를 주면 재계산한다.

### 5.2 Rule event 출력

```text
<FRAME_INPUT_ROOT>/<RECORDING_ID>/recording_rule_events.json
```

Schema:

```text
rule-based-scenario-events-v1
```

핵심 구조:

```json
{
  "schema_version": "rule-based-scenario-events-v1",
  "recording_id": "<RECORDING_ID>",
  "interval_boundary_convention": "inclusive_samples",
  "rule_based_events": [
    {
      "scenario": "changing_lane",
      "start_frame": 120,
      "end_frame": 148,
      "start_timestamp_s": 12.0,
      "end_timestamp_s": 14.8,
      "duration_s": 2.8,
      "confidence": 1.0,
      "source": "rule_based",
      "detector_version": "...",
      "evidence": {}
    }
  ],
  "data_quality": {}
}
```

`start_frame`과 `end_frame`은 모두 포함되는 inclusive boundary이다.

### 5.3 1 FPS frame-tag 출력

```text
<FRAME_INPUT_ROOT>/<RECORDING_ID>/recording_frame_tags_1fps/
├── manifest.json
└── frame_<SOURCE_FRAME_INDEX>.json
```

Sampling 방식은 각 정수 초 `0s, 1s, 2s, ...`에 가장 가까운 original frame을 선택하는 방식이다. 같은 source frame이 중복 선택되면 한 번만 기록한다.

각 frame-tag JSON은 scenario별 boolean 상태를 저장한다. 이 파일이 GT Workspace의 prediction 입력이다.

### 5.4 Sampled frame input 출력

각 선택 frame마다 다음 디렉터리를 만든다.

```text
frame_<SOURCE_FRAME_INDEX>/
├── frame.json
├── bev.png
└── gt_reference.json
```

역할:

| 파일 | 소비자 | 계약 |
|---|---|---|
| `frame.json` | model/VLM/debugging/validator | 같은 source frame의 canonical state |
| `bev.png` | VLM/GT/debugging | `frame.json`과 동일 frame, ego-heading-up |
| `gt_reference.json` | 사람 검토/debugging | rule/lane derivation reference; model input과 분리 |
 
`frame.json`에는 정답 label을 넣지 않는다. 이는 model input leakage를 방지하기 위한 계약이다.

Frame schema:

```text
odld-dynamic-frame-model-input-v1
```

BEV schema:

```text
odld-per-frame-bev-v1
```

### 5.5 Stage 2 manifest와 review page

```text
<FRAME_INPUT_ROOT>/manifest.json
<FRAME_INPUT_ROOT>/bev_review.html
```

Manifest schema는 `odld-per-frame-input-manifest-v1`이며 recording별 canonical frame 수, 생성된 frame 수, sampling rate, cache hit 여부 및 각 artifact 경로를 기록한다.

## 6. Existing-output 정책과 재실행 계약

`--existing-output` 값:

| 값 | 동작 |
|---|---|
| `ask` | 기존 출력이 있으면 대화형 선택 요구 |
| `resume` | generation fingerprint가 일치하는 completed frame 재사용 |
| `regenerate` | 대상 frame 출력을 다시 생성 |
| `cancel` | 기존 출력을 변경하지 않고 종료 |

Batch 또는 원격 실행에서는 `ask` 대신 `resume` 또는 `regenerate`를 명시하는 것을 권장한다.

`resume`은 파일 존재 여부만 보는 것이 아니라 generation signature/fingerprint를 이용해 현재 설정과 맞는 frame인지 확인한다.

## 7. Rule / Feature / Event 인터페이스

### Feature extraction

```text
src/ms_odd_tagging/features/
├── ego_motion.py
├── object_relations.py
├── road_feature_relations.py
├── pedestrian_crosswalk_relations.py
├── object_path_crossing_relations.py
├── traffic_relations.py
└── traffic_light_context.py
```

공통 입력은 canonical recording 또는 canonical frame이며, 출력은 detector가 재사용할 relation/evidence dictionary이다.

### Rule detector

```text
src/ms_odd_tagging/tagger/rule_based/registry.py
configs/direct_scenarios.yaml
```

공통 출력 단위는 `ScenarioEvent`이다.

```text
Canonical sequence
→ reusable feature/relation
→ frame-level state
→ hysteresis / temporal filtering
→ event segmentation
→ ScenarioEvent
```

Threshold, minimum duration, inactive gap, merge gap, hysteresis, pre/post roll은 config가 source of truth이다.

## 8. Following Lane 독립 CLI 인터페이스

`ms-odd-tagging`의 Stage 2에서는 following-lane 결과가 내부 분석과 rule event에 사용된다. 별도 artifact와 explorer가 필요하면 `ms-odd-lane`을 실행한다.

### 입력

```text
<Canonical Root>/<RECORDING_ID>_canonical_odld_frames.json
configs/following_lane.json
```

### 출력

```text
<OUTPUT_ROOT>/
├── 01_lane_geometry/<RECORDING_ID>_lane_geometry.json
├── 02_frame_assignments/<RECORDING_ID>_frame_assignments.json
├── 03_tags/<RECORDING_ID>_following_lane_tags.json
└── 04_visualization/<RECORDING_ID>_following_lane_explorer.html
```

각 단계는 `--stop-after lane-geometry|assignments|tags|visualization`으로 중단할 수 있다.

## 9. LD Topology 독립 CLI 인터페이스

### 입력

```text
<Canonical Root>/<RECORDING_ID>_canonical_odld_frames.json
configs/ld_topology.json
```

### 출력

```text
<OUTPUT_ROOT>/
├── results/<RECORDING_ID>_ld_topology.json
├── csv/<RECORDING_ID>_ld_topology_frames.csv
└── debug_images/                         # --debug-images 사용 시
```

`--frame INDEX` 또는 `--frame START:STOP`으로 일부 frame만 분석할 수 있다.

## 10. Qwen VLM 인터페이스

Qwen VLM은 `ms-odd-tagging` main command와 분리된 hybrid verifier이다.

### 구현

```text
src/ms_odd_tagging/vlm/
```

### 입력

| 입력 | 설명 |
|---|---|
| canonical recording | candidate 생성의 source |
| scenario group | `on_intersection`, `starting_u_turn`, `traffic_light_episode` |
| deterministic candidate | VLM에 전달할 episode/window |
| BEV evidence | candidate 구간에서 선택된 최대 이미지 수 |
| OpenAI-compatible endpoint | 기본 `http://127.0.0.1:8001/v1/chat/completions` |
| model | 기본 Qwen VL model 설정 |

### 처리 계약

```text
Canonical + rule/geometry evidence
→ high-recall candidate/episode
→ candidate bundle + BEV
→ Qwen VL inference
→ structured response validation
→ accepted decision
→ merged event JSON
```

### 출력

```text
<output_root>/
├── manifest_candidate_only_<SCENARIO>.json   # --candidate-only
├── manifest_<SCENARIO>.json
├── events/<SCENARIO>/<RECORDING_ID>_events.json
├── raw_responses/<SCENARIO>/
├── request_payloads/<SCENARIO>/
├── cache/
└── review/                                   # review bundle export 시
```

Manifest schema는 `qwen-vlm-poc-run-manifest-v1`이며 config, candidate bundle, raw result, validation, accepted event 및 review bundle 경로를 기록한다.

VLM event는 현재 자동으로 `recording_rule_events.json` 또는 `recording_frame_tags_1fps`에 합쳐지지 않는다. 최종 통합 결과를 사용할 경우 rule/VLM merge 경계를 명시적으로 확인해야 한다.

## 11. GT Workspace 인터페이스

### 입력

```text
--frame-root <MS_ODD_OUTPUT_ROOT>/02_frame_inputs
--gt-root <MS_ODD_OUTPUT_ROOT>/06_gt_comparison/gt
```

GT Workspace가 읽는 항목:

- `frame_<INDEX>/frame.json`
- `frame_<INDEX>/bev.png`
- `recording_frame_tags_1fps/frame_<INDEX>.json`
- 기존 `<RECORDING_ID>_manual_gt.json`

Prediction alignment 순서:

1. exact source frame index
2. exact match가 없으면 nearest timestamp
3. 허용 범위는 sample period의 절반

### 출력

```text
<GT_ROOT>/<RECORDING_ID>_manual_gt.json
```

현재 저장 schema는 `simplified-manual-gt-v1`이다. prediction은 초기값으로 사용할 수 있지만 최종 GT는 사람이 review한 frame만 저장해야 한다.

## 12. ODLD Explorer 인터페이스

일반 실행 entrypoint:

```text
scripts/odld_explorer/generate.py
```

입력:

- raw recording root
- canonical root
- scenario/tagging 결과
- 출력 디렉터리와 index path

출력:

- recording별 HTML explorer
- dataset-level `index.html`

Explorer는 full recording의 geometry, object, trajectory, lane/topology 및 scenario interval 원인을 분석하는 도구이다. GT Workspace의 sampled-frame label review와 목적이 다르다.

## 13. Runtime log와 종료 상태

`ms-odd-tagging`은 다음 runtime report를 기록한다.

```text
<MS_ODD_OUTPUT_ROOT>/runtime_logs/pipeline_<TIMESTAMP>.json
```

핵심 field:

```text
recorded_at
recordings[]
stages[]
failures[]
total_elapsed_seconds
average_pipeline_elapsed_seconds_per_successful_recording
average_pipeline_recording_count
```

동작:

- 한 recording 실패가 다른 recording 처리를 반드시 중단시키지는 않는다.
- 필수 raw 파일이 없는 recording은 실패로 기록하고 skip한다.
- canonicalization이 실패한 recording은 Stage 2로 전달하지 않는다.
- 하나 이상의 pipeline failure가 있으면 최종 return code는 1이다.
- 정상 완료는 0이다.
- interactive existing-output 선택을 수행할 수 없는 상태 등은 frame generator에서 2를 반환할 수 있다.

## 14. 핵심 정합 계약

- OD `frameIndex`는 trajectory row index와 직접 대응한다.
- LD는 recording-level static/shared map이고 frame별 timestamp stream이 아니다.
- Canonical은 source frame을 drop하지 않는다.
- Dynamic object state는 관측 gap을 임의로 forward-fill하지 않는다.
- Rule/event 계산은 full canonical sequence를 사용할 수 있다.
- `frame.json`/BEV와 frame tags는 sampling된 original source frame을 사용한다.
- 1 FPS ordinal과 source frame index를 혼동하지 않는다.
- `frame.json`과 `bev.png`는 반드시 같은 source frame이어야 한다.
- `frame.json`에는 GT 또는 최종 scenario label을 삽입하지 않는다.
- unsupported semantic label은 약한 evidence만으로 자동 추측하지 않는다.
- source에 없는 traffic-light state를 생성하거나 저장하지 않는다.
- public command, output path, schema가 바뀌면 이 문서와 `03_DATA_FORMAT.md`를 함께 수정한다.

## 15. Source of truth

문서와 구현이 다를 경우 다음 순서로 현재 계약을 확인한다.

1. CLI entrypoint: `pyproject.toml`
2. Main orchestration: `src/ms_odd_tagging/pipeline.py`
3. Canonical schema/write path: `canonical/odld.py`
4. Frame output/write path: `frame_inputs/generator.py` 및 `_generator.py`
5. Frame validation: `validator/frame_schema.py`
6. Event type: `tagger/rule_based/scenario_event.py`
7. Frame-tag export: `frame_inputs/frame_tags.py`
8. VLM output: `vlm/cli.py`
9. GT persistence: `gt/workspace.py`
