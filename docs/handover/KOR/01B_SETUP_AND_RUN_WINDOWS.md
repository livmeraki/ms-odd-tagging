# Setup and Run — Windows

## 1. 대상 환경

이 문서는 Windows PowerShell 환경에서 repository 설치부터 Smoke Test, batch input generation, ODLD Explorer, GT Authoring, VLM client 실행까지 진행하기 위한 runbook이다.

- Python 3.10 이상
- Windows PowerShell
- repository root에서 명령 실행

> 이 문서의 명령은 PowerShell용이다. Bash 명령과 섞어 사용하지 않는다.

## 2. Python environment 설치

~~~powershell
python -m venv .venv-win
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv-win\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest
~~~

virtual environment가 활성화되면 prompt 앞에 (.venv-win)이 표시된다.

activation을 사용할 수 없는 환경에서는 virtual environment의 Python을 직접 실행한다.

~~~powershell
.\.venv-win\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv-win\Scripts\python.exe -m pytest
~~~

package를 editable install하지 않는 경우:

~~~powershell
$env:PYTHONPATH = "src"
~~~

VLM server dependency가 필요한 경우:

~~~powershell
python -m pip install -e ".[server]"
~~~

> VLM client는 Windows에서 실행할 수 있지만 local vLLM server 지원 환경은 별도로 확인한다.

## 3. Data / Output 환경변수

현재 PowerShell session에서 설정:

~~~powershell
$env:MS_ODD_DATA_ROOT = "D:\path\to\ms-odd-tagging-data\data"
$env:MS_ODD_OUTPUT_ROOT = "D:\path\to\ms-odd-tagging-data\outputs"
~~~

값 확인:

~~~powershell
$env:MS_ODD_DATA_ROOT
$env:MS_ODD_OUTPUT_ROOT
Get-ChildItem (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") -Directory
~~~

### 3.1 PowerShell에서 영구 설정

PowerShell profile을 연다.

~~~powershell
if (!(Test-Path $PROFILE)) {
    New-Item -ItemType File -Path $PROFILE -Force | Out-Null
}
notepad $PROFILE
~~~

profile file 마지막에 다음 내용을 추가한다.

~~~powershell
$env:MS_ODD_DATA_ROOT = "D:\path\to\ms-odd-tagging-data\data"
$env:MS_ODD_OUTPUT_ROOT = "D:\path\to\ms-odd-tagging-data\outputs"
~~~

저장 후 현재 terminal에 적용한다.

~~~powershell
. $PROFILE
~~~

새 PowerShell terminal에서는 자동으로 적용된다.

## 4. 입력 Recording 구조

~~~text
$env:MS_ODD_DATA_ROOT\01_raw\<RECORDING_ID>\
├── annotations_OD.json
├── annotations_LD.json
└── traj_lcs.txt
~~~

입력 directory 확인:

~~~powershell
$RECORDING = "<RECORDING_ID>"
Get-ChildItem (Join-Path $env:MS_ODD_DATA_ROOT "01_raw\$RECORDING")
~~~

## 5. Smoke Test

처음에는 recording 1개에서 frame input 1개만 생성한다.

~~~powershell
python run_pipeline.py <RECORDING_ID> --frame-limit 1
~~~

예시:

~~~powershell
python run_pipeline.py Rec_Drv_GER_MACHET18_20260319_151819 --frame-limit 1
~~~

확인 항목:

- Stage 1/2와 Stage 2/2가 error 없이 완료되었는지
- $env:MS_ODD_OUTPUT_ROOT\01_canonical에 canonical JSON이 생성되었는지
- $env:MS_ODD_OUTPUT_ROOT\02_frame_inputs에 frame input JSON과 BEV가 생성되었는지
- BEV에서 Ego, lane/road geometry, 주변 object가 정상적으로 표시되는지

~~~powershell
Get-ChildItem (Join-Path $env:MS_ODD_OUTPUT_ROOT "01_canonical") -File |
    Select-Object -First 10

Get-ChildItem (Join-Path $env:MS_ODD_OUTPUT_ROOT "02_frame_inputs") -File -Recurse |
    Select-Object -First 10
~~~

## 6. Input Generation 실행

기본 Frame Input / BEV sampling rate는 1 FPS이다.

### 6.1 Recording 1개 전체 실행

~~~powershell
python run_pipeline.py <RECORDING_ID>
~~~

예시:

~~~powershell
python run_pipeline.py Rec_Drv_GER_MACHET18_20260319_151819
~~~

2 FPS:

~~~powershell
python run_pipeline.py <RECORDING_ID> --frames-per-second 2
~~~

모든 canonical frame 생성:

~~~powershell
python run_pipeline.py <RECORDING_ID> --all-frames
~~~

기존 output을 이어서 사용:

~~~powershell
python run_pipeline.py <RECORDING_ID> --existing-output resume
~~~

기존 output을 재생성:

~~~powershell
python run_pipeline.py <RECORDING_ID> --existing-output regenerate
~~~

### 6.2 선택한 여러 Recording 실행

~~~powershell
python run_pipeline.py Rec_A Rec_B Rec_C --existing-output resume
~~~

### 6.3 이름순 앞의 10개 Recording 실행

~~~powershell
$recordings = Get-ChildItem (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") -Directory |
    Sort-Object Name |
    Select-Object -First 10

$recordings.Name
python run_pipeline.py $recordings.Name --existing-output resume
~~~

### 6.4 모든 Recording 실행

~~~powershell
$recordings = Get-ChildItem (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") -Directory |
    Sort-Object Name

$recordings.Name
python run_pipeline.py $recordings.Name --existing-output resume
~~~

필수 파일이 없거나 processing error가 발생한 recording은 skip되며 실행 마지막의 Failed Recordings와 runtime JSON에 기록된다.

Runtime log:

~~~powershell
Get-ChildItem (Join-Path $env:MS_ODD_OUTPUT_ROOT "runtime_logs")
~~~

## 7. Canonical만 생성

~~~powershell
python run_pipeline.py <RECORDING_ID> --stop-after canonical
~~~

결과:

~~~text
$env:MS_ODD_OUTPUT_ROOT\01_canonical
~~~

## 8. Rule-based Tagging 구성 확인

~~~powershell
python -m ms_odd_tagging.tagger.rule_based.registry --help
~~~

설정 파일:

~~~text
configs\direct_scenarios.yaml
~~~

새 scenario를 추가하거나 detector를 수정하기 전 enabled_scenarios와 각 threshold의 provenance를 확인한다.

## 9. Full ODLD Scenario Explorer

Explorer output:

~~~text
$env:MS_ODD_OUTPUT_ROOT\06_scenario_explorers/odld
~~~

### 9.1 Recording 1개

~~~powershell
$RECORDING = "<RECORDING_ID>"

python scripts/odld_explorer/generate_odld_dataset_explorers_w_scenario_tag.py `
  --source-root (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") `
  --canonical-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "01_canonical") `
  --output-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "06_scenario_explorers/odld") `
  --index-path (Join-Path $env:MS_ODD_OUTPUT_ROOT "06_scenario_explorers/odld\index.html") `
  --regenerate-existing `
  $RECORDING
~~~

### 9.2 Canonical 기준 이름순 앞의 10개

~~~powershell
$RECORDINGS = Get-ChildItem (Join-Path $env:MS_ODD_OUTPUT_ROOT "01_canonical") `
  -Filter "*_canonical_odld_frames.json" -File |
  Sort-Object Name |
  Select-Object -First 10 |
  ForEach-Object { $_.BaseName -replace '_canonical_odld_frames$', '' }

$RECORDINGS

python scripts/odld_explorer/generate_odld_dataset_explorers_w_scenario_tag.py `
  --source-root (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") `
  --canonical-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "01_canonical") `
  --output-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "06_scenario_explorers/odld") `
  --index-path (Join-Path $env:MS_ODD_OUTPUT_ROOT "06_scenario_explorers/odld\index.html") `
  --regenerate-existing `
  $RECORDINGS
~~~

11~20번째 recording은 다음 selection을 사용한다.

~~~powershell
Select-Object -Skip 10 -First 10
~~~

21~30번째 recording은 Select-Object -Skip 20 -First 10을 사용한다.

### 9.3 생성 가능한 모든 Recording

recording argument를 생략한다.

~~~powershell
python scripts/odld_explorer/generate_odld_dataset_explorers_w_scenario_tag.py `
  --source-root (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") `
  --canonical-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "01_canonical") `
  --output-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "06_scenario_explorers/odld") `
  --index-path (Join-Path $env:MS_ODD_OUTPUT_ROOT "06_scenario_explorers/odld\index.html") `
  --regenerate-existing
~~~

생성 후 다음 index를 browser에서 연다.

~~~text
$env:MS_ODD_OUTPUT_ROOT\06_scenario_explorers/odld\index.html
~~~

## 10. Integrated ODLD GT Authoring

먼저 Full ODLD Scenario Explorer를 생성해야 한다.

### 10.1 GT Authoring Explorer 생성

~~~powershell
python scripts/odld_explorer/add_gt_authoring_to_tagged_explorers.py `
  --source-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "06_scenario_explorers/odld") `
  --output-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "06_scenario_explorers/gt_authoring") `
  --frame-input-root (Join-Path $env:MS_ODD_OUTPUT_ROOT "02_frame_inputs") `
  --gt-dir (Join-Path $env:MS_ODD_DATA_ROOT "02_gt") `
  --regenerate-existing
