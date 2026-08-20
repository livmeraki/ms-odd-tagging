# Setup and Run

## 1. 목적

이 문서는 새 담당자가 repository를 받아 **환경을 설치하고 recording 1개를 Smoke Test한 뒤 전체 input generation을 실행하는 것**까지 빠르게 진행할 수 있도록 정리한 runbook이다.

## 2. 기본 환경

현재 package는 Python 3.10 이상을 요구한다.

다음 명령은 Linux/macOS, Windows에서 동일하게 사용할 수 있다.

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

package를 editable install하지 않을 경우 `PYTHONPATH=src`를 설정해야 한다.

Linux/macOS:

```bash
export PYTHONPATH=src
```

Windows PowerShell:

```powershell
$env:PYTHONPATH = "src"
```

## 3. 주요 dependency

`pyproject.toml` 기준 기본 runtime dependency에는 Pillow와 Shapely가 포함된다. Shapely는 LD topology의 intersection geometry 구성 및 분류에 사용되므로 setup 시 함께 설치되어야 한다. 개발 환경에는 pytest와 numpy가 포함된다.

VLM server를 사용할 경우 `server` optional dependency에 vLLM, tokenizers, numpy, sympy, networkx 등이 정의되어 있다.

```bash
python -m pip install -e ".[server]"
```

Lanelet2 PoC는 Linux에서만 optional dependency로 제공된다.

## 4. 데이터 / 출력 경로

이 문서의 이후 명령은 모두 아래 두 환경변수를 기준으로 설명한다.

- `MS_ODD_DATA_ROOT`: 입력 data root
- `MS_ODD_OUTPUT_ROOT`: 생성 output root

Windows PowerShell 예시:

```powershell
$env:MS_ODD_DATA_ROOT = "D:\path\to\ms-odd-tagging-data\data"
$env:MS_ODD_OUTPUT_ROOT = "D:\path\to\ms-odd-tagging-data\outputs"
```

Linux/macOS 예시:

```bash
export MS_ODD_DATA_ROOT=/path/to/ms-odd-tagging-data/data
export MS_ODD_OUTPUT_ROOT=/path/to/ms-odd-tagging-data/outputs
```

환경변수 설정 후 pipeline은 다음 구조를 사용한다.

```text
$MS_ODD_DATA_ROOT/01_raw
        │
        ▼
$MS_ODD_OUTPUT_ROOT/01_canonical
        │
        ▼
$MS_ODD_OUTPUT_ROOT/02_frame_inputs
```

추가 output도 같은 `MS_ODD_OUTPUT_ROOT` 아래에 생성한다.

> PowerShell에서 `$env:...`로 설정한 값은 현재 terminal session에만 적용된다. 새 terminal을 열면 다시 설정해야 한다.

machine-specific path를 source code에 hard-code하지 않는다.

## 5. 입력 recording 준비

OD+LD pipeline을 사용할 recording은 다음 위치에 둔다.

```text
$MS_ODD_DATA_ROOT/01_raw/<RECORDING_ID>/
├── annotations_OD.json
├── annotations_LD.json
└── traj_lcs.txt
```

실제 raw directory layout은 `data/README.md`와 loader를 함께 확인한다.

## 6. 첫 실행: Smoke Test

처음에는 전체 recording을 처리하지 말고, **recording 1개에서 frame input 1개만 생성하여 setup과 입력 경로가 정상인지 확인**한다.

Smoke Test 실행 범위:

```text
$MS_ODD_DATA_ROOT/01_raw/<RECORDING_ID>
        │
        ▼
① Canonicalization
        │
        ▼
$MS_ODD_OUTPUT_ROOT/01_canonical
        │
        ▼
② Frame Input / BEV 생성 (1 frame)
        │
        ▼
$MS_ODD_OUTPUT_ROOT/02_frame_inputs
```

Linux/macOS:

```bash
python run_pipeline.py <RECORDING_ID> \
  --frame-limit 1
```

Windows PowerShell:

```powershell
python run_pipeline.py <RECORDING_ID> --frame-limit 1
```

예시:

```powershell
python run_pipeline.py Rec_Drv_GER_MACHET18_20260319_151819 --frame-limit 1
```

