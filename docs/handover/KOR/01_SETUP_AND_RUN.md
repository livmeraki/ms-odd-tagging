# Setup and Run

## 1. 목적

이 문서는 새 담당자가 repository를 받아 환경을 설치하고, recording 1개를 Smoke Test한 뒤, 전체 input generation과 기본 GT review까지 실행할 수 있도록 정리한 runbook이다.

현재 `run_pipeline.py`의 기본 흐름은 다음과 같다.

```text
Raw OD / LD / Ego Trajectory
        │
        ▼
1. Canonicalization
        │
        ▼
outputs/01_canonical
        │
        ▼
2. Frame Input / BEV + 1 FPS rule frame tags
        │
        ▼
outputs/02_frame_inputs
        │
        ▼
3. Simplified Taxonomy GT Workspace 자동 실행
   ms_odd_tagging.simplified_taxonomy.gt_workspace_profiled
        │
        ▼
outputs/06_gt_comparison/gt
```

GT Workspace는 browser에서 사용하는 interactive server이므로 pipeline 마지막에서 실행된 뒤 `Ctrl+C`로 종료할 때까지 process가 유지된다. unattended / batch input generation만 수행하려면 `--no-gt-workspace`를 사용한다.

## 2. 기본 환경

현재 package는 Python 3.10 이상을 요구한다.

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

package를 editable install하지 않을 경우 `PYTHONPATH=src`를 설정한다.

Linux/macOS:

```bash
export PYTHONPATH=src
```

Windows PowerShell:

```powershell
$env:PYTHONPATH = "src"
```

기본 runtime dependency에는 Pillow와 Shapely가 포함된다. VLM server가 필요할 때만 다음 optional dependency를 설치한다.

```bash
python -m pip install -e ".[server]"
```

## 3. 데이터 / 출력 경로

모든 예시는 다음 두 환경변수를 기준으로 한다.

- `MS_ODD_DATA_ROOT`: 입력 data root
- `MS_ODD_OUTPUT_ROOT`: 생성 output root

Windows PowerShell:

```powershell
$env:MS_ODD_DATA_ROOT = "D:\path\to\ms-odd-tagging-data\data"
$env:MS_ODD_OUTPUT_ROOT = "D:\path\to\ms-odd-tagging-data\outputs"
```

Linux/macOS:

```bash
export MS_ODD_DATA_ROOT=/path/to/ms-odd-tagging-data/data
export MS_ODD_OUTPUT_ROOT=/path/to/ms-odd-tagging-data/outputs
```

주요 경로:

```text
$MS_ODD_DATA_ROOT/01_raw
$MS_ODD_OUTPUT_ROOT/01_canonical
$MS_ODD_OUTPUT_ROOT/02_frame_inputs
$MS_ODD_OUTPUT_ROOT/06_gt_comparison/gt
$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers
```

machine-specific path를 source code에 hard-code하지 않는다.

## 4. 입력 recording 준비

```text
$MS_ODD_DATA_ROOT/01_raw/<RECORDING_ID>/
├── annotations_OD.json
├── annotations_LD.json
└── traj_lcs.txt
```

## 5. 첫 실행: Smoke Test

recording 1개에서 frame input 1개만 생성해 setup을 확인한다.

Windows PowerShell:

```powershell
python run_pipeline.py <RECORDING_ID> --frame-limit 1
```

예시:

```powershell
python run_pipeline.py Rec_Drv_GER_MACHET18_20260319_151819 --frame-limit 1
```

Stage 1과 Stage 2가 완료되면 기본 GT Workspace가 자동으로 실행된다.

```text
GT Workspace profiler: http://127.0.0.1:8765
```

browser에서 다음 주소를 연다.

```text
http://127.0.0.1:8765
```

확인할 항목:

- `01_canonical`에 해당 recording의 canonical JSON이 생성되었는지
- `02_frame_inputs/<recording>/frame_XXXXXX/frame.json`이 생성되었는지
- 같은 frame directory에 `bev.png`가 생성되었는지
- `02_frame_inputs/<recording>/recording_frame_tags_1fps`가 생성되었는지
- GT Workspace에서 recording이 보이는지
- BEV와 Prediction이 같은 시점으로 정렬되어 보이는지
- GT 수정 후 저장 내용이 `06_gt_comparison/gt`에 autosave되는지

작업이 끝나면 GT Workspace를 실행한 terminal에서 `Ctrl+C`를 누른다.

