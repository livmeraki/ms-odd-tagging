# Setup and Run — Linux

## 1. 대상 환경

이 문서는 Linux Bash 환경에서 repository 설치부터 Smoke Test, batch input generation, ODLD Explorer, GT Authoring, VLM client 실행까지 진행하기 위한 runbook이다.

- Python 3.10 이상
- Bash
- repository root에서 명령 실행
- Lanelet2와 local vLLM server는 Linux 환경을 권장한다.

> 이 문서의 명령은 Bash용이다. PowerShell 명령과 섞어 사용하지 않는다.

## 2. Python environment 설치

~~~bash
python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest
~~~

virtual environment가 활성화되면 prompt 앞에 (.venv)가 표시된다.

package를 editable install하지 않는 경우:

~~~bash
export PYTHONPATH=src
~~~

VLM server dependency가 필요한 경우:

~~~bash
python -m pip install -e ".[server]"
~~~

## 3. Data / Output 환경변수

현재 terminal session에서 설정:

~~~bash
export MS_ODD_DATA_ROOT="/absolute/path/to/ms-odd-tagging-data/data"
export MS_ODD_OUTPUT_ROOT="/absolute/path/to/ms-odd-tagging-data/outputs"
~~~

값 확인:

~~~bash
printf 'MS_ODD_DATA_ROOT=%s\n' "$MS_ODD_DATA_ROOT"
printf 'MS_ODD_OUTPUT_ROOT=%s\n' "$MS_ODD_OUTPUT_ROOT"
ls "$MS_ODD_DATA_ROOT/01_raw"
~~~

### 3.1 Bash에서 영구 설정

~/.bashrc를 연다.

~~~bash
nano ~/.bashrc
~~~

마지막에 다음 내용을 추가한다.

~~~bash
export MS_ODD_DATA_ROOT="/absolute/path/to/ms-odd-tagging-data/data"
export MS_ODD_OUTPUT_ROOT="/absolute/path/to/ms-odd-tagging-data/outputs"
~~~

저장 후 현재 terminal에 적용한다.

~~~bash
source ~/.bashrc
~~~

새 Bash terminal에서는 자동으로 적용된다.

## 4. 입력 Recording 구조

~~~text
$MS_ODD_DATA_ROOT/01_raw/<RECORDING_ID>/
├── annotations_OD.json
├── annotations_LD.json
└── traj_lcs.txt
~~~

입력 directory 확인:

~~~bash
RECORDING="<RECORDING_ID>"
ls -la "$MS_ODD_DATA_ROOT/01_raw/$RECORDING"
~~~

## 5. Smoke Test

처음에는 recording 1개에서 frame input 1개만 생성한다.

~~~bash
python run_pipeline.py <RECORDING_ID> \
  --frame-limit 1
~~~

예시:

~~~bash
python run_pipeline.py Rec_Drv_GER_MACHET18_20260319_151819 \
  --frame-limit 1
~~~

확인 항목:

- Stage 1/2와 Stage 2/2가 error 없이 완료되었는지
- $MS_ODD_OUTPUT_ROOT/01_canonical에 canonical JSON이 생성되었는지
- $MS_ODD_OUTPUT_ROOT/02_frame_inputs에 frame input JSON과 BEV가 생성되었는지
- BEV에서 Ego, lane/road geometry, 주변 object가 정상적으로 표시되는지

~~~bash
find "$MS_ODD_OUTPUT_ROOT/01_canonical" -maxdepth 1 -type f | head
find "$MS_ODD_OUTPUT_ROOT/02_frame_inputs" -type f | head
~~~

## 6. Input Generation 실행

기본 Frame Input / BEV sampling rate는 1 FPS이다.

### 6.1 Recording 1개 전체 실행

~~~bash
python run_pipeline.py <RECORDING_ID>
~~~

예시:

~~~bash
python run_pipeline.py Rec_Drv_GER_MACHET18_20260319_151819
~~~

2 FPS:

~~~bash
python run_pipeline.py <RECORDING_ID> \
  --frames-per-second 2
