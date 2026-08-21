# Data Format and Interface Contracts

## 1. 목적과 적용 범위

이 문서는 Motional Scenario tagging pipeline이 사용하는 raw OD, raw LD, ego trajectory, canonical recording, sampled frame input, rule event, 1 FPS frame tag, VLM result 및 manual GT의 데이터 계약을 정의한다.

여기에 제시된 JSON은 이해를 위한 대표 구조이다. 정확한 현재 field와 validation 조건의 source of truth는 각 writer/validator 코드이다.

## 2. 공통 표기와 단위

| 표기 | 의미 |
|---|---|
| `frame_index` | 원본 annotation/canonical source frame index |
| `timestamp_unix_s` | Unix timestamp, 초 |
| `time_since_start_s` | recording 시작 기준 경과 시간, 초 |
| `LCS` | recording이 공유하는 local coordinate system |
| `ego-relative` | 현재 ego pose와 heading 기준 좌표 |
| `m` | 거리/위치 단위 meter |
| `mps` | 속도 m/s |
| `mps2` | 가속도 m/s² |
| `rad` | angle radian |
| `radps` | yaw rate rad/s |

1 FPS output의 파일 번호는 “몇 번째 1 FPS sample인가”가 아니라 선택된 original `frame_index`이다.

## 3. Raw recording directory 계약

```text
<MS_ODD_DATA_ROOT>/01_raw/<RECORDING_ID>/
├── annotations_OD.json
├── annotations_LD.json
└── traj_lcs.txt
```

세 파일 모두 필요하다. 파일명이 다르면 main pipeline은 자동으로 발견하지 않는다.

## 4. Raw OD Annotation

OD는 scene-level, object-centric 구조를 사용한다.

대표 구조:

```text
root
├── scene
│   ├── id
│   ├── name
│   └── frameCount
└── objects[]
    ├── objectId
    ├── className
    ├── staticAttributes / attributes
    ├── visible_frames
    └── frames / bbox3d
```

주요 소비 정보:

| 정보 | downstream 사용 |
|---|---|
| `objectId` | track/object identity |
| `className` | vehicle, pedestrian, bike, motorcycle, traffic light 등 분류 |
| `frameIndex` | trajectory row와의 직접 정합 |
| `bbox3d` position/dimension/orientation | ego-relative 위치, 거리, heading, footprint |
| frame observation | object visibility와 derivative 계산 |
| camera metadata | camera별 visibility 관련 별도 PoC에서 사용 가능 |

중요 계약:

- Dynamic object geometry는 해당 source frame에 usable `bbox3d`가 있을 때 사용한다.
- 관측되지 않은 dynamic state를 일반적으로 자동 forward-fill하지 않는다.
- observation gap이 큰 구간에서는 velocity derivative를 생략할 수 있다.
- traffic light object의 존재와 traffic-light state는 다른 정보이다. source에 state가 없다면 state를 생성하지 않는다.

## 5. Ego Trajectory — `traj_lcs.txt`

기본 row:

```text
timestamp tx ty tz qx qy qz qw
```

| Column | Type | 의미 |
|---|---|---|
| `timestamp` | float | Unix timestamp 또는 source timestamp, 초 |
| `tx ty tz` | float | ego position in LCS, meter |
| `qx qy qz qw` | float | ego orientation quaternion |

Canonicalizer는 trajectory에서 다음 derived field를 만든다.

- heading/yaw
- velocity vector
- speed
- acceleration
- yaw rate
- recording 시작 기준 시간

정합 조건:

- row 수는 OD와 LD의 `scene.frameCount`와 같아야 한다.
- timestamp는 strictly increasing이어야 한다.
- trajectory row `i`는 OD source frame `i`와 직접 대응한다.
- detector 내부에서 별도 offset을 임의로 추가하면 안 된다.

## 6. Raw LD Annotation

LD는 recording-level road/lane geometry이다.

대표 구조:

```text
root
└── scene
    └── frameCount
lanes
├── points[]
├── lines[]
├── roadBoundaries[]
├── lanes[]
└── roadmarks / topology-related features
```

Canonicalizer가 사용하는 주요 개념:

- point id와 LCS 위치
- lane line/road-boundary의 ordered point reference
- physical lane과 boundary relation
- lane attributes와 topology
- crosswalk/stopline 등 roadmark
- intersection 관련 geometry

중요 계약:

- LD는 frame별 timestamp annotation으로 취급하지 않는다.
- 완전한 geometry는 canonical `ld_feature_store`에 recording당 한 번 저장한다.
- 각 frame은 ego 주변에서 필요한 feature id와 요약만 참조한다.
- missing point reference, duplicate id, invalid geometry는 LD quality에 기록한다.

## 7. Raw data alignment 계약

```text
OD frameIndex i ─────────────┐
Trajectory row i ────────────┼─> Canonical frame i
Recording-level LD geometry ─┘    (ego pose i로 spatial query)
```

강제 조건:

```text
OD scene.frameCount
= LD scene.frameCount
= len(trajectory rows)
= len(canonical.frames)
```

OD/LD scene id 또는 scene name 불일치는 warning으로 남길 수 있지만 frame-count 불일치는 fatal error이다.

## 8. Canonical recording

### 파일명

```text
<RECORDING_ID>_canonical_odld_frames.json
```

### Schema

```text
odld-trajectory-canonical-frame-v1
```

### 대표 top-level 구조

```json
{
  "schema_version": "odld-trajectory-canonical-frame-v1",
  "recording_id": "<RECORDING_ID>",
  "source": {
    "od_annotations": ".../annotations_OD.json",
    "ld_annotations": ".../annotations_LD.json",
    "trajectory": ".../traj_lcs.txt",
    "alignment": {
      "od_to_trajectory": "OD frameIndex maps directly to trajectory row index",
      "ld_temporal_model": "recording_static_map_spatially_queried_at_each_ego_pose",
      "scene_id_match": true,
      "scene_name_match": true
    },
    "coordinate_system": {
      "od": "LCS",
      "trajectory": "LCS",
      "ld": "inferred_shared_lcs",
      "ld_explicitly_declared": false
    }
  },
  "recording": {},
  "scenario_taxonomy": [],
  "ld_configuration": {},
  "ld_feature_store": {},
  "data_quality": {},
  "frames": []
}
```

### Top-level field 계약

| Field | Type | 의미 |
|---|---|---|
| `schema_version` | string | canonical schema version |
| `recording_id` | string | recording directory/id |
| `source` | object | 원본 파일과 alignment/coordinate metadata |
| `recording` | object | frame count, 시작/종료 시간, duration, nominal frame rate |
| `scenario_taxonomy` | array[string] | canonical이 전달하는 scenario 이름 |
| `ld_configuration` | object | nearby radius, geometry storage 방식 |
| `ld_feature_store` | object | recording-wide normalized LD geometry |
| `data_quality` | object | alignment, object, LD quality |
| `frames` | array[object] | source frame 순서의 full-rate frame state |

### `recording` field

```text
frame_count
start_timestamp_unix_s
end_timestamp_unix_s
duration_s
median_frame_interval_s
nominal_frame_rate_hz
```

### Canonical frame 구조

```json
{
  "frame_index": 0,
  "timestamp_unix_s": 0.0,
  "time_since_start_s": 0.0,
  "ego": {
    "position_lcs_m": [0.0, 0.0, 0.0],
    "orientation_lcs_quaternion_xyzw": [0.0, 0.0, 0.0, 1.0],
    "heading_lcs_rad": 0.0,
    "velocity_lcs_mps": [0.0, 0.0, 0.0],
    "speed_mps": 0.0,
    "acceleration_mps2": 0.0,
    "yaw_rate_radps": 0.0
  },
  "objects": [],
  "scenario_signals": {},
  "interaction_candidates": [],
  "ld": {}
}
```

### Canonical frame field 계약

| Field | Type | 의미 |
|---|---|---|
| `frame_index` | int | original source frame index |
| `timestamp_unix_s` | float | trajectory timestamp |
| `time_since_start_s` | float | recording-relative time |
| `ego` | object | pose 및 motion derivatives |
| `objects` | array | 해당 frame의 normalized OD states |
| `scenario_signals` | object | basic derived evidence |
| `interaction_candidates` | array | object interaction candidate |
| `ld` | object | nearby LD feature reference 및 ego-relative summary |