### Smoke Test 결과 확인

다음 네 가지만 확인한다.

- `Stage 1/2`, `Stage 2/2`가 error 없이 완료되었는지
- `$env:MS_ODD_OUTPUT_ROOT\01_canonical`에 해당 recording의 canonical JSON이 생성되었는지
- `$env:MS_ODD_OUTPUT_ROOT\02_frame_inputs`에 frame input JSON과 BEV가 1개 이상 생성되었는지
- BEV를 열었을 때 Ego, lane/road geometry, 주변 object가 정상적으로 표시되는지

위 항목이 정상이라면 전체 Recording 실행으로 진행한다.

## 7. 전체 Recording 실행

Smoke Test가 정상적으로 완료되었다면 같은 recording 전체에 대해 input generation을 실행한다. 기본 Frame Input / BEV sampling rate는 **1 FPS**이다.

> **관찰된 실행 시간:** 현재 Windows 로컬 환경에서 약 1분 길이 recording 1개를 기본 1 FPS로 처리할 때 Canonicalization + Frame Input / BEV 생성까지 대략 **30~40초/recording**이 소요되었다. 실제 측정값은 실행 종료 시 Runtime Summary와 `$env:MS_ODD_OUTPUT_ROOT\runtime_logs`의 JSON log에서 확인한다.

### Recording 1개 전체 실행

```powershell
python run_pipeline.py <RECORDING_ID>
```

예시:

```powershell
python run_pipeline.py Rec_Drv_GER_MACHET18_20260319_151819
```

2 FPS:

```powershell
python run_pipeline.py <RECORDING_ID> --frames-per-second 2
```

모든 canonical frame 생성:

```powershell
python run_pipeline.py <RECORDING_ID> --all-frames
```

### 선택한 여러 Recording 실행

```powershell
python run_pipeline.py Rec_A Rec_B Rec_C --existing-output resume
```

`MS_ODD_DATA_ROOT/01_raw`에서 앞의 10개 directory를 선택하려면:

```powershell
$recordings = Get-ChildItem (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") -Directory |
    Sort-Object Name |
    Select-Object -First 10

python run_pipeline.py $recordings.Name --existing-output resume
```

### Data folder의 모든 Recording 실행

```powershell
$recordings = Get-ChildItem (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") -Directory
python run_pipeline.py $recordings.Name --existing-output resume
```

Pipeline은 raw data를 `$env:MS_ODD_DATA_ROOT\01_raw`에서 읽고 결과를 `$env:MS_ODD_OUTPUT_ROOT` 아래에 생성하므로 `--source-root`, `--output-root`를 반복해서 지정할 필요가 없다.

Batch 중 일부 recording에 필수 파일이 없거나 processing error가 발생하면 해당 recording은 skip하고 나머지 recording을 계속 처리한다. 실패한 recording은 실행 마지막의 `Failed Recordings`와 runtime JSON에 기록된다.

### 전체 실행 후 확인

- Runtime Summary에서 각 stage와 전체 실행 시간을 확인
- `$env:MS_ODD_OUTPUT_ROOT\01_canonical`에 canonical 결과가 생성되었는지 확인
- `$env:MS_ODD_OUTPUT_ROOT\02_frame_inputs`에 frame input / BEV가 생성되었는지 확인
- 일부 BEV를 열어 Ego, road geometry, 주변 object 위치가 정상인지 확인

> `run_pipeline.py`의 전체 실행은 현재 **input generation pipeline 전체 실행**을 의미한다. Rule-based tagging, Full ODLD Scenario Explorer, Integrated ODLD GT Authoring, VLM은 이후 필요에 따라 별도로 사용한다.

---

## 8. 필요할 때 사용하는 추가 기능

아래 항목은 순서대로 실행하는 pipeline이 아니다. 전체 Recording 실행 이후 개발 목적에 따라 필요한 기능만 선택해서 사용한다.

