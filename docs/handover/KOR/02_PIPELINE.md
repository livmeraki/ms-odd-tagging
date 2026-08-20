# Pipeline

## 1. 전체 흐름

현재 repository는 raw OD/LD annotation과 Ego Trajectory를 common canonical representation으로 정합한 뒤, frame-level model input/BEV와 rule-based Motional Scenario tag를 생성하고, 마지막에 Simplified Taxonomy GT Workspace를 기본 reviewer로 실행한다.

```text
Raw Recording
├── annotations_OD.json
├── annotations_LD.json
└── traj_lcs.txt
        │
        ▼
Stage 1. OD+LD Canonicalization
        │
        ▼
outputs/01_canonical
        │
        ▼
Stage 2. Frame Input / BEV generation
        │
        ├── frame_XXXXXX/frame.json
        ├── frame_XXXXXX/bev.png
        ├── recording_rule_events.json
        └── recording_frame_tags_1fps/
                │
                ▼
Default GT Review
ms_odd_tagging.simplified_taxonomy.gt_workspace_profiled
                │
                ├── current frame-tag prediction mapping
                ├── BEV + Prediction + GT review
                └── autosave
                        │
                        ▼
outputs/06_gt_comparison/gt
```

`run_pipeline.py`를 기본 option으로 실행하면 Stage 2 완료 후 GT Workspace가 자동으로 실행된다. interactive server를 띄우지 않는 unattended/batch input generation에서는 `--no-gt-workspace`를 사용한다.

## 2. Stage 1 — Canonicalization

관련 module:

```text
src/ms_odd_tagging/canonical/builder.py
src/ms_odd_tagging/canonical/
```

지원되는 active canonical path는 OD+LD이다. Raw OD, LD, trajectory를 frame 기준으로 정합하고, 이후 detector와 BEV generator가 함께 사용할 recording representation을 만든다.

주요 contract:

- OD+LD canonical을 active path로 사용
- 숫자 0은 valid data이며 `null`로 바꾸지 않음
- LD는 recording-level static geometry이며 frame별 nearby reference와 함께 사용
- frame index와 timestamp를 downstream에서 임의 추정하지 않도록 canonical 단계에서 정합

## 3. Stage 2 — Frame Input / BEV + Rule Frame Tags

관련 module:

```text
src/ms_odd_tagging/frame_inputs/builder.py
src/ms_odd_tagging/frame_inputs/_standard_impl.py
src/ms_odd_tagging/frame_inputs/frame_tags.py
```

기본 pipeline은 timestamp 기준 1 FPS로 frame input을 생성한다.

각 sampled frame:

```text
02_frame_inputs/<recording>/frame_XXXXXX/
├── frame.json
├── bev.png
└── gt_reference.json
```

recording-level rule evaluation 결과는 같은 recording directory 아래에 저장된다.

```text
02_frame_inputs/<recording>/
├── recording_rule_events.json
└── recording_frame_tags_1fps/
    ├── manifest.json
    └── frame_XXXXXX.json
```

`recording_frame_tags_1fps`는 current simplified GT prediction의 source이다.

## 4. Rule-based Feature Extraction

주요 feature module:

```text
src/ms_odd_tagging/features/ego_motion.py
src/ms_odd_tagging/features/object_relations.py
src/ms_odd_tagging/features/road_feature_relations.py
src/ms_odd_tagging/features/pedestrian_crosswalk_relations.py
src/ms_odd_tagging/features/object_path_crossing_relations.py
src/ms_odd_tagging/features/traffic_relations.py
src/ms_odd_tagging/features/traffic_light_context.py
```

각 detector가 raw JSON을 반복 해석하지 않고 공통 feature/relation을 재사용한다.

## 5. Rule-based Scenario Detection

중심 registry:

```text
src/ms_odd_tagging/tagger/rule_based/registry.py
```

주요 detector:

```text
dynamics.py
turns.py
lane_changes.py
crosswalks.py
object_interactions.py
pedestrian_crosswalks.py
object_path_crossings.py
traffic_interactions.py
```

registry는 configuration의 `enabled_scenarios`와 detector mapping을 기준으로 recording 전체를 평가하고 time range를 가진 `ScenarioEvent`를 생성한다.

## 6. Event Segmentation

Motional Scenario는 단일 frame boolean보다 시작/종료 구간이 중요하다.

따라서 detector는 frame별 상태 이후 다음 logic을 적용해 event range를 만든다.

- minimum duration
- inactive gap
- merge gap
- hysteresis
- pre/post roll

관련 module:

```text
src/ms_odd_tagging/tagger/rule_based/event_segmentation.py
src/ms_odd_tagging/tagger/rule_based/scenario_event.py
```

## 7. Default Simplified Taxonomy GT Workspace

현재 기본 GT reviewer:

```text
ms_odd_tagging.simplified_taxonomy.gt_workspace_profiled
```

관련 module:

```text
src/ms_odd_tagging/simplified_taxonomy/gt_workspace_profiled.py
src/ms_odd_tagging/simplified_taxonomy/current_frame_predictions.py
src/ms_odd_tagging/simplified_taxonomy/mapper.py
src/ms_odd_tagging/simplified_taxonomy/input_frame_gt.py
src/ms_odd_tagging/simplified_taxonomy/input_frame_gt_server.py
src/ms_odd_tagging/simplified_taxonomy/manual_gt.py
```

### Prediction path

GT Workspace는 current pipeline output인:

```text
02_frame_inputs/<recording>/recording_frame_tags_1fps
```

을 읽는다.

active Motional Scenario label을 `mapper.py`를 통해 simplified taxonomy prediction으로 변환한 뒤, unreviewed GT control에 prefill한다. Prefill된 값은 자동으로 reviewed GT가 되지 않으며 사용자가 Save해야 한다.

### Frame alignment

Frame Input generator와 `recording_frame_tags_1fps` exporter는 1 FPS sampling policy가 다를 수 있다. 예를 들어 같은 시점이 source frame 11과 frame 10으로 선택될 수 있다.

따라서 prediction matching은 다음 순서를 사용한다.

1. exact source frame index
2. exact match가 없으면 nearest timestamp
3. requested sample period의 절반 이내일 때만 accept

이 contract를 바꾸면 BEV와 prediction이 서로 다른 시점을 가리킬 수 있으므로 regression 확인이 필요하다.

### Autosave path

```text
outputs/06_gt_comparison/gt/<recording>_manual_gt.json
```

기존 reviewed GT가 존재하면 prediction prefill로 덮어쓰지 않는다.

### Interactive behavior

GT Workspace는 HTTP server이므로 기본 pipeline 마지막에서 process를 유지한다.

```text
http://127.0.0.1:8765
```

작업 종료 시 `Ctrl+C`를 누른다. CI, unattended batch, input-generation-only run은 `--no-gt-workspace`를 사용한다.

## 8. Lane / Topology 관련 기능

Lane 이해는 여러 scenario의 기반 기능이다.

```text
src/ms_odd_tagging/scenarios/following_lane/
src/ms_odd_tagging/ld_topology/
src/ms_odd_tagging/bev_lane_poc/
src/ms_odd_tagging/lanelet2_poc/
```

주의:

- `lanelet2_poc`는 optional PoC이며 기본 pipeline에서 활성화되지 않음
- physical lane assignment와 logical lane continuity를 구분
- intersection 내부/전후에서는 lane ID stability와 lane-change suppression을 함께 확인

## 9. Full ODLD Scenario Explorer

Default GT Workspace와 별개로 OD / LD / Ego Trajectory / Scenario Event를 전체적으로 확인할 때 사용한다.

권장 runner:

```text
scripts/odld_explorer/generate_odld_dataset_explorers_w_stage_progress.py
```

이 explorer는 debugging/visual inspection tool이며 `run_pipeline.py`의 기본 stage는 아니다.

과거 Full ODLD Scenario Explorer에 authoring panel을 주입하는 tool은 historical/debug path로 남아 있으며 현재 default GT workflow가 아니다.

## 10. Optional VLM Layer

현재 VLM은 deterministic rule/geometry로 candidate와 evidence를 먼저 만들고 semantic judgment가 필요한 case에 제한적으로 적용하는 방향이다.

```text
src/ms_odd_tagging/qwen_vlm_poc/
src/ms_odd_tagging/tagger/model_based/
```

원칙:

> 계산 가능한 scenario를 VLM에 먼저 맡기지 않는다.

## 11. Validation / Evaluation

관련 package:

```text
src/ms_odd_tagging/validator/
src/ms_odd_tagging/gt_comparison/
src/ms_odd_tagging/simplified_taxonomy/
```

현재 manual GT authoring의 default entry point는 Simplified Taxonomy GT Workspace이며, 평가 시 prediction source, GT version, sampling rate, commit SHA를 함께 기록해야 한다.

## 12. Pipeline 설계 시 유지해야 할 계약

- model input에 rule-derived answer를 직접 넣지 않는다.
- timestamp와 frame index alignment를 임의로 가정하지 않는다.
- GT Workspace prediction은 `recording_frame_tags_1fps`의 current output을 기준으로 한다.
- Prediction-prefill과 human-reviewed GT를 구분한다.
- 기존 reviewed GT를 prediction으로 덮어쓰지 않는다.
- 1 FPS visualization/review sampling과 full-frame rule evaluation을 구분한다.
- unsupported semantic label을 약한 evidence로 추측하지 않는다.
- PoC module을 production/active pipeline과 동일하게 취급하지 않는다.