### LD 저장 계약

`ld_feature_store`에는 complete normalized geometry를 한 번 저장한다. Frame-level `ld`는 일반적으로 다음 정보를 담는다.

- `available`
- nearby feature ids
- ego-relative distance/side/heading summary
- optional clipped geometry

BEV/geometry consumer는 recording-level `ld_feature_store`와 frame-level `ld`를 함께 사용해야 한다.

## 9. Canonical manifest

파일:

```text
01_canonical/manifest.json
```

Schema:

```text
odld-trajectory-canonical-manifest-v1
```

대표 구조:

```json
{
  "schema_version": "odld-trajectory-canonical-manifest-v1",
  "scenario_taxonomy": [],
  "ld_configuration": {},
  "recordings": [
    {
      "recording_id": "...",
      "path": "<RECORDING_ID>_canonical_odld_frames.json",
      "frame_count": 0,
      "duration_s": 0.0,
      "nominal_frame_rate_hz": 10.0,
      "ld_quality": {}
    }
  ]
}
```

## 10. Sampled `frame.json`

### 위치

```text
02_frame_inputs/<RECORDING_ID>/frame_<SOURCE_FRAME_INDEX>/frame.json
```

### Schema

```text
odld-dynamic-frame-model-input-v1
```

### 필수 top-level field

```text
schema_version
recording_id
frame_id
source_canonical_file
frame_index
time_since_start_s
taxonomy
bev
ego
scenario_signals
object_counts
objects
interaction_candidates
ld
data_quality
data_notes
```

현재 writer는 `timestamp_unix_s`와 `generation` 정보도 기록한다.

### 대표 구조

```json
{
  "schema_version": "odld-dynamic-frame-model-input-v1",
  "recording_id": "<RECORDING_ID>",
  "frame_id": "<RECORDING_ID>:frame-000120",
  "source_canonical_file": "outputs/01_canonical/...",
  "frame_index": 120,
  "timestamp_unix_s": 0.0,
  "time_since_start_s": 12.0,
  "taxonomy": [],
  "bev": {
    "schema_version": "odld-per-frame-bev-v1",
    "frame_index": 120,
    "path": "bev.png",
    "format": "png",
    "audience": "model",
    "renderer": "explorer-aligned-revised-v1",
    "orientation": "ego-heading-up"
  },
  "ego": {},
  "scenario_signals": {},
  "object_counts": {},
  "objects": [],
  "interaction_candidates": [],
  "ld": {},
  "data_quality": {},
  "data_notes": [],
  "generation": {}
}
```

### Field 계약

| Field | Type | 계약 |
|---|---|---|
| `frame_id` | string | `<recording_id>:frame-<frame_index:06d>` |
| `source_canonical_file` | string | portable path, Windows backslash를 저장하지 않음 |
| `frame_index` | int | BEV와 동일한 source index |
| `taxonomy` | array | canonical taxonomy 전달 |
| `bev.frame_index` | int | top-level `frame_index`와 같아야 함 |
| `bev.path` | string | `frame.json` 기준 같은 directory의 PNG |
| `ego` | object | canonical frame ego |
| `objects` | array | 거리순 정렬 후 `max_objects`까지만 compact export |
| `ld` | object | canonical frame의 LD context |
| `data_quality.objects_truncated` | bool | object 제한 적용 여부 |
| `generation.fingerprint` | string | resume/up-to-date 판단 |

Validator:

```bash
ms-odd-validate \
  --frame-input-dir <MS_ODD_OUTPUT_ROOT>/02_frame_inputs \
  <RECORDING_ID>
```

Validator는 schema version, 필수 key, frame id/index, portable source path, BEV format/path/frame index, ego/object type을 검사한다.

## 11. `bev.png` 계약

위치:

```text
frame_<SOURCE_FRAME_INDEX>/bev.png
```

계약:

- PNG format
- `frame.json`과 동일 frame
- ego-centric
- ego heading up
- current renderer: `explorer-aligned-revised-v1`
- configured extent와 centered extent metadata는 `frame.json.bev`에 기록
- default size는 builder 기준 900 × 1200 px
- default configured extent는 left 45 m, right 45 m, behind 25 m, ahead 95 m

