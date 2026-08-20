# Pipeline

## 1. 전체 흐름

현재 repository는 raw OD/LD annotation과 ego trajectory를 하나의 canonical representation으로 정합한 뒤, deterministic rule/geometry tagging과 VLM-assisted tagging을 수행한다.

VLM은 전체 frame을 직접 판단하는 기본 경로가 아니다. 먼저 Rule / Geometry / Temporal logic으로 **VLM이 필요한 구간(candidate / episode)** 을 좁힌 뒤, 해당 candidate에 대해서만 BEV/evidence를 구성하고 VLM이 semantic 판단을 수행한다.

```text
Raw Recording
├── annotations_OD.json
├── annotations_LD.json
└── traj_lcs.txt
        │
        ▼
OD+LD+Trajectory Canonicalization
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
        │          VLM Validation /
        │          Result Merging
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
                │
                ▼
          GT Comparison
```

핵심은 **Rule path와 VLM path가 병렬적인 두 개의 독립 tagger가 아니라는 점**이다. VLM path도 canonical data와 rule/geometry feature를 사용하며, candidate selection을 통해 필요한 구간만 모델에 전달한다.

## 2. Stage 1 — Canonicalization

공식 entry point:

```text
src/ms_odd_tagging/canonical/builder.py
```

현재 canonical path는 **OD + LD + Ego Trajectory 통합 경로 하나**이다.

Canonicalization은 다음 세 입력을 함께 정합한다.

```text
annotations_OD.json
annotations_LD.json
traj_lcs.txt
```

주요 역할:

- OD object state와 ego trajectory frame alignment
- ego speed / acceleration / yaw-rate 등 기본 motion state 구성
- recording-level LD geometry normalization
- `ld_feature_store` 구성
- frame별 nearby LD feature reference 구성
- downstream rule/geometry/VLM candidate 단계가 공유하는 canonical frame sequence 생성

현재 active canonical schema:

```text
odld-trajectory-canonical-frame-v1
```

주요 contract:

- 숫자 `0`은 valid data이며 `null`로 변환하면 안 된다.
- source frame index와 trajectory alignment를 보존한다.
- complete LD geometry는 recording-wide `ld_feature_store`에 저장한다.
- 각 frame은 `ld.nearby_feature_ids` 등 compact reference를 사용한다.
- downstream code는 이 통합 canonical schema를 기준으로 동작한다.

## 3. Stage 2 — Frame Input / BEV

공식 module:

```text
src/ms_odd_tagging/frame_inputs/builder.py
```

기본 pipeline은 real timestamp 기준 1 FPS로 frame을 선택해 각 timestamp마다 독립적인:

- `frame.json`
- `bev.png`

를 생성한다.

각 sampled frame은 GT Workspace와 VLM evidence 구성에서 사용할 수 있는 frame-level input으로 사용된다.

## 4. Rule-based Feature Extraction

registry는 canonical frame sequence를 받아 scenario detector와 VLM candidate selector가 공통으로 사용할 feature를 생성한다.

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

각 detector가 raw JSON을 다시 해석하지 않고 canonical data와 공통 feature/relation을 재사용하는 방향으로 구성되어 있다.

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

registry는 configuration의 `enabled_scenarios`와 detector mapping을 기준으로 전체 recording을 평가하고 시간 구간을 가진 `ScenarioEvent`를 생성한다.

Deterministic rule로 충분히 판별 가능한 scenario는 이 단계에서 최종 결과가 결정된다. VLM이 필요한 scenario는 candidate selection 단계로 넘긴다.

## 6. Event Segmentation

Motional Scenario는 단일 frame boolean보다 **시작/종료 구간**이 중요하다.

따라서 detector는 frame별 상태를 계산한 뒤:

- minimum duration
- inactive gap
- merge gap
- hysteresis
- pre/post roll

등을 적용하여 event range를 구성한다.

관련 module:

```text
src/ms_odd_tagging/tagger/rule_based/event_segmentation.py
src/ms_odd_tagging/tagger/rule_based/scenario_event.py
```

## 7. Lane / Topology

Lane 이해는 여러 scenario의 기반 기능이다.

관련 package:

```text
src/ms_odd_tagging/scenarios/following_lane/
src/ms_odd_tagging/ld_topology/
src/ms_odd_tagging/bev_lane_poc/
src/ms_odd_tagging/lanelet2_poc/
```

주의:

- `lanelet2_poc`는 optional PoC이며 기본 pipeline에서 활성화되지 않는다.
- physical lane assignment와 logical lane continuity를 혼동하지 않는다.
- intersection 내부/전후에서는 lane ID가 변하기 쉬우므로 lane change detector에 suppression/stability logic이 존재한다.

## 8. VLM Candidate Selection / VLM-assisted Tagging

현재 VLM path의 핵심은 **candidate generation → evidence 구성 → VLM inference → validation/merge** 순서이다.

```text
Canonical + Rule/Geometry Feature
              │
              ▼
      Candidate / Episode Selection
              │
              ▼
        Evidence Construction
     (BEV / frame context / metadata)
              │
              ▼
          VLM Inference
              │
              ▼
      Validation / Confidence Gate
              │
              ▼
        Scenario Result Merge
```

관련 package:

```text
src/ms_odd_tagging/qwen_vlm_poc/
```

현재 configuration의 VLM group은 다음과 같이 관리된다.

```text
on_intersection
starting_u_turn
traffic_light_episode
```

`traffic_light_episode`는 하나의 candidate/episode에서 traffic-light 관련 여러 최종 scenario를 판별하기 위한 group이다. 실제 label 목록은 `qwen_vlm_poc/config.py`와 `configs/scenario_catalog.csv`를 source of truth로 확인한다.

현재 config의 주요 candidate window 관련 값 예시는 다음과 같다.

```text
window_seconds = 5.0
candidate_stride_seconds = 2.5
max_bev_images = 6
acceptance_threshold = 0.72
review_threshold = 0.45
```

문서의 숫자보다 실제 config를 우선한다.

> 계산 가능한 scenario를 VLM에 먼저 맡기지 않는다. Rule/geometry로 candidate와 evidence를 만들고, 의미적 판단이 필요한 candidate에만 VLM을 적용한다.

## 9. Frame-level Tag Export / GT Workspace

Rule/VLM 결과는 평가와 reviewer에서 사용할 수 있도록 frame-level tag로 변환한다.

현재 1 FPS frame tag output:

```text
outputs/02_frame_inputs/<RECORDING_ID>/recording_frame_tags_1fps/
```

각 frame tag JSON은 scenario별 boolean 상태를 포함한다.

기본 GT reviewer는 Simplified Taxonomy GT Workspace이다.

```text
src/ms_odd_tagging/simplified_taxonomy/
```

GT Workspace는 current `recording_frame_tags_1fps` prediction을 simplified taxonomy로 mapping하여 prediction reference로 표시하고, 아직 review하지 않은 frame에는 prediction을 prefill한다. 사람이 `Save` 또는 `Save + Next`를 수행하기 전까지 해당 frame은 reviewed GT로 간주하지 않는다.

Frame Input과 frame-tag export의 1 FPS sampling frame index가 다를 수 있으므로 prediction alignment는 exact frame index를 우선하고, exact match가 없으면 timestamp 기준 nearest match를 사용한다.

## 10. Validation / GT Comparison

관련 package:

```text
src/ms_odd_tagging/validator/
src/ms_odd_tagging/gt_comparison/
```

validator는 frame/model output schema 및 semantic validation을 담당한다.

GT comparison은 사람이 작성한 GT와 자동 결과를 matching하여 metric과 report를 생성하기 위한 기능이다.

## 11. Pipeline 설계 시 유지해야 할 계약

- canonical input은 OD + LD + Ego Trajectory 통합 경로 하나로 유지한다.
- model input에 rule-derived answer를 직접 넣지 않는다.
- VLM은 전체 frame brute-force inference가 아니라 candidate/episode selection 이후 필요한 구간에만 적용한다.
- VLM candidate selection과 VLM final judgment를 구분한다.
- timestamp와 frame index alignment를 임의로 가정하지 않는다.
- unsupported semantic label을 약한 evidence로 추측하지 않는다.
- 1 FPS visualization/reviewer sampling과 full-frame rule evaluation을 구분한다.
- PoC module을 production/active pipeline과 동일하게 취급하지 않는다.