~~~

모든 canonical frame 생성:

~~~bash
python run_pipeline.py <RECORDING_ID> \
  --all-frames
~~~

기존 output을 이어서 사용:

~~~bash
python run_pipeline.py <RECORDING_ID> \
  --existing-output resume
~~~

기존 output을 재생성:

~~~bash
python run_pipeline.py <RECORDING_ID> \
  --existing-output regenerate
~~~

### 6.2 선택한 여러 Recording 실행

~~~bash
python run_pipeline.py Rec_A Rec_B Rec_C \
  --existing-output resume
~~~

### 6.3 이름순 앞의 10개 Recording 실행

~~~bash
recordings=()

while IFS= read -r recording; do
  recordings+=("$recording")
done < <(
  for recording_path in "$MS_ODD_DATA_ROOT"/01_raw/*/; do
    [ -d "$recording_path" ] || continue
    basename "$recording_path"
  done | sort | head -n 10
)

printf '%s\n' "${recordings[@]}"
python run_pipeline.py "${recordings[@]}" \
  --existing-output resume
~~~

### 6.4 모든 Recording 실행

~~~bash
recordings=()

while IFS= read -r recording; do
  recordings+=("$recording")
done < <(
  for recording_path in "$MS_ODD_DATA_ROOT"/01_raw/*/; do
    [ -d "$recording_path" ] || continue
    basename "$recording_path"
  done | sort
)

printf '%s\n' "${recordings[@]}"
python run_pipeline.py "${recordings[@]}" \
  --existing-output resume
~~~

필수 파일이 없거나 processing error가 발생한 recording은 skip되며 실행 마지막의 Failed Recordings와 runtime JSON에 기록된다.

Runtime log:

~~~bash
ls "$MS_ODD_OUTPUT_ROOT/runtime_logs"
~~~

## 7. Canonical만 생성

~~~bash
python run_pipeline.py <RECORDING_ID> \
  --stop-after canonical
~~~

결과:

~~~text
$MS_ODD_OUTPUT_ROOT/01_canonical
~~~

## 8. Rule-based Tagging 구성 확인

~~~bash
python -m ms_odd_tagging.tagger.rule_based.registry --help
~~~

설정 파일:

~~~text
configs/direct_scenarios.yaml
~~~

새 scenario를 추가하거나 detector를 수정하기 전 enabled_scenarios와 각 threshold의 provenance를 확인한다.

## 9. Full ODLD Scenario Explorer

Explorer output:

~~~text
$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers
~~~

### 9.1 Recording 1개

~~~bash
RECORDING="<RECORDING_ID>"

python scripts/odld_explorer/generate_odld_dataset_explorers_w_stage_progress.py \
  --source-root "$MS_ODD_DATA_ROOT/01_raw" \
  --canonical-dir "$MS_ODD_OUTPUT_ROOT/01_canonical" \
  --output-dir "$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers" \
  --index-path "$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers/index.html" \
  --regenerate-existing \
  "$RECORDING"
~~~

### 9.2 Canonical 기준 이름순 앞의 10개

~~~bash
RECORDINGS=()

while IFS= read -r recording; do
  RECORDINGS+=("$recording")