| 하고 싶은 작업 | 사용할 기능 |
|---|---|
| Frame Input 없이 Canonical 결과만 생성 | Canonical만 생성 |
| Rule scenario 구성 및 detector 확인 | Rule-based Tagging 구성 확인 |
| OD + LD + Ego Trajectory + Scenario Tag를 함께 시각적으로 확인 | Full ODLD Scenario Explorer |
| Full ODLD Explorer에서 Ground Truth 작성 / 저장 | Integrated ODLD GT Authoring |
| VLM 실험 실행 | Local VLM Inference |

### 8.1 Canonical만 생성

```powershell
python run_pipeline.py <RECORDING_ID> --stop-after canonical
```

결과:

```text
$env:MS_ODD_OUTPUT_ROOT\01_canonical
```

### 8.2 Rule-based Tagging 구성 확인

현재 rule registry와 사용 가능한 option을 확인한다.

```powershell
python -m ms_odd_tagging.tagger.rule_based.registry --help
```

설정 파일은 repository의 다음 파일을 사용한다.

```text
configs/direct_scenarios.yaml
```

새 scenario를 추가하거나 detector를 수정하기 전에는 `enabled_scenarios`와 각 threshold의 `provenance`를 확인한다. Rule / Geometry algorithm의 상세 내용은 `05_ALGORITHMS.md`를 확인한다.

### 8.3 Full ODLD Scenario Explorer

최종 결과 확인과 디버깅에는 generic `ms_odd_tagging.visualization.scenario_explorer` 대신 full ODLD event-tag explorer를 사용한다.

현재 권장 실행 경로는 `generate_odld_dataset_explorers_w_stage_progress.py`이다. 이 runner는 raw OD/LD, Ego Trajectory, canonical data와 scenario tag를 함께 표시하는 explorer를 생성하면서, recording 내부의 실제 처리 stage가 완료될 때마다 진행 상황과 stage별 소요 시간을 출력한다.

`recordings` positional argument는 여러 개를 받을 수 있으며, argument를 생략하면 canonical directory에서 생성 가능한 recording 전체를 대상으로 한다.

> 현재 stage-progress runner는 **legacy window/tag cache를 읽지 않는다.** Rule-based scenario event는 현재 `$MS_ODD_OUTPUT_ROOT/01_canonical`의 canonical data와 현재 rule configuration을 기준으로 매 실행 시 다시 생성한다. 따라서 정상적인 Full ODLD Scenario Explorer 생성 명령에는 `legacy/windows` 경로나 `--window-dir`가 필요하지 않다.

Explorer 결과는 항상 다음 정상 output 경로 아래에 생성한다.

```text
$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers
```

#### Recording 1개 생성

Windows PowerShell:

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

예시:

```powershell
$RECORDING = "Rec_Drv_GER_MACHET18_20260319_144819"

python scripts/odld_explorer/generate_odld_dataset_explorers_w_stage_progress.py `
  --source-root (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") `
  --canonical-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "01_canonical") `
  --output-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "07_odld_scenario_explorers") `
  --index-path (Join-Path $env:MS_ODD_OUTPUT_ROOT "07_odld_scenario_explorers/index.html") `
  --regenerate-existing `
  $RECORDING
```

#### 선택한 여러 Recording 생성

이미 canonical이 생성된 recording 중 이름순 앞의 10개를 선택해 한 번에 생성하는 예시이다. ODLD explorer는 canonical file을 기준으로 생성되므로 raw directory가 아니라 `$MS_ODD_OUTPUT_ROOT/01_canonical`에서 선택한다.

Windows PowerShell:

```powershell
$RECORDINGS = Get-ChildItem (Join-Path $env:MS_ODD_OUTPUT_ROOT "01_canonical") `
  -Filter "*_canonical_odld_frames.json" -File |
  Sort-Object Name |
  Select-Object -First 10 |
  ForEach-Object { $_.BaseName -replace '_canonical_odld_frames$', '' }

# 실제 선택된 recording 확인
$RECORDINGS

python scripts/odld_explorer/generate_odld_dataset_explorers_w_stage_progress.py `
  --source-root (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") `
  --canonical-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "01_canonical") `
  --output-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "07_odld_scenario_explorers") `
  --index-path (Join-Path $env:MS_ODD_OUTPUT_ROOT "07_odld_scenario_explorers/index.html") `
  --regenerate-existing `
  $RECORDINGS
