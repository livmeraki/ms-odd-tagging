# References

## 1. 목적

이 문서는 Motional Scenario ODD Tagging Automation 프로젝트를 이해하거나 수정할 때 우선 확인해야 하는 repository 내부 자료와 외부/정책성 참고 문서를 정리한다.

## 2. Repository Entry Points

### Root README

```text
README.md
```

다음 내용을 가장 먼저 확인한다.

- repository layout
- install command
- `run_pipeline.py` 사용법
- output folder convention
- frame input sampling policy
- GT reviewer
- important contracts

### Main Pipeline

```text
run_pipeline.py
src/ms_odd_tagging/pipeline.py
```

현재 canonical → frame-input generation의 공식 entry point이다.

## 3. Input / Canonicalization

```text
src/ms_odd_tagging/input_generator/canonical.py
src/ms_odd_tagging/input_generator/canonical_odld.py
src/ms_odd_tagging/input_generator/frame_input.py
src/ms_odd_tagging/input_generator/frame_input_revised.py
```

OD-only와 OD+LD canonicalization의 차이를 확인할 때 우선 참고한다.

## 4. Rule-based Tagging

### Registry / Config

```text
src/ms_odd_tagging/tagger/rule_based/registry.py
configs/direct_scenarios.yaml
```

현재 scenario wiring, threshold, detector version, provenance의 source of truth에 가장 가깝다.

### Detectors

```text
src/ms_odd_tagging/tagger/rule_based/dynamics.py
src/ms_odd_tagging/tagger/rule_based/turns.py
src/ms_odd_tagging/tagger/rule_based/lane_changes.py
src/ms_odd_tagging/tagger/rule_based/crosswalks.py
src/ms_odd_tagging/tagger/rule_based/object_interactions.py
src/ms_odd_tagging/tagger/rule_based/pedestrian_crosswalks.py
src/ms_odd_tagging/tagger/rule_based/object_path_crossings.py
src/ms_odd_tagging/tagger/rule_based/traffic_interactions.py
```

### Event handling

```text
src/ms_odd_tagging/tagger/rule_based/event_segmentation.py
src/ms_odd_tagging/tagger/rule_based/scenario_event.py
```

## 5. Feature Extraction

```text
src/ms_odd_tagging/features/ego_motion.py
src/ms_odd_tagging/features/object_relations.py
src/ms_odd_tagging/features/road_feature_relations.py
src/ms_odd_tagging/features/pedestrian_crosswalk_relations.py
src/ms_odd_tagging/features/object_path_crossing_relations.py
src/ms_odd_tagging/features/traffic_relations.py
src/ms_odd_tagging/features/traffic_light_context.py
```

새 detector를 구현하기 전에 이미 필요한 evidence가 feature layer에 존재하는지 확인한다.

## 6. Lane / Topology

```text
src/ms_odd_tagging/scenarios/following_lane/
src/ms_odd_tagging/ld_topology/
src/ms_odd_tagging/bev_lane_poc/
src/ms_odd_tagging/lanelet2_poc/
```

기존 설명 문서:

```text
docs/following_lane.md
docs/lanelet2_poc.md
docs/phase2_lane_change.md
```

Lanelet2 기능은 optional PoC임을 주의한다.

## 7. Existing Development Documents

```text
docs/audit.md
docs/phase1_rule_based.md
docs/phase2_lane_change.md
docs/following_lane.md
docs/lanelet2_poc.md
brainstorm.md
```

`audit.md`는 exploratory predecessor에서 현재 repository로 migration된 provenance를 확인하는 데 중요하다.

`brainstorm.md`는 과거 아이디어와 실험 기록이 섞여 있으므로 현재 behavior의 source of truth로 직접 사용하지 말고 개발 이력 확인용으로 사용한다.

## 8. GT / Evaluation

```text
src/ms_odd_tagging/gt_comparison/
src/ms_odd_tagging/validator/
data/02_gt/
```

GT authoring과 metric 재현 시 해당 code와 실제 GT version을 함께 고정한다.

## 9. Visualization

```text
src/ms_odd_tagging/visualization/scenario_explorer.py
scripts/odld_explorer/
```

Rule 결과를 수정할 때 숫자 output만 확인하지 말고 visualization으로 geometry와 temporal behavior를 함께 검토한다.

## 10. VLM / Model-based

```text
src/ms_odd_tagging/tagger/model_based/
src/ms_odd_tagging/qwen_vlm_poc/
prompts/
```

Qwen VLM PoC package 주요 구성:

- `candidates.py`
- `evidence.py`
- `client.py`
- `validation.py`
- `merging.py`
- `visualization.py`

VLM 관련 코드는 active deterministic rule pipeline과 분리해 이해한다.

## 11. 정책 / 가이드 문서

프로젝트에서 참고한 주요 문서:

### Motional Scenario taxonomy / scenario list

Dynamics, Interaction, Zone, Maneuver, Behavior 등 Motional Scenario label 정의를 확인하기 위한 자료.

### ODD Tagging Guide v2.7.x

기존 ODD Tagging의 class structure, Static/Dynamic ODD 작업 단위 및 annotation 기준을 확인하는 자료.

### 자율주행 E2E 데이터 구축 가이드라인 및 규격 정의서

자율주행 E2E 데이터의 수집, 가공, 정합, 라벨링, 시나리오/이벤트 개념을 참고하기 위한 자료.

> 위 정책 문서들은 회사 내부 또는 별도 공유 위치에 존재할 수 있으므로 repository에 원문을 무단 복사하지 말고 공식 저장 위치를 인수인계 시 함께 전달한다.

## 12. Raw Data 정보

대표 입력:

```text
annotations_OD.json
annotations_LD.json
traj_lcs.txt
```

데이터 형식은 `03_DATA_FORMAT.md`에서 요약하며, 실제 raw data policy와 storage path는 다음 문서/설정을 함께 확인한다.

```text
data/README.md
.env.example
src/ms_odd_tagging/common/config.py
```

## 13. Source of Truth 우선순위

정보가 충돌할 경우 다음 우선순위를 권장한다.

```text
1. 현재 실행되는 source code + tests
2. configs/direct_scenarios.yaml
3. root README.md
4. docs/handover/KOR/*
5. 기존 phase/PoC 문서
6. brainstorm / 과거 발표 자료
```

정책상 scenario 정의 자체가 충돌하는 경우에는 repository보다 **최신 공식 taxonomy/policy 문서**를 먼저 확인하고 code를 수정한다.

## 14. Handover 문서 유지 규칙

새 기능을 추가하거나 구조를 바꿀 때 최소 다음 문서를 함께 갱신한다.

- pipeline 변경 → `02_PIPELINE.md`
- schema 변경 → `03_DATA_FORMAT.md`
- scenario wiring 변경 → `04_SCENARIO_STATUS.md`
- detector logic 변경 → `05_ALGORITHMS.md`
- metric 변경 → `06_EVALUATION.md`
- known bug 추가/해결 → `07_KNOWN_ISSUES.md`
- backlog 변경 → `08_NEXT_STEPS.md`