done < <(
  for canonical_path in "$MS_ODD_OUTPUT_ROOT"/01_canonical/*_canonical_odld_frames.json; do
    [ -f "$canonical_path" ] || continue
    filename=$(basename "$canonical_path")
    printf '%s\n' "${filename%_canonical_odld_frames.json}"
  done | sort | head -n 10
)

printf '%s\n' "${RECORDINGS[@]}"

python scripts/odld_explorer/generate_odld_dataset_explorers_w_stage_progress.py \
  --source-root "$MS_ODD_DATA_ROOT/01_raw" \
  --canonical-dir "$MS_ODD_OUTPUT_ROOT/01_canonical" \
  --output-dir "$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers" \
  --index-path "$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers/index.html" \
  --regenerate-existing \
  "${RECORDINGS[@]}"
~~~

11~20번째 recording은 selection pipeline의 마지막을 다음과 같이 바꾼다.

~~~bash
done | sort | tail -n +11 | head -n 10
~~~

21~30번째 recording은 tail -n +21을 사용한다.

### 9.3 생성 가능한 모든 Recording

recording argument를 생략한다.

~~~bash
python scripts/odld_explorer/generate_odld_dataset_explorers_w_stage_progress.py \
  --source-root "$MS_ODD_DATA_ROOT/01_raw" \
  --canonical-dir "$MS_ODD_OUTPUT_ROOT/01_canonical" \
  --output-dir "$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers" \
  --index-path "$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers/index.html" \
  --regenerate-existing
~~~

생성 후 다음 index를 browser에서 연다.

~~~text
$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers/index.html
~~~

## 10. Integrated ODLD GT Authoring

먼저 Full ODLD Scenario Explorer를 생성해야 한다.

### 10.1 GT Authoring Explorer 생성

~~~bash
python scripts/odld_explorer/add_gt_authoring_to_tagged_explorers.py \
  --source-dir "$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers" \
  --output-dir "$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers_gt_authoring_all_tags" \
  --frame-input-root "$MS_ODD_OUTPUT_ROOT/02_frame_inputs" \
  --gt-dir "$MS_ODD_DATA_ROOT/02_gt" \
  --regenerate-existing
~~~

특정 recording만 생성하려면 command 마지막에 RECORDING_ID를 추가한다.

### 10.2 Autosave Server 실행

~~~bash
python scripts/odld_explorer/serve_gt_authoring_explorers.py \
  --directory "$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers_gt_authoring_all_tags" \
  --gt-dir "$MS_ODD_DATA_ROOT/02_gt" \
  --host 127.0.0.1 \
  --port 8080
~~~

Browser:

~~~text
http://127.0.0.1:8080/index.html
~~~

GT output:

~~~text
$MS_ODD_DATA_ROOT/02_gt/<RECORDING_ID>_frame_gt.json
~~~

작업 중에는 server를 종료하지 않는다. 작업이 끝나면 Ctrl+C로 종료한다.

## 11. Local VLM Inference

VLM client:

~~~bash
python -m ms_odd_tagging.tagger.model_based.local_vllm \
  --recording <RECORDING_ID> \
  --model-input-root "$MS_ODD_OUTPUT_ROOT/02_frame_inputs" \
  --output-root "$MS_ODD_OUTPUT_ROOT/03_tagging" \
  --endpoint http://127.0.0.1:8001/v1/chat/completions
~~~

Server port 확인:

~~~bash
lsof -i :8001
~~~

VLM은 optional이다. 먼저 deterministic rule pipeline을 확인한다.

## 12. CLI 확인

~~~bash
python -m ms_odd_tagging.canonical.builder --help
python -m ms_odd_tagging.frame_inputs.builder --help
python -m ms_odd_tagging.validator.frame_schema --help
python -m ms_odd_tagging.tagger.rule_based.registry --help
python scripts/odld_explorer/generate_odld_dataset_explorers_w_stage_progress.py --help
python scripts/odld_explorer/add_gt_authoring_to_tagged_explorers.py --help
python scripts/odld_explorer/serve_gt_authoring_explorers.py --help
~~~

## 13. 자주 발생하는 문제

### Bash syntax error near unexpected token

원인: PowerShell의 Get-ChildItem, Join-Path 또는 $env:... 명령을 Bash에서 실행했다.

해결: 이 문서의 Bash command만 사용한다.

### 환경변수가 비어 있음

~~~bash
source ~/.bashrc
printf '%s\n' "$MS_ODD_DATA_ROOT"
printf '%s\n' "$MS_ODD_OUTPUT_ROOT"
~~~

### Port 8001이 이미 사용 중

~~~bash
lsof -i :8001
~~~

process를 확인한 뒤 필요한 경우 해당 server를 정상 종료한다.