```

11~20번째 recording처럼 다음 batch를 생성하려면 selection 부분의 `Select-Object`만 다음과 같이 바꾼다.

```powershell
Select-Object -Skip 10 -First 10
```

예를 들어 21~30번째 recording은 `Select-Object -Skip 20 -First 10`을 사용한다.

#### 생성 가능한 모든 Recording 생성

recording argument를 생략한다.

Windows PowerShell:

```powershell
python scripts/odld_explorer/generate_odld_dataset_explorers_w_stage_progress.py `
  --source-root (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") `
  --canonical-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "01_canonical") `
  --output-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "07_odld_scenario_explorers") `
  --index-path (Join-Path $env:MS_ODD_OUTPUT_ROOT "07_odld_scenario_explorers/index.html") `
  --regenerate-existing
```

Linux/macOS:

```bash
python scripts/odld_explorer/generate_odld_dataset_explorers_w_stage_progress.py \
  --source-root "$MS_ODD_DATA_ROOT/01_raw" \
  --canonical-dir "$MS_ODD_OUTPUT_ROOT/01_canonical" \
  --output-dir "$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers" \
  --index-path "$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers/index.html" \
  --regenerate-existing
```

생성 중에는 다음과 같이 실제 완료된 stage와 해당 stage의 소요 시간이 출력된다.

```text
[odld-stage:<RECORDING_ID>] 1/17 ... complete: load canonical OD+LD JSON [...]
[odld-stage:<RECORDING_ID>] 2/17 ... complete: run LD topology classifier [...]
...
[odld-stage:<RECORDING_ID>] 17/17 ... complete: update index + manifest [...]
```

이 percentage는 **완료된 stage 개수 기준**이며 전체 runtime의 정확한 시간 비율을 의미하지 않는다. 특정 stage가 오래 걸리면 다음 완료 log가 출력되기까지 시간이 길어질 수 있다.

생성 후 다음 index를 browser에서 연다.

```text
$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers/index.html
```

rule 결과가 이상할 경우 이 explorer에서 OD / LD / Ego Trajectory / Scenario Event를 함께 확인한다.

### 8.4 Integrated ODLD GT Authoring

Ground Truth 작성에는 별도의 `ms_odd_tagging.gt_comparison.authoring` HTML page 대신, **Full ODLD Scenario Explorer에 GT authoring panel을 직접 결합한 최근 tool**을 사용한다. 이 방식에서는 OD / LD / Ego Trajectory / Scenario Event를 보면서 동일 frame 기준으로 GT를 작성할 수 있다.

먼저 8.3의 Full ODLD Scenario Explorer가 생성되어 있어야 한다.

#### 1) 생성된 모든 recording의 GT authoring explorer 생성

`recordings` positional argument를 생략하면 `07_odld_scenario_explorers`에 현재 생성되어 있는 모든 compatible recording을 대상으로 GT authoring explorer를 만든다. 이것을 기본 사용 방식으로 권장한다.

Windows PowerShell:

```powershell
python scripts/odld_explorer/add_gt_authoring_to_tagged_explorers.py `
  --source-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "07_odld_scenario_explorers") `
  --output-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "07_odld_scenario_explorers_gt_authoring_all_tags") `
  --frame-input-root (Join-Path $env:MS_ODD_OUTPUT_ROOT "02_frame_inputs") `
  --gt-dir (Join-Path $env:MS_ODD_DATA_ROOT "02_gt") `
  --regenerate-existing
```

Linux/macOS:

```bash
python scripts/odld_explorer/add_gt_authoring_to_tagged_explorers.py \
  --source-dir "$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers" \
  --output-dir "$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers_gt_authoring_all_tags" \
  --frame-input-root "$MS_ODD_OUTPUT_ROOT/02_frame_inputs" \
  --gt-dir "$MS_ODD_DATA_ROOT/02_gt" \
  --regenerate-existing
