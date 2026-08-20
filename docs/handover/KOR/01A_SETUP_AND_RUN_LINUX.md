# Setup and Run — Linux

## 1. 대상 환경

이 문서는 Linux Bash 환경에서 repository를 처음 clone한 뒤 현재 pipeline을 실행하기 위한 runbook이다.

- Python 3.10 이상
- Bash
- repository root에서 명령 실행

## 2. Clone 및 branch 선택

~~~bash
git clone https://github.com/livmeraki/ms-odd-tagging.git
cd ms-odd-tagging
git switch refactor/repo-cleanup-20260813
git pull
~~~

## 3. Python environment 설치

~~~bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
~~~

설치 확인:

~~~bash
ms-odd-tagging --help
python -c "import ms_odd_tagging; print('ms_odd_tagging import OK')"
~~~

## 4. Data / Output 환경변수

~~~bash
export MS_ODD_DATA_ROOT="/absolute/path/to/data"
export MS_ODD_OUTPUT_ROOT="/absolute/path/to/outputs"
~~~

확인:

~~~bash
printf 'MS_ODD_DATA_ROOT=%s\n' "$MS_ODD_DATA_ROOT"
printf 'MS_ODD_OUTPUT_ROOT=%s\n' "$MS_ODD_OUTPUT_ROOT"
ls "$MS_ODD_DATA_ROOT/01_raw"
~~~

각 recording은 다음 파일을 포함해야 한다.

~~~text
$MS_ODD_DATA_ROOT/01_raw/<RECORDING_ID>/
├── annotations_OD.json
├── annotations_LD.json
└── traj_lcs.txt
~~~

## 5. Smoke Test

먼저 recording 1개에서 frame input 1개만 생성한다.

~~~bash
ms-odd-tagging <RECORDING_ID> \
  --frame-limit 1 \
  --existing-output regenerate
~~~

확인 항목:

- canonicalization이 완료되는지
- `01_canonical`에 canonical JSON이 생성되는지
- `02_frame_inputs`에 `frame.json`과 `bev.png`가 생성되는지
- BEV의 Ego, lane/road geometry, 주변 object가 정상적으로 보이는지

~~~bash
find "$MS_ODD_OUTPUT_ROOT/01_canonical" -maxdepth 1 -type f | head
find "$MS_ODD_OUTPUT_ROOT/02_frame_inputs" -type f | head
~~~

## 6. Pipeline 실행

Recording 1개:

~~~bash
ms-odd-tagging <RECORDING_ID>
~~~

2 FPS:

~~~bash
ms-odd-tagging <RECORDING_ID> --frames-per-second 2
~~~

모든 canonical frame에 대해 frame input 생성:

~~~bash
ms-odd-tagging <RECORDING_ID> --all-frames
~~~

기존 output 이어서 사용:

~~~bash
ms-odd-tagging <RECORDING_ID> --existing-output resume
~~~

기존 output 재생성:

~~~bash
ms-odd-tagging <RECORDING_ID> --existing-output regenerate
~~~

Canonical만 생성:

~~~bash
ms-odd-tagging <RECORDING_ID> --stop-after canonical
~~~

선택한 여러 recording:

~~~bash
ms-odd-tagging Rec_A Rec_B Rec_C --existing-output resume
~~~

모든 recording:

~~~bash
mapfile -t RECORDINGS < <(
  find "$MS_ODD_DATA_ROOT/01_raw" \
    -mindepth 1 -maxdepth 1 -type d \
    -printf '%f\n' | sort
)

printf '%s\n' "${RECORDINGS[@]}"
ms-odd-tagging "${RECORDINGS[@]}" --existing-output resume
~~~

Runtime log는 다음에 저장된다.

~~~bash
ls "$MS_ODD_OUTPUT_ROOT/runtime_logs"
~~~

## 7. 개별 Stage CLI

~~~bash
ms-odd-canonical --help
ms-odd-frame-inputs --help
ms-odd-rules --help
ms-odd-ld-topology --help
~~~

LD topology는 repository root의 별도 wrapper가 아니라 package CLI로 실행한다.

~~~bash
ms-odd-ld-topology --help
~~~

## 8. Full ODLD Scenario Explorer

~~~bash
python scripts/odld_explorer/generate_odld_dataset_explorers_w_scenario_tag.py \
  --source-root "$MS_ODD_DATA_ROOT/01_raw" \
  --canonical-dir "$MS_ODD_OUTPUT_ROOT/01_canonical" \
  --output-dir "$MS_ODD_OUTPUT_ROOT/06_scenario_explorers/odld" \
  --index-path "$MS_ODD_OUTPUT_ROOT/06_scenario_explorers/odld/index.html" \
  --regenerate-existing
~~~

생성 후 browser에서 다음 파일을 연다.

~~~text
$MS_ODD_OUTPUT_ROOT/06_scenario_explorers/odld/index.html
~~~

## 9. Simplified Taxonomy GT Workspace

~~~bash
python -m ms_odd_tagging.simplified_taxonomy.gt_workspace_profiled \
  --frame-root "$MS_ODD_OUTPUT_ROOT/02_frame_inputs" \
  --gt-root "$MS_ODD_OUTPUT_ROOT/06_gt_comparison/gt" \
  --source-hz 10 \
  --sample-hz 1 \
  --host 127.0.0.1 \
  --port 8765
~~~

Browser:

~~~text
http://127.0.0.1:8765
~~~

## 10. VLM

VLM 관련 CLI:

~~~bash
ms-odd-qwen-vlm-poc --help
~~~

Local vLLM endpoint를 사용할 경우 server port 확인:

~~~bash
lsof -i :8001
~~~

VLM candidate/evidence/inference 구조는 `02_PIPELINE.md`를 참고한다.

## 11. Test

~~~bash
python -m pytest
~~~
