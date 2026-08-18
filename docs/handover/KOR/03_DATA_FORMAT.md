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

LD ALT는 OD와 달리 **frame-centric, lane/boundary-centric** 구조이다.

주요 구조:

### Lane lines

`line_predictions_CCS`

일반적으로 L1~L5 / R1~R5 형태의 lane-line candidate가 포함되며 다음과 같은 값이 사용된다.

- `type_shape_infer`
- `type_sd`
- `type_color`
- `ccs_pts`
- `ccs_left_pts`
- `ccs_right_pts`
- `vcs_pts`
- `src_ics_pts`
- `confidence`

### Boundary

`boundary_predictions_CCS`

예:

- guardrail
- curb
- road edge

### Freespace

`fsd_edges`

free-space boundary geometry를 나타낸다.

## 5. OD와 LD의 중요한 차이

```text
OD ALT
scene -> objects -> frames -> bbox3d

LD ALT
frame -> lane lines / boundaries / freespace
```

따라서 canonicalization의 핵심은 object-centric OD와 frame-centric LD를 ego trajectory의 공통 시간축에 맞추는 것이다.

## 6. Canonical Data

현재 두 canonical schema가 존재한다.

```text
od-trajectory-canonical-frame-v1
odld-trajectory-canonical-frame-v1
```

OD+LD canonical에서는 frame별 dynamic data와 static/shared LD feature store를 분리해 불필요한 geometry duplication을 줄인다.

중요 contract:

- `ld_feature_store`: LD geometry의 shared feature 저장소
- `ld.nearby_feature_ids`: 해당 frame에서 사용할 nearby LD feature reference

BEV 또는 geometry feature를 생성할 때 두 구조가 모두 필요하다.

> 실제 field 이름과 schema는 현재 canonicalizer output을 source of truth로 사용한다. 이 문서의 예시는 구조 이해용이며 schema를 대체하지 않는다.

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

## 10. 데이터 확인 시 권장 순서

새 recording에서 이상이 발생하면 다음 순서로 확인한다.

1. raw file 존재 여부
2. OD frame 수 / trajectory row 수
3. timestamp/frame ordering
4. canonical frame 생성 결과
5. LD feature store와 nearby IDs
6. BEV에서 실제 geometry 정합 확인
7. 그 다음 scenario detector 결과 확인

데이터 alignment 문제를 detector threshold 문제로 오인하지 않는 것이 중요하다.
