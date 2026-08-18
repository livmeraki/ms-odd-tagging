# Pipeline

## 1. 전체 흐름

현재 repository는 raw OD/LD annotation과 ego trajectory를 공통 canonical representation으로 정합한 뒤, rule-based tagging과 frame-level model input/BEV 생성을 분리하여 수행한다.

```text
Raw Recording
├── annotations_OD.json
├── annotations_LD.json
└── traj_lcs.txt
        │
        ▼
OD+LD Canonicalization
        │
        ▼
outputs/01_canonical
        │
        ├─────────────────────────────┐
        │                             │
        ▼                             ▼
Rule-based feature extraction   Frame input / BEV generation
+ scenario detectors            (1 FPS default)
        │                             │
        ▼                             ▼
ScenarioEvent                   frame.json + bev.png
        │                             │
        │                       Optional VLM / PoC
        └──────────────┬──────────────┘
                       ▼
                Tagging / Validation
                       │
                       ▼
                  GT Comparison
```

## 2. Stage 1 — Canonicalization

관련 module:

```text
src/ms_odd_tagging/input_generator/canonical.py
src/ms_odd_tagging/input_generator/canonical_odld.py
```

지원되는 canonical path는 OD+LD 하나이다. `canonical.py`는 별도 mode가 아니라 `canonical_odld.py`가 재사용하는 내부 OD/trajectory core로만 유지한다.

Canonicalization은 raw OD, LD, trajectory를 frame 기준으로 동기화하고 LD feature store 및 frame-level nearby feature reference를 구성한다.

주요 contract:

- OD schema: `od-trajectory-canonical-frame-v1`
- OD+LD schema: `odld-trajectory-canonical-frame-v1`
- 숫자 0은 valid data이며 `null`로 변환하면 안 된다.
- OD+LD BEV에는 `ld_feature_store`와 frame-level `ld.nearby_feature_ids`가 모두 필요하다.

## 3. Stage 2 — Frame Input / BEV

관련 module:

```text
src/ms_odd_tagging/input_generator/frame_input.py
src/ms_odd_tagging/input_generator/frame_input_revised.py
```

기본 pipeline은 real timestamp 기준 1 FPS로 frame을 선택해 각 timestamp마다 독립적인:

- `frame.json`
- `bev.png`

를 생성한다.

과거의 5초 window + start/middle/end keyframe 방식은 legacy helper로 남아 있으나 현재 frame reviewer와 active input pipeline의 기본 방식은 아니다.

`frame_input_revised.py`는 additive experiment이며 기존 generator를 대체하지 않는다.

## 4. Rule-based Feature Extraction

registry는 canonical frame sequence를 받아 scenario detector가 공통으로 사용할 feature를 생성한다.

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

각 detector가 raw JSON 구조를 중복 해석하지 않고, 먼저 계산된 공통 relation/feature를 재사용하는 방향으로 구성되어 있다.

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

## 7. Lane / Topology 관련 별도 기능

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

## 8. Optional VLM Layer

현재 repository에는 두 종류의 model-related code가 존재한다.

1. 일반 model-based tagger
2. `qwen_vlm_poc` package

`qwen_vlm_poc`에는 candidate generation, evidence construction, prompt, validation, merging, visualization이 분리되어 있다.

권장 원칙은 다음과 같다.

> 계산 가능한 scenario를 VLM에 먼저 맡기지 않는다. Rule/geometry로 candidate와 evidence를 만들고, 의미적 판단이 필요한 경우에만 VLM을 사용한다.

## 9. Validation / GT Comparison

관련 package:

```text
src/ms_odd_tagging/validator/
src/ms_odd_tagging/gt_comparison/
```

validator는 frame/model output schema 및 semantic validation을 담당한다.

GT comparison은 사람이 작성한 GT와 자동 결과를 matching하여 metric과 report를 생성하기 위한 기능이다.

## 10. Pipeline 설계 시 유지해야 할 계약

- model input에 rule-derived answer를 직접 넣지 않는다.
- timestamp와 frame index alignment를 임의로 가정하지 않고 canonicalization에서 해결한다.
- unsupported semantic label을 약한 evidence로 추측하지 않는다.
- 1 FPS visualization sampling과 full-frame rule evaluation을 구분한다.
- PoC module을 production/active pipeline과 동일하게 취급하지 않는다.