BEV는 sampled visual artifact이고 rule detector의 full-rate temporal input을 대체하지 않는다.

## 12. `gt_reference.json` 계약

위치:

```text
frame_<SOURCE_FRAME_INDEX>/gt_reference.json
```

이 파일은 해당 frame에서 rule/lane이 직접 도출한 reference와 active event evidence를 담는다.

대표 field:

```text
directly_derived_labels
rule_based_reference.active_labels
rule_based_reference.active_events
rule_based_reference.lane_tracker
```

`gt_reference.json`은 debugging/review reference이다. `frame.json`과 분리되어 있으며 model input으로 전달해 label leakage를 만들면 안 된다.

## 13. Rule event JSON

파일:

```text
recording_rule_events.json
```

Schema:

```text
rule-based-scenario-events-v1
```

### `ScenarioEvent` 계약

| Field | Type | 의미 |
|---|---|---|
| `scenario` | string | scenario name |
| `start_frame` | int | inclusive start source frame |
| `end_frame` | int | inclusive end source frame |
| `start_timestamp_s` | float | event start time |
| `end_timestamp_s` | float | event end time |
| `duration_s` | float | event duration |
| `confidence` | float | 기본 1.0 |
| `source` | string | 기본 `rule_based` |
| `detector_version` | string | detector implementation version |
| `evidence` | object | 판단 근거 |

Timestamp가 recording-relative인지 source absolute인지 detector마다 임의로 바꾸면 안 된다. 현재 event pipeline의 `*_timestamp_s`는 canonical frame의 temporal convention을 따라야 한다.

## 14. 1 FPS frame-tag JSON

### Directory

```text
recording_frame_tags_1fps/
├── manifest.json
└── frame_<SOURCE_FRAME_INDEX>.json
```

Frame schema:

```text
motional-scenario-frame-tags-1fps-v1
```

대표 구조:

```json
{
  "schema_version": "motional-scenario-frame-tags-1fps-v1",
  "recording_id": "<RECORDING_ID>",
  "frame": 120,
  "timestamp_s": 12.0,
  "source_event_json": "recording_rule_events.json",
  "rule_config_version": "...",
  "sample_rate_hz": 1.0,
  "sampling": "nearest_original_frame_to_integer_second",
  "tags": {
    "motional_scenarios": {
      "stationary": false,
      "changing_lane": true
    }
  }
}
```

Tag가 true인 조건:

```text
event.start_frame <= sampled source frame <= event.end_frame
```

Manifest schema:

```text
motional-scenario-frame-tags-1fps-manifest-v1
```

Manifest는 scenario 목록, scenario count, sampled frame count, 각 frame file path를 기록한다.

## 15. Frame-input manifest

파일:

```text
02_frame_inputs/manifest.json
```

Schema:

```text
odld-per-frame-input-manifest-v1
```

대표 field:

```text
schema_version
renderer
orientation
frames_per_second
existing_output_policy
recordings[]
```

Recording summary:

```text
recording_id
canonical_frame_count
generated_frame_count
generated_this_run
skipped_up_to_date
frames_per_second
analysis_cache_hit
recording_frame_tags
frames[]
```

## 16. VLM candidate/run/result 계약

VLM group은 다음 중 하나이다.

```text
on_intersection
starting_u_turn
traffic_light_episode
```

각 group이 생성할 수 있는 실제 label 목록은 `src/ms_odd_tagging/vlm/config.py`와 `configs/scenario_catalog.csv`가 source of truth이다.

Run manifest schema:

```text
qwen-vlm-poc-run-manifest-v1
```

대표 구조:

```json
{
  "schema_version": "qwen-vlm-poc-run-manifest-v1",
  "config": {},
  "candidate_bundles": [],
  "raw_results": [],
  "validation": [
    {
      "candidate_id": "...",
      "accepted": true,
      "review_required": false,
      "reasons": [],
      "decision": {},
      "decisions": []
    }
  ],
  "events": [],
  "review_bundles": []
}
```

Accepted decision은 다음 경로에 event array로 기록한다.

```text
events/<SCENARIO_GROUP>/<RECORDING_ID>_events.json
```