GT Workspace를 띄우지 않고 input generation만 Smoke Test하려면:

```powershell
python run_pipeline.py <RECORDING_ID> --frame-limit 1 --no-gt-workspace
```

## 6. 전체 Recording 실행

기본 Frame Input / BEV sampling rate는 1 FPS이다.

### Recording 1개

```powershell
python run_pipeline.py <RECORDING_ID>
```

### 2 FPS frame input 생성

```powershell
python run_pipeline.py <RECORDING_ID> --frames-per-second 2
```

GT Workspace 자체의 review 기준은 현재 1 FPS frame-tag prediction에 맞춰 1 FPS로 유지된다.

### 모든 canonical frame 생성

```powershell
python run_pipeline.py <RECORDING_ID> --all-frames
```

### 선택한 여러 Recording

```powershell
python run_pipeline.py Rec_A Rec_B Rec_C --existing-output resume
```

### 앞의 10개 Recording

```powershell
$recordings = Get-ChildItem (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") -Directory |
    Sort-Object Name |
    Select-Object -First 10

python run_pipeline.py $recordings.Name --existing-output resume
```

### Data folder의 모든 Recording

interactive GT Workspace를 batch 끝에 띄우고 싶다면:

```powershell
$recordings = Get-ChildItem (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") -Directory
python run_pipeline.py $recordings.Name --existing-output resume
```

input generation만 unattended로 수행하려면 반드시 `--no-gt-workspace`를 붙인다.

```powershell
$recordings = Get-ChildItem (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") -Directory
python run_pipeline.py $recordings.Name --existing-output resume --no-gt-workspace
```

일부 recording이 실패해도 나머지는 계속 처리하며, 실패 목록과 timing은 `runtime_logs`에 기록된다.

## 7. 기본 GT Workspace

현재 pipeline의 기본 GT reviewer는 다음 module이다.

```text
ms_odd_tagging.simplified_taxonomy.gt_workspace_profiled
```

Pipeline을 거치지 않고 GT Workspace만 다시 실행할 수도 있다.

Windows PowerShell:

```powershell
python -m ms_odd_tagging.simplified_taxonomy.gt_workspace_profiled `
  --frame-root (Join-Path $env:MS_ODD_OUTPUT_ROOT "02_frame_inputs") `
  --gt-root (Join-Path $env:MS_ODD_OUTPUT_ROOT "06_gt_comparison/gt") `
  --source-hz 10 `
  --sample-hz 1 `
  --host 127.0.0.1 `
  --port 8765
```

Linux/macOS:

```bash
python -m ms_odd_tagging.simplified_taxonomy.gt_workspace_profiled \
  --frame-root "$MS_ODD_OUTPUT_ROOT/02_frame_inputs" \
  --gt-root "$MS_ODD_OUTPUT_ROOT/06_gt_comparison/gt" \
  --source-hz 10 \
  --sample-hz 1 \
  --host 127.0.0.1 \
  --port 8765
```

### Prediction source

GT Workspace는 별도의 `*_simplified_prediction.json`을 기본 prediction source로 사용하지 않는다.

현재 prediction source는 각 recording의:

```text
$MS_ODD_OUTPUT_ROOT/02_frame_inputs/<RECORDING_ID>/recording_frame_tags_1fps/
```

이다.

각 frame-tag JSON의 active Motional Scenario를 simplified taxonomy로 mapping해 Prediction으로 보여 준다.

Frame Input과 frame-tag exporter는 1 FPS sampling 방식이 서로 다를 수 있으므로 prediction alignment는 다음 순서를 사용한다.

1. exact frame index match
2. exact match가 없으면 timestamp 기준 nearest frame match
3. 1 FPS 기준 half sample period 안에 들어오는 경우에만 accept

review되지 않은 frame은 prediction을 GT control에 prefill하지만 `UNREVIEWED` 상태로 유지된다. 사용자가 `Save` 또는 `Save + Next`를 수행해야 GT로 인정된다. 이미 저장된 reviewed GT가 있으면 prediction으로 덮어쓰지 않는다.

### Autosave output

```text
$MS_ODD_OUTPUT_ROOT/06_gt_comparison/gt/<RECORDING_ID>_manual_gt.json
```

### GT Workspace profiling

현재 default module은 초기 recording-list loading 성능을 확인하기 위해 startup/list-load timing도 terminal에 출력한다.

