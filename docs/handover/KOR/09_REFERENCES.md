# References

## 1. 목적

이 문서는 현재 Motional Scenario ODD Tagging repository를 이해하거나 수정할 때 확인해야 하는 source of truth를 정리한다.

## 2. Repository Entry Points

```text
README.md
pyproject.toml
src/ms_odd_tagging/pipeline.py
```

설치 후 기본 실행 command:

```text
ms-odd-tagging
```

## 3. Input / Canonicalization

```text
src/ms_odd_tagging/canonical/builder.py
src/ms_odd_tagging/canonical/odld.py
src/ms_odd_tagging/frame_inputs/builder.py
src/ms_odd_tagging/frame_inputs/frame_tags.py
```

현재 canonical schema:

```text
odld-trajectory-canonical-frame-v1
```

입력은 다음 세 파일을 함께 사용한다.

```text
annotations_OD.json
annotations_LD.json
traj_lcs.txt
```

## 4. Rule-based Tagging

Registry / configuration:

```text
src/ms_odd_tagging/tagger/rule_based/registry.py
configs/direct_scenarios.yaml
configs/scenario_catalog.csv
```

주요 detector:

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

Event handling:

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

## 6. Lane / Topology

```text
src/ms_odd_tagging/scenarios/following_lane/
src/ms_odd_tagging/ld_topology/
configs/following_lane.json
configs/ld_topology.json
```

Lane 관련 설명에서는 raw image에서 lane marking을 새로 검출하는 의미의 lane detection과 구분하기 위해, 현재 subsystem의 역할을 `lane geometry reconstruction` / `ego lane inference`로 표현한다.

## 7. VLM-assisted Tagging

```text
src/ms_odd_tagging/vlm/
```

VLM scenario group과 최종 label mapping은 다음을 함께 확인한다.

```text
src/ms_odd_tagging/vlm/config.py
configs/scenario_catalog.csv
```

현재 VLM path는 candidate / episode selection 이후 필요한 evidence에만 inference를 수행한다.

## 8. GT Review

```text
src/ms_odd_tagging/gt/
```

실행 command:

```text
ms-odd-gt
```

## 9. Full ODLD Explorer

```text
scripts/odld_explorer/generate.py
scripts/odld_explorer/explorer.py
scripts/odld_explorer/odld_explorer_common.py
```

일반적으로 `generate.py`를 사용한다.

## 10. Validation / Tests

```text
src/ms_odd_tagging/validator/frame_schema.py
tests/
.github/workflows/unit-tests.yml
```

## 11. Raw Data / Environment

```text
data/README.md
.env.example
src/ms_odd_tagging/common/config.py
```

현재 output stage path의 source of truth는 `src/ms_odd_tagging/common/config.py`이다.

## 12. 정책 / 가이드 문서

프로젝트 외부에서 함께 확인해야 하는 기준 문서는 다음과 같다.

- Motional Scenario taxonomy / scenario list
- ODD Tagging Guide v2.7.x
- 자율주행 E2E 데이터 구축 가이드라인 및 규격 정의서

정책상 scenario 정의와 repository 구현이 충돌하면 최신 공식 taxonomy/policy 문서를 우선 확인한다.

## 13. Source of Truth 우선순위

```text
1. 현재 main source code + tests
2. configs/scenario_catalog.csv / configs/direct_scenarios.yaml
3. 최신 공식 taxonomy / policy 문서
4. README.md
5. docs/handover/KOR/*
```

Documentation에 적힌 path/command가 source code와 다를 경우 current source code와 `common/config.py`, `pyproject.toml`을 기준으로 문서를 수정한다.

## 14. Handover 문서 유지 규칙

- project entry point / developer workflow 변경 → `00_OVERVIEW.md`
- 실행 command/path 변경 → `01_SETUP_AND_RUN.md`, OS별 runbook, `README.md`
- pipeline 변경 → `02_PIPELINE.md`
- schema 변경 → `03_DATA_FORMAT.md`
- scenario wiring 변경 → `04_SCENARIO_STATUS.md`
- detector logic / signal assumption 변경 → `05_ALGORITHMS.md`
- GT / metric / evaluation contract 변경 → `06_EVALUATION.md`
- unresolved implementation, validation task, future engineering direction 변경 → `07_REMAINING_WORK.md`
- source of truth / reference path 변경 → `09_REFERENCES.md`