Inference failure/timeout은 accepted=false, review_required=true로 기록할 수 있다.

주의: VLM event file은 현재 rule event/frame tag file에 자동 병합되는 동일 schema의 final output이 아니다. 평가나 납품용으로 합칠 때 merge 정책과 provenance를 별도로 보존해야 한다.

## 17. Manual GT 계약

파일:

```text
<GT_ROOT>/<RECORDING_ID>_manual_gt.json
```

Schema:

```text
simplified-manual-gt-v1
```

대표 구조:

```json
{
  "schema_version": "simplified-manual-gt-v1",
  "recording_id": "<RECORDING_ID>",
  "sampling_hz": 1.0,
  "gt_finished": false,
  "frames": [
    {
      "frame_index": 120,
      "timestamp": 12.0,
      "gt": {},
      "reviewed": true
    }
  ]
}
```

Simplified GT tag model:

```text
ego_motion
├── state: stationary | moving | starting | stopping | unknown
└── speed_band: low | medium | high | unknown | null

ego_maneuver
├── type: lane_keeping | lane_change | turn | u_turn | unknown
└── direction: left | right | straight | null

traffic_relation
├── lead: present | absent | unknown
└── trail: present | absent | unknown

road_context
├── intersection: yes | no | unknown
├── traffic_light_intersection: yes | no | unknown
├── traffic_light_relevant: yes | no | unknown
└── on_stopline_crosswalk: yes | no | unknown

interaction_tags[]
source_scenarios[]
unmapped_scenarios[]
```

Prediction은 prefill/reference일 뿐이며 `reviewed: true`인 사람 검토 결과만 GT로 취급한다.

## 18. Runtime report 계약

파일:

```text
runtime_logs/pipeline_<YYYYMMDD_HHMMSS>.json
```

대표 구조:

```json
{
  "recorded_at": "...",
  "recordings": [],
  "stages": [
    {
      "stage": 1,
      "name": "canonicalization",
      "module": "ms_odd_tagging.canonical.builder",
      "elapsed_seconds": 0.0,
      "succeeded": 0,
      "failed": 0,
      "recordings": []
    }
  ],
  "failures": [],
  "total_elapsed_seconds": 0.0,
  "average_pipeline_elapsed_seconds_per_successful_recording": 0.0,
  "average_pipeline_recording_count": 0
}
```

재현성 기록에는 runtime report 외에도 commit SHA, config version, GT version, recording list와 sampling option을 함께 남겨야 한다.

## 19. Interface 변경 규칙

다음 변경은 breaking interface change로 취급한다.

- raw required filename 변경
- frame-index/timestamp alignment 변경
- coordinate system 또는 unit 변경
- schema version 또는 필수 field 변경
- output directory/file naming 변경
- event boundary convention 변경
- 1 FPS sampling 알고리즘 변경
- `frame.json`에 label/GT 추가
- VLM event merge 정책 변경
- GT taxonomy/schema 변경

이 경우 최소한 다음을 함께 수정한다.

1. writer
2. validator/reader
3. unit/integration test
4. `02_PIPELINE.md`
5. 이 문서
6. setup/run 예시
7. 필요 시 migration 또는 backward-compatibility note

## 20. Source of truth

| Data contract | Source |
|---|---|
| Canonical | `src/ms_odd_tagging/canonical/odld.py` |
| Frame input | `src/ms_odd_tagging/frame_inputs/model_input.py` |
| Frame output layout | `src/ms_odd_tagging/frame_inputs/_generator.py` |
| Frame validation | `src/ms_odd_tagging/validator/frame_schema.py` |
| Scenario event | `src/ms_odd_tagging/tagger/rule_based/scenario_event.py` |
| 1 FPS frame tags | `src/ms_odd_tagging/frame_inputs/frame_tags.py` |
| Following lane | `src/ms_odd_tagging/scenarios/following_lane/pipeline.py` |
| LD topology | `src/ms_odd_tagging/ld_topology/cli.py` |
| VLM run/result | `src/ms_odd_tagging/vlm/cli.py` |
| Manual GT | `src/ms_odd_tagging/gt/schema.py`, `gt/workspace.py` |
