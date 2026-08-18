# Scenario Status

## 1. Source of Truth

Scenario별 자동화 방식과 현재 상태는 하나의 catalog에서 관리한다.

```text
configs/scenario_catalog.csv
```

이 파일이 다음 정보의 **single source of truth**이다.

- 공식/현재 사용 scenario name
- taxonomy category
- 자동 판별 방식 (`rule`, `vlm`)
- 현재 구현 상태
- VLM candidate group
- repository-specific extension 여부

따라서 scenario가 Rule-based인지 VLM inferred인지 확인할 때 별도의 문서 목록을 찾지 말고 `scenario_catalog.csv`를 먼저 확인한다.

## 2. Catalog Column

| Column | 의미 |
|---|---|
| `name` | scenario label |
| `category` | `dynamics`, `interaction`, `zone`, `maneuver`, `behavior` |
| `methods` | 자동 판별 방식. `rule`, `vlm`, `rule+vlm`, 또는 빈 값 |
| `status` | 현재 구현/검증 상태 |
| `taxonomy_status` | reference taxonomy 포함 여부 |
| `vlm_candidate_group` | VLM candidate/inference에서 사용하는 group |
| `notes` | 예외 또는 추가 설명 |

`methods`가 빈 값인 경우 현재 repository에서 자동 tagging path가 연결되지 않은 scenario이다.

## 3. Method 의미

### `rule`

Deterministic rule / geometry / temporal logic으로 판별한다.

예:

- `stationary`
- `changing_lane`
- `traversing_crosswalk`
- `near_multiple_pedestrians`

Rule threshold와 detector parameter는 `configs/direct_scenarios.yaml`에서 관리한다.

### `vlm`

VLM candidate generation 및 inference를 통해 판별하는 scenario이다.

예:

- `on_intersection`
- `starting_u_turn`
- traffic-light 관련 scenario

VLM 관련 실행 code는 다음 package를 확인한다.

```text
src/ms_odd_tagging/qwen_vlm_poc/
```

### `rule+vlm`

동일 scenario에 Rule과 VLM path가 모두 존재할 수 있다.

현재 대표적인 예는:

```text
waiting_for_pedestrian_to_cross
```

이다. 따라서 scenario를 단순히 "Rule 또는 VLM" 중 하나로 강제 분류하지 않고 `methods`를 복수 값으로 저장한다.

## 4. Status 의미

| Status | 의미 |
|---|---|
| `implemented` | active deterministic implementation이 존재 |
| `poc_calibration` | code는 존재하지만 추가 dataset calibration / validation 필요 |
| `vlm_poc` | VLM PoC path에서 다루는 scenario |
| `unsupported` | 현재 자동 tagging path가 연결되지 않음 |

> `implemented`는 production-level validation 완료와 같은 의미가 아니다. 실제 신뢰 수준은 evaluation 결과와 `07_KNOWN_ISSUES.md`를 함께 확인한다.

## 5. 현재 Catalog 범위

현재 catalog는 reference Motional Scenario list를 기반으로 하며, 현재 repository가 실제로 사용하는 추가 label도 함께 기록한다.

현재 repository의 rule detector에는 reference list에 없는 다음 label이 존재하므로 `taxonomy_status=repo_extension`으로 명시한다.

- `near_multiple_motorcycle`
- `crossed_by_motorcycle`

이렇게 reference taxonomy와 현재 code 사이의 차이를 숨기지 않고 catalog에서 명시적으로 관리한다.

## 6. Code와 Catalog 관계

```text
configs/scenario_catalog.csv
          │
          ├── Rule method metadata
          │     └── rule registry와 consistency test
          │
          ├── VLM method metadata
          │     └── qwen_vlm_poc/config.py
          │         ├── SCENARIOS
          │         └── TRAFFIC_LIGHT_LABELS
          │
          └── Handover documentation
```

VLM의 `SCENARIOS`와 `TRAFFIC_LIGHT_LABELS`는 catalog에서 derive하도록 변경되어 별도 label list를 중복 관리하지 않는다.

Rule registry의 current support list와 catalog의 `rule` method가 일치하는지는 unit test로 고정한다.

```text
tests/unit/test_scenario_catalog.py
```

## 7. Runtime Config와의 차이

`scenario_catalog.csv`와 `direct_scenarios.yaml`의 역할은 다르다.

```text
scenario_catalog.csv
→ 어떤 scenario가 존재하는가?
→ Rule / VLM 중 어떤 방식으로 처리하는가?
→ 현재 상태는 무엇인가?

direct_scenarios.yaml
→ Rule detector가 어떤 threshold / parameter로 동작하는가?
→ 현재 run에서 어떤 rule scenario가 enabled 되었는가?
```

따라서 detector threshold를 catalog에 넣지 않는다.

## 8. 유지보수 원칙

새 scenario를 추가하거나 처리 방식을 변경할 때는 가장 먼저:

```text
configs/scenario_catalog.csv
```

를 수정한다.

그 다음 필요한 경우에만 아래를 수정한다.

1. Rule scenario → detector / feature module + `direct_scenarios.yaml`
2. VLM scenario → `qwen_vlm_poc` candidate / prompt / validation
3. tests
4. GT reviewer support
5. evaluation artifact

Scenario 이름과 Rule/VLM 분류를 여러 Python 파일이나 Markdown 문서에 별도 list로 복사하지 않는다.
