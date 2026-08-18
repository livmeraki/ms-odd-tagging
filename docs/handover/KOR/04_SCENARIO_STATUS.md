# Scenario Status

## 1. Source of Truth

Scenario별 자동화 방식과 현재 상태는 하나의 catalog에서 관리한다.

```text
configs/scenario_catalog.csv
```

이 파일이 다음 정보의 **single source of truth**이다.

- scenario name
- category
- 자동 판별 방식 (`rule`, `vlm`)
- 현재 상태 (`active`, `experimental`, `unsupported`)

따라서 scenario가 Rule-based인지 VLM 기반인지 확인할 때 별도의 문서 목록을 찾지 말고 `scenario_catalog.csv`를 먼저 확인한다.

## 2. Catalog Columns

Catalog는 의도적으로 다음 네 column만 유지한다.

| Column | 의미 |
|---|---|
| `name` | scenario label |
| `category` | `dynamics`, `interaction`, `zone`, `maneuver`, `behavior` |
| `methods` | 현재 선택된 자동 판별 방식. `rule`, `vlm`, 또는 빈 값 |
| `status` | `active`, `experimental`, `unsupported` |

Catalog에는 detector threshold, VLM candidate group, taxonomy 예외 설명과 같은 implementation detail을 넣지 않는다.

각 scenario는 현재 기준으로 하나의 method만 가진다. 과거에 다른 방식으로 실험한 code가 남아 있더라도 현재 선택된 tagging 방식만 catalog에 기록한다.

## 3. Method 의미

### `rule`

Rule / Geometry / Temporal logic이 최종 scenario를 판별한다.

예:

- `stationary`
- `changing_lane`
- `traversing_crosswalk`
- `near_multiple_pedestrians`
- `waiting_for_pedestrian_to_cross`

Rule threshold와 detector parameter는 `configs/direct_scenarios.yaml`에서 관리한다.

### `vlm`

Rule / Geometry 기반으로 먼저 candidate 구간과 evidence를 선택한 뒤, VLM이 최종 scenario를 판별한다.

즉 `vlm`은 모든 frame을 그대로 VLM에 입력하는 방식이 아니라 다음과 같은 hybrid pipeline을 의미한다.

```text
Rule / Geometry based candidate selection
                ↓
       Evidence / BEV selection
                ↓
           VLM inference
                ↓
       Validation / merging
```

예:

- `on_intersection`
- `starting_u_turn`
- traffic-light 관련 scenario

VLM 관련 실행 code와 candidate grouping은 다음 package 안에서 관리한다.

```text
src/ms_odd_tagging/qwen_vlm_poc/
```

`waiting_for_pedestrian_to_cross`는 과거 VLM PoC도 구현되었지만, 현재 선택된 최종 방식은 deterministic `rule`이다. 따라서 catalog에서는 `rule`로만 관리하며, 해당 VLM PoC는 현재 VLM scenario configuration에서 제외한다.

## 4. Status 의미

| Status | 의미 |
|---|---|
| `active` | 현재 구현되어 기본적으로 사용할 수 있는 자동 tagging path가 존재 |
| `experimental` | 구현 또는 PoC path는 존재하지만 추가 calibration / validation 필요 |
| `unsupported` | 현재 자동 tagging path가 연결되지 않음 |

`methods`와 `status`는 서로 다른 정보를 표현한다.

예:

```text
on_intersection
methods = vlm
status = experimental
```

즉 판별 방식은 `methods`에서, 검증 수준은 `status`에서 확인한다.

> `active`는 production-level validation이 완전히 끝났다는 의미가 아니다. 실제 성능과 제한 사항은 evaluation 결과와 `07_KNOWN_ISSUES.md`를 함께 확인한다.

## 5. Reference Taxonomy와 Repository Extension

현재 catalog는 supplied Motional Scenario reference list를 기반으로 하며, repository가 실제로 사용하는 다음 두 label도 포함한다.

- `near_multiple_motorcycle`
- `crossed_by_motorcycle`

이 두 label은 현재 rule-based detector에서 사용되지만 supplied Motional Scenario reference list에는 없었다.

이 예외 때문에 모든 row에 별도의 taxonomy column을 추가하지 않는다. Reference taxonomy와 repository extension 차이는 이 문서에서 명시적으로 관리한다.

## 6. Code와 Catalog 관계

```text
configs/scenario_catalog.csv
          │
          ├── Rule method metadata
          │     └── rule registry와 consistency test
          │
          ├── VLM method metadata
          │     └── qwen_vlm_poc/config.py가 catalog coverage 검증
          │
          └── Handover documentation
```

VLM candidate grouping은 scenario 자체의 속성이 아니라 현재 VLM implementation의 구조이므로 `qwen_vlm_poc/config.py` 내부에서 관리한다.

Rule registry의 support list와 catalog의 `rule` method가 일치하는지, VLM grouping이 catalog의 `vlm` method 전체를 정확히 덮는지는 다음 unit test로 확인한다.

```text
tests/unit/test_scenario_catalog.py
```

## 7. Runtime Config와의 차이

`scenario_catalog.csv`와 `direct_scenarios.yaml`의 역할은 다르다.

```text
scenario_catalog.csv
→ 어떤 scenario가 존재하는가?
→ 현재 Rule / VLM 중 어떤 방식으로 처리하는가?
→ 현재 상태는 무엇인가?

direct_scenarios.yaml
→ Rule detector가 어떤 threshold / parameter로 동작하는가?
→ 현재 run에서 어떤 rule scenario가 enabled 되었는가?
```

따라서 detector threshold나 세부 algorithm parameter를 catalog에 넣지 않는다.

## 8. 유지보수 원칙

새 scenario를 추가하거나 처리 방식을 변경할 때는 가장 먼저:

```text
configs/scenario_catalog.csv
```

를 수정한다.

그 다음 필요한 경우에만 아래를 수정한다.

1. Rule scenario → detector / feature module + `direct_scenarios.yaml`
2. VLM scenario → `qwen_vlm_poc` candidate grouping / prompt / validation
3. tests
4. GT reviewer support
5. evaluation artifact

Scenario 이름과 Rule/VLM 분류를 여러 Python 파일이나 Markdown 문서에 별도 list로 복사하지 않는다.
