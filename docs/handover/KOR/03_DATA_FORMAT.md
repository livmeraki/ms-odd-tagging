# Data Format

## 1. 목적

이 문서는 Motional Scenario tagging pipeline에서 사용하는 OD, LD, Ego Trajectory와 canonical/frame input의 관계를 설명한다.

## 2. Raw OD Annotation

OD ALT 데이터는 기본적으로 scene-level object-centric 구조이다.

개념적 구조:

```text
scene
└── objects[]
    ├── className
    ├── object/track identifier
    └── frames[]
        └── bbox3d / frame-specific attributes
```

현재 사용되는 OD class 예에는 다음이 포함된다.

- `pedestrian`
- `rider_bicycle`
- `rider_motorcycle`
- `car`
- `truck`
- `bus`
- `traffic_sign`
- `traffic_light_car`
- `crosswalk`
- `stopline`
- obstacle 계열

OD의 `bbox3d`는 주변 객체의 위치, 크기, orientation 및 ego와의 relation 계산에 사용된다.

## 3. Ego Trajectory

`traj_lcs.txt`의 기본 column:

```text
timestamp tx ty tz qx qy qz qw
```

주요 용도:

- ego position
- ego orientation / heading
- frame 간 displacement
- speed / acceleration / jerk 계산
- yaw / turn 계산
- OD/LD geometry를 ego motion과 연결

Trajectory row와 annotation frame의 정합은 매우 중요하다. detector 내부에서 임의 offset을 추가하기보다 canonicalizer의 synchronization contract를 사용한다.

## 4. Raw LD Annotation

LD는 recording-level road/lane geometry를 제공하며 lane, boundary, topology, roadmark 등의 구조를 포함한다. Canonicalization 단계에서는 이를 recording-wide feature store로 정규화하고, 각 frame에서는 ego pose 기준 nearby feature를 참조한다.

주요 사용 정보:

- lane / lane boundary geometry
- lane topology
- road boundary
- crosswalk / stopline 등 roadmark
- intersection 관련 geometry

## 5. OD / LD / Trajectory 정합

```text
OD annotation ─┐
LD annotation ─┼─> Canonicalization
Trajectory ────┘
```

현재 지원되는 canonicalization은 이 세 입력을 함께 사용하는 **OD+LD+Trajectory 단일 경로**이다.

- OD는 frame별 dynamic object 상태를 제공한다.
- LD는 recording-level static/shared road geometry를 제공한다.
- Trajectory는 ego pose와 공통 시간축을 제공한다.

따라서 detector에서 OD와 LD를 별도 독립 schema로 취급하기보다 canonical representation을 source of truth로 사용한다.

## 6. Canonical Data

현재 active pipeline의 canonical schema는 하나이다.

```text
odld-trajectory-canonical-frame-v1
```

Canonical data에서는 frame별 dynamic data와 recording-wide LD feature store를 분리해 불필요한 geometry duplication을 줄인다.

중요 contract:

- `frames[]`: original source frame index와 timestamp를 유지하는 frame sequence
- `ego`: ego pose / speed / acceleration / yaw-rate 등
- `objects`: 해당 frame의 normalized OD object state
- `ld_feature_store`: recording-wide LD geometry shared feature 저장소
- `ld.nearby_feature_ids`: 해당 frame에서 사용할 nearby LD feature reference
- `scenario_signals` / `interaction_candidates`: downstream rule/geometry 판단에 사용하는 derived evidence

BEV 또는 geometry feature를 생성할 때 `ld_feature_store`와 frame-level LD reference가 모두 필요하다.

> 실제 field 이름과 schema는 현재 `ms_odd_tagging.canonical.builder` output을 source of truth로 사용한다. 이 문서의 예시는 구조 이해용이며 schema를 대체하지 않는다.

## 7. Frame Input

선택된 timestamp마다 독립적인 model-facing input을 생성한다.

```text
<selected frame>/
├── frame.json
└── bev.png
```

기본 sampling은 1 FPS이다.

현재 active frame reviewer는 각 sampled source frame의 exact BEV를 사용한다. legacy 5-second motional window나 start/middle/end image 묶음을 기본 입력으로 사용하지 않는다.

## 8. Rule Event와 Model Input의 분리

중요한 설계 원칙:

```text
Canonical data
├── model-facing frame.json
└── rule-derived events / GT reference
```

Rule detector가 생성한 정답 후보를 model-facing `frame.json`에 직접 삽입하지 않는다. 이는 VLM 평가 시 answer leakage를 막기 위한 contract이다.

## 9. Coordinate / Geometry 주의사항

- 입력 데이터의 좌표계 종류를 확인한 후 변환한다.
- BEV는 ego-centric representation을 사용하며 ego heading과 geometry 방향을 일관되게 유지해야 한다.
- lane polygon, object footprint, crosswalk/stopline relation을 계산할 때 center point 하나만으로 판단하지 말고 footprint/geometry overlap 여부를 확인한다.
- 숫자 `0`은 정상 값일 수 있으므로 falsy 처리로 `null`로 바꾸지 않는다.
