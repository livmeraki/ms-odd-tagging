# Pipeline

## 1. 전체 흐름

```text
Raw Recording
├── annotations_OD.json
├── annotations_LD.json
└── traj_lcs.txt
        │
        ▼
Canonicalization
        │
        ▼
outputs/01_canonical
        │
        ├──────────────────────────┐
        │                          │
        ▼                          ▼
Rule / Geometry / Temporal    Frame Input / BEV
Feature Extraction            Generation (1 FPS default)
        │                          │
        ├──────────────┐           │
        │              │           │
        ▼              ▼           │
Rule Detection    VLM Candidate    │
                  / Episode        │
        │              │           │
        │              ▼           │
        │         Evidence / BEV ◄─┘
        │              │
        │              ▼
        │         VLM Inference
        │              │
        │              ▼
        │        Validation / Merge
        │              │
        └──────┬───────┘
               ▼
      Motional Scenario Tags
               │
               ▼
 recording_frame_tags_1fps
               │
               ▼
          GT Workspace
```

VLM은 전체 frame을 직접 분류하지 않는다. Rule / geometry evidence로 candidate 또는 episode를 선택하고 필요한 구간에만 inference한다.

## 2. Canonicalization

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

역할:

- OD object state와 ego trajectory 정합
- ego pose / speed / acceleration / yaw-rate 구성
- recording-level LD geometry 정규화
- `ld_feature_store` 구성
- frame별 nearby LD reference 구성

Schema:

```text
odld-trajectory-canonical-frame-v1
```

## 3. Frame Input / BEV

```text
src/ms_odd_tagging/frame_inputs/builder.py
```

기본 sampling은 timestamp 기준 1 FPS이다.

```text
frame_XXXXXX/
├── frame.json
└── bev.png
```

Frame Input은 tagging, GT review, VLM evidence에서 공유한다.

## 4. Feature Extraction

```text
src/ms_odd_tagging/features/ego_motion.py
src/ms_odd_tagging/features/object_relations.py
src/ms_odd_tagging/features/road_feature_relations.py
src/ms_odd_tagging/features/pedestrian_crosswalk_relations.py
src/ms_odd_tagging/features/object_path_crossing_relations.py
src/ms_odd_tagging/features/traffic_relations.py
src/ms_odd_tagging/features/traffic_light_context.py
```

## 5. Rule Detection

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

시간 구간이 필요한 결과는 `ScenarioEvent`로 구성한다.

## 6. Event Segmentation

```text
src/ms_odd_tagging/tagger/rule_based/event_segmentation.py
src/ms_odd_tagging/tagger/rule_based/scenario_event.py
```

Scenario에 따라 minimum duration, inactive gap, merge gap, hysteresis, pre/post roll을 사용한다.

## 7. Lane / Topology

```text
src/ms_odd_tagging/scenarios/following_lane/
src/ms_odd_tagging/ld_topology/
configs/following_lane.json
configs/ld_topology.json
```

Lane/topology 결과는 lane relation, lane-change/turn 판단과 VLM evidence에 사용된다.

## 8. VLM

```text
src/ms_odd_tagging/vlm/
```

```text
Canonical + Rule/Geometry Feature
              │
              ▼
      Candidate / Episode
              │
              ▼
        Evidence / BEV
              │
              ▼
          VLM Inference
              │
              ▼
       Validation / Merge
```

VLM group:

```text
on_intersection
starting_u_turn
traffic_light_episode
```

Source of truth:

```text
src/ms_odd_tagging/vlm/config.py
configs/scenario_catalog.csv
```

실행:

```text
ms-odd-vlm
```

## 9. Frame Tags

```text
outputs/02_frame_inputs/<RECORDING_ID>/recording_frame_tags_1fps/
```

각 JSON은 해당 frame의 Motional Scenario boolean 상태를 포함한다.

## 10. GT Workspace

```text
src/ms_odd_tagging/gt/
```

실행:

```text
ms-odd-gt
```

GT Workspace는 sampled frame의 BEV와 prediction을 함께 보여주고 사람이 최종 GT를 검토·저장한다.

## 11. ODLD Explorer

```text
scripts/odld_explorer/generate.py
scripts/odld_explorer/explorer.py
scripts/odld_explorer/odld_explorer_common.py
scripts/odld_explorer/generate_dataset_explorers.py
```

일반 실행은 `generate.py`만 사용한다. `explorer.py`와 두 support module은 generator가 사용하는 내부 구현이다.

## 12. 핵심 계약

- canonical input은 OD + LD + Ego Trajectory를 함께 사용한다.
- `frame.json`에 정답 label을 직접 삽입하지 않는다.
- VLM은 candidate / episode selection 이후 필요한 구간에 적용한다.
- frame index와 timestamp alignment를 명시적으로 처리한다.
- unsupported semantic label은 약한 evidence만으로 추측하지 않는다.
- rule event 계산과 1 FPS reviewer sampling을 구분한다.
