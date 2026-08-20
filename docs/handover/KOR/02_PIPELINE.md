# Pipeline

## 1. 전체 흐름

현재 repository는 raw OD/LD annotation과 ego trajectory를 canonical representation으로 정합하고, rule/geometry 기반 Motional Scenario 판단과 필요한 구간의 VLM-assisted 판단을 수행한다.

```text
Raw Recording
├── annotations_OD.json
├── annotations_LD.json
└── traj_lcs.txt
        │
        ▼
OD + LD + Trajectory Canonicalization
        │
        ▼
outputs/01_canonical
        │
        ├──────────────────────────────┐
        │                              │
        ▼                              ▼
Rule / Geometry / Temporal       Frame Input / BEV
Feature Extraction               Generation (1 FPS default)
        │                              │
        ├───────────────┐              │
        │               │              │
        ▼               ▼              │
Deterministic       VLM Candidate      │
Scenario Detection  / Episode Selection│
        │               │              │
        │               ▼              │
        │          Evidence / BEV ◄────┘
        │               │
        │               ▼
        │          VLM Inference
        │               │
        │               ▼
        │          Validation / Merge
        │               │
        └───────┬───────┘
                ▼
       Motional Scenario Output
                │
                ▼
   recording_frame_tags_1fps
                │
                ▼
 Simplified Taxonomy GT Workspace
```

VLM은 전체 frame을 brute-force로 판단하지 않는다. Rule / Geometry / Temporal evidence로 candidate 또는 episode를 선택한 뒤 의미적 판단이 필요한 구간에만 적용한다.

## 2. Canonicalization

공식 module:

```text
src/ms_odd_tagging/canonical/builder.py
src/ms_odd_tagging/canonical/odld.py
```

입력:

```text
annotations_OD.json
annotations_LD.json
traj_lcs.txt
```

주요 역할:

- OD object state와 ego trajectory frame alignment
- ego pose / speed / acceleration / yaw-rate 구성
- recording-level LD geometry normalization
- `ld_feature_store` 구성
- frame별 nearby LD feature reference 구성
- downstream rule/geometry/VLM 단계가 공유하는 canonical frame sequence 생성

Canonical schema:

```text
odld-trajectory-canonical-frame-v1
```

주요 contract:

- source frame index와 trajectory alignment를 보존한다.
- 숫자 `0`은 valid data이며 `null`로 변환하지 않는다.
- complete LD geometry는 recording-wide `ld_feature_store`에 저장한다.
- 각 frame은 필요한 LD feature를 reference한다.

## 3. Frame Input / BEV

공식 module:

```text
src/ms_odd_tagging/frame_inputs/builder.py
```

기본 sampling은 real timestamp 기준 1 FPS이다. 선택된 각 timestamp에 대해 다음을 생성한다.

```text
frame_XXXXXX/
├── frame.json
└── bev.png
```

Frame Input은 reviewer와 VLM evidence에서 사용하는 frame-level representation이다.

## 4. Feature Extraction

공통 feature layer:

```text
src/ms_odd_tagging/features/ego_motion.py
src/ms_odd_tagging/features/object_relations.py
src/ms_odd_tagging/features/road_feature_relations.py
src/ms_odd_tagging/features/pedestrian_crosswalk_relations.py
src/ms_odd_tagging/features/object_path_crossing_relations.py
src/ms_odd_tagging/features/traffic_relations.py
src/ms_odd_tagging/features/traffic_light_context.py
```

Detector가 raw annotation을 각각 다시 해석하기보다 canonical data와 공통 relation을 재사용한다.

## 5. Rule-based Scenario Detection

중심 registry:

```text
src/ms_odd_tagging/tagger/rule_based/registry.py
configs/direct_scenarios.yaml
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

Registry는 enabled scenario와 detector mapping을 기준으로 전체 recording을 평가한다. Detector는 frame별 signal을 계산한 뒤 필요한 경우 시간 구간을 가진 `ScenarioEvent`로 구성한다.

## 6. Event Segmentation

관련 module:

```text
src/ms_odd_tagging/tagger/rule_based/event_segmentation.py
src/ms_odd_tagging/tagger/rule_based/scenario_event.py
```

Event range 구성에는 scenario에 따라 다음 요소를 사용한다.

- minimum duration
- inactive gap
- merge gap
- hysteresis
- pre/post roll

## 7. Lane / Topology

현재 lane/topology 관련 구현:

```text
src/ms_odd_tagging/scenarios/following_lane/
src/ms_odd_tagging/ld_topology/
configs/following_lane.json
configs/ld_topology.json
```

Following-lane과 lane topology 결과는 lane relation, lane-change/turn 판단 및 일부 VLM candidate evidence에 사용된다.

## 8. VLM Candidate Selection / VLM-assisted Tagging

관련 package:

```text
src/ms_odd_tagging/qwen_vlm_poc/
```

처리 순서:

```text
Canonical + Rule/Geometry Feature
              │
              ▼
      Candidate / Episode Selection
              │
              ▼
        Evidence Construction
              │
              ▼
          VLM Inference
              │
              ▼
       Validation / Merge
```

현재 VLM group:

```text
on_intersection
starting_u_turn
traffic_light_episode
```

`traffic_light_episode`는 하나의 episode에서 여러 traffic-light 관련 최종 scenario를 판별한다. 최종 label mapping은 다음을 source of truth로 사용한다.

```text
src/ms_odd_tagging/qwen_vlm_poc/config.py
configs/scenario_catalog.csv
```

## 9. Frame-level Tag Export

Frame-level prediction은 다음 위치에 기록된다.

```text
outputs/02_frame_inputs/<RECORDING_ID>/recording_frame_tags_1fps/
```

각 JSON은 해당 frame의 Motional Scenario boolean 상태를 포함한다.

## 10. Simplified Taxonomy GT Workspace

관련 package:

```text
src/ms_odd_tagging/simplified_taxonomy/
```

실행 command:

```text
ms-odd-gt-workspace
```

GT Workspace는 sampled frame의 BEV와 prediction을 함께 보여주고 사람이 최종 GT를 검토·저장하기 위한 도구이다.

## 11. Full ODLD Scenario Explorer

현재 유지하는 explorer scripts:

```text
scripts/odld_explorer/generate_odld_dataset_explorers_w_stage_progress.py
scripts/odld_explorer/generate_odld_dataset_explorers_w_scenario_tag.py
scripts/odld_explorer/odld_explorer_common.py
```

Full ODLD Explorer는 OD, LD, ego trajectory, scenario tag 및 lane/topology context를 함께 확인하기 위한 디버깅/검토 도구이다.

## 12. 유지해야 할 핵심 계약

- canonical input은 OD + LD + Ego Trajectory를 함께 사용한다.
- model-facing `frame.json`에 정답 label을 직접 삽입하지 않는다.
- VLM은 candidate / episode selection 이후 필요한 구간에 적용한다.
- frame index와 timestamp alignment를 명시적으로 처리한다.
- unsupported semantic label은 약한 evidence만으로 추측하지 않는다.
- rule event 계산과 1 FPS reviewer sampling을 구분한다.