~~~

특정 recording만 생성하려면 command 마지막에 RECORDING_ID를 추가한다.

### 10.2 Autosave Server 실행

~~~powershell
python scripts/odld_explorer/serve_gt_authoring_explorers.py `
  --directory (Join-Path $env:MS_ODD_OUTPUT_ROOT "06_scenario_explorers/gt_authoring") `
  --gt-dir (Join-Path $env:MS_ODD_DATA_ROOT "02_gt") `
  --host 127.0.0.1 `
  --port 8080
~~~

Browser:

~~~text
http://127.0.0.1:8080/index.html
~~~

GT output:

~~~text
$env:MS_ODD_DATA_ROOT\02_gt\<RECORDING_ID>_frame_gt.json
~~~

작업 중에는 server를 종료하지 않는다. 작업이 끝나면 Ctrl+C로 종료한다.

## 11. Local VLM Inference

VLM client:

~~~powershell
python -m ms_odd_tagging.tagger.model_based.local_vllm `
  --recording <RECORDING_ID> `
  --model-input-root (Join-Path $env:MS_ODD_OUTPUT_ROOT "02_frame_inputs") `
  --output-root (Join-Path $env:MS_ODD_OUTPUT_ROOT "03_tagging") `
  --endpoint http://127.0.0.1:8001/v1/chat/completions
~~~

Port 확인:

~~~powershell
Get-NetTCPConnection -LocalPort 8001 -ErrorAction SilentlyContinue
~~~

VLM은 optional이다. 먼저 deterministic rule pipeline을 확인한다.

## 12. CLI 확인

~~~powershell
python -m ms_odd_tagging.canonical.builder --help
python -m ms_odd_tagging.frame_inputs.builder --help
python -m ms_odd_tagging.validator.frame_schema --help
python -m ms_odd_tagging.tagger.rule_based.registry --help
python scripts/odld_explorer/generate_odld_dataset_explorers_w_scenario_tag.py --help
python scripts/odld_explorer/add_gt_authoring_to_tagged_explorers.py --help
python scripts/odld_explorer/serve_gt_authoring_explorers.py --help
~~~

## 13. 자주 발생하는 문제

### Bash syntax error near unexpected token

원인: Bash command를 PowerShell이 아닌 Bash terminal에서 실행해야 하거나, 반대로 PowerShell command를 Bash에서 실행했다.

PowerShell prompt는 일반적으로 PS로 시작한다.

~~~text
PS C:\path\to\ms-odd-tagging>
~~~

이 문서의 PowerShell command만 사용한다.

### Activate.ps1을 실행할 수 없음

현재 terminal session에서만 execution policy를 완화한다.

~~~powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv-win\Scripts\Activate.ps1
~~~

또는 activation 없이 다음처럼 직접 실행한다.

~~~powershell
.\.venv-win\Scripts\python.exe run_pipeline.py <RECORDING_ID> --frame-limit 1
~~~

### 환경변수가 비어 있음

~~~powershell
. $PROFILE
$env:MS_ODD_DATA_ROOT
$env:MS_ODD_OUTPUT_ROOT
~~~

### Port 8001이 이미 사용 중

~~~powershell
Get-NetTCPConnection -LocalPort 8001 -ErrorAction SilentlyContinue
~~~

process를 확인한 뒤 필요한 경우 해당 server를 정상 종료한다.