예:

```text
GT WORKSPACE LIST LOAD PROFILE #1
Recordings scanned: ...
1. scan/read frame inputs : ...
2. read reviewed GT      : ...
3. read GT metadata      : ...
4. read current frame tags: ...
5. status/finalize       : ...
```

## 8. Pipeline option

### Canonical까지만 생성

```powershell
python run_pipeline.py <RECORDING_ID> --stop-after canonical
```

이 경우 GT Workspace는 실행되지 않는다.

### GT Workspace 실행 생략

```powershell
python run_pipeline.py <RECORDING_ID> --no-gt-workspace
```

### GT Workspace port 변경

```powershell
python run_pipeline.py <RECORDING_ID> --gt-port 8766
```

host도 필요하면 변경할 수 있다.

```powershell
python run_pipeline.py <RECORDING_ID> --gt-host 127.0.0.1 --gt-port 8766
```

## 9. Full ODLD Scenario Explorer

GT Workspace와 별개로, OD + LD + Ego Trajectory + Scenario Event를 전체적으로 디버깅할 때는 Full ODLD Scenario Explorer를 사용한다.

권장 runner:

```text
scripts/odld_explorer/generate_odld_dataset_explorers_w_stage_progress.py
```

Recording 1개:

```powershell
$RECORDING = "<RECORDING_ID>"

python scripts/odld_explorer/generate_odld_dataset_explorers_w_stage_progress.py `
  --source-root (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") `
  --canonical-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "01_canonical") `
  --output-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "07_odld_scenario_explorers") `
  --index-path (Join-Path $env:MS_ODD_OUTPUT_ROOT "07_odld_scenario_explorers/index.html") `
  --regenerate-existing `
  $RECORDING
```

모든 생성 가능한 recording:

```powershell
python scripts/odld_explorer/generate_odld_dataset_explorers_w_stage_progress.py `
  --source-root (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") `
  --canonical-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "01_canonical") `
  --output-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "07_odld_scenario_explorers") `
  --index-path (Join-Path $env:MS_ODD_OUTPUT_ROOT "07_odld_scenario_explorers/index.html") `
  --regenerate-existing
```

Explorer 결과:

```text
$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers/index.html
```

이 runner는 current canonical + current rule configuration을 기준으로 scenario event를 다시 생성하며 normal-use path에서는 legacy window cache를 사용하지 않는다.

> 과거 Full ODLD Explorer에 GT authoring panel을 주입하던 `add_gt_authoring_to_tagged_explorers.py` / `serve_gt_authoring_explorers.py` 흐름은 현재 기본 GT workflow가 아니다. 필요한 historical/debug use case에서만 사용한다.

## 10. Local VLM Inference

VLM PoC가 필요한 경우에만 사용한다.

Windows PowerShell:

```powershell
python -m ms_odd_tagging.tagger.model_based.local_vllm `
  --recording <RECORDING_ID> `
  --model-input-root (Join-Path $env:MS_ODD_OUTPUT_ROOT "02_frame_inputs") `
  --output-root (Join-Path $env:MS_ODD_OUTPUT_ROOT "03_tagging") `
  --endpoint http://127.0.0.1:8001/v1/chat/completions
```

## 11. 개별 CLI 확인

```bash
python run_pipeline.py --help
python -m ms_odd_tagging.canonical.builder --help
python -m ms_odd_tagging.frame_inputs.builder --help
python -m ms_odd_tagging.simplified_taxonomy.gt_workspace_profiled --help
python scripts/odld_explorer/generate_odld_dataset_explorers_w_stage_progress.py --help
```

## 12. 실행 전 / 문제 발생 시 체크리스트

- Python 3.10+인지 확인
- package install 또는 `PYTHONPATH=src` 설정
- `MS_ODD_DATA_ROOT`, `MS_ODD_OUTPUT_ROOT` 설정
- raw recording에 OD / LD / trajectory가 모두 있는지 확인
- 첫 실행은 `--frame-limit 1` Smoke Test 권장
- `bev.png`와 `recording_frame_tags_1fps` 생성 확인
- GT Workspace에서 BEV와 prediction frame alignment 확인
- GT autosave 위치는 `06_gt_comparison/gt`
- unattended batch는 `--no-gt-workspace` 사용
- Full ODLD Scenario Explorer는 별도 debugging / visual inspection 용도
- output을 Git에 commit하지 않기