```

특정 recording만 다시 생성하고 싶을 때에만 command 마지막에 `<RECORDING_ID>`를 추가한다.

#### 2) Autosave server 실행

GT 작성 결과를 JSON으로 저장하려면 생성된 explorer 전체를 local server로 연다.

Windows PowerShell:

```powershell
python scripts/odld_explorer/serve_gt_authoring_explorers.py `
  --directory (Join-Path $env:MS_ODD_OUTPUT_ROOT "07_odld_scenario_explorers_gt_authoring_all_tags") `
  --gt-dir (Join-Path $env:MS_ODD_DATA_ROOT "02_gt") `
  --host 127.0.0.1 `
  --port 8080
```

Linux/macOS:

```bash
python scripts/odld_explorer/serve_gt_authoring_explorers.py \
  --directory "$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers_gt_authoring_all_tags" \
  --gt-dir "$MS_ODD_DATA_ROOT/02_gt" \
  --host 127.0.0.1 \
  --port 8080
```

server 실행 후 browser에서 다음 주소를 연다.

```text
http://127.0.0.1:8080/index.html
```

index에서 생성된 recording들을 선택해 GT를 작성한다. GT는 다음 위치에 recording별 JSON으로 저장된다.

```text
$MS_ODD_DATA_ROOT/02_gt/<RECORDING_ID>_frame_gt.json
```

GT authoring 중에는 server process를 종료하지 않는다. 작업이 끝나면 terminal에서 `Ctrl+C`로 종료한다.

### 8.5 Local VLM Inference

VLM PoC가 필요한 경우에만 사용한다.

Windows PowerShell:

```powershell
python -m ms_odd_tagging.tagger.model_based.local_vllm `
  --recording <RECORDING_ID> `
  --model-input-root (Join-Path $env:MS_ODD_OUTPUT_ROOT "02_frame_inputs") `
  --output-root (Join-Path $env:MS_ODD_OUTPUT_ROOT "03_tagging") `
  --endpoint http://127.0.0.1:8001/v1/chat/completions
```

Linux/macOS:

```bash
python -m ms_odd_tagging.tagger.model_based.local_vllm \
  --recording <RECORDING_ID> \
  --model-input-root "$MS_ODD_OUTPUT_ROOT/02_frame_inputs" \
  --output-root "$MS_ODD_OUTPUT_ROOT/03_tagging" \
  --endpoint http://127.0.0.1:8001/v1/chat/completions
```

> 위 client 명령 자체는 Windows에서도 실행할 수 있지만, local vLLM server의 지원 환경은 별도로 확인해야 한다. VLM 기능은 optional이며 deterministic rule pipeline을 먼저 확인한 뒤 사용한다.

## 9. 개별 Stage / CLI 확인

```bash
python -m ms_odd_tagging.canonical.builder --help
python -m ms_odd_tagging.frame_inputs.builder --help
python -m ms_odd_tagging.validator.frame_schema --help
python -m ms_odd_tagging.tagger.rule_based.registry --help
python scripts/odld_explorer/generate_odld_dataset_explorers_w_stage_progress.py --help
python scripts/odld_explorer/add_gt_authoring_to_tagged_explorers.py --help
python scripts/odld_explorer/serve_gt_authoring_explorers.py --help
```

위 명령은 data/output path를 사용하지 않으므로 Linux/macOS와 Windows PowerShell에서 동일하다.

## 10. 실행 전 / 문제 발생 시 체크리스트

- Python 3.10+인지 확인
- package install 또는 `PYTHONPATH=src` 설정
- `MS_ODD_DATA_ROOT`, `MS_ODD_OUTPUT_ROOT` 설정 확인
- `$MS_ODD_DATA_ROOT/01_raw/<RECORDING_ID>`에 OD/LD/trajectory가 모두 있는지 확인
- 첫 실행은 `--frame-limit 1` Smoke Test부터 수행
- Smoke Test 성공 후 전체 Recording 실행
- 실행 종료 후 Runtime Summary와 failed recording 확인
- Full ODLD Scenario Explorer는 `generate_odld_dataset_explorers_w_stage_progress.py` 사용
- Full ODLD Scenario Explorer 실행 시 `legacy/windows` 또는 `--window-dir`를 사용하지 않음
- Explorer 결과는 `$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers`에서 확인
- GT 작성 시 별도 Frame GT Reviewer 대신 Integrated ODLD GT Authoring 사용
- output을 Git에 commit하지 않기
