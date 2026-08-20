# Setup and Run — Windows

## 1. 대상 환경

이 문서는 Windows PowerShell 환경에서 repository를 처음 clone한 뒤 현재 pipeline을 실행하기 위한 runbook이다.

- Python 3.10 이상
- Windows PowerShell
- repository root에서 명령 실행

## 2. Clone 및 branch 선택

~~~powershell
git clone https://github.com/livmeraki/ms-odd-tagging.git
Set-Location ms-odd-tagging
git switch refactor/repo-cleanup-20260813
git pull
~~~

## 3. Python environment 설치

~~~powershell
python -m venv .venv-win
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv-win\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
~~~

설치 확인:

~~~powershell
ms-odd-tagging --help
python -c "import ms_odd_tagging; print('ms_odd_tagging import OK')"
~~~

activation 없이 실행해야 하는 경우 package module을 직접 사용할 수 있다.

~~~powershell
.\.venv-win\Scripts\python.exe -m ms_odd_tagging.pipeline <RECORDING_ID> --frame-limit 1
~~~

## 4. Data / Output 환경변수

~~~powershell
$env:MS_ODD_DATA_ROOT = "D:\path\to\data"
$env:MS_ODD_OUTPUT_ROOT = "D:\path\to\outputs"
~~~

확인:

~~~powershell
$env:MS_ODD_DATA_ROOT
$env:MS_ODD_OUTPUT_ROOT
Get-ChildItem (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") -Directory
~~~

각 recording은 다음 파일을 포함해야 한다.

~~~text
$env:MS_ODD_DATA_ROOT\01_raw\<RECORDING_ID>\
├── annotations_OD.json
├── annotations_LD.json
└── traj_lcs.txt
~~~

## 5. Smoke Test

~~~powershell
ms-odd-tagging <RECORDING_ID> --frame-limit 1 --existing-output regenerate
~~~

확인 항목:

- canonicalization이 완료되는지
- `01_canonical`에 canonical JSON이 생성되는지
- `02_frame_inputs`에 `frame.json`과 `bev.png`가 생성되는지
- BEV의 Ego, lane/road geometry, 주변 object가 정상적으로 보이는지

~~~powershell
Get-ChildItem (Join-Path $env:MS_ODD_OUTPUT_ROOT "01_canonical") -File | Select-Object -First 10
Get-ChildItem (Join-Path $env:MS_ODD_OUTPUT_ROOT "02_frame_inputs") -File -Recurse | Select-Object -First 10
~~~

## 6. Pipeline 실행

Recording 1개:

~~~powershell
ms-odd-tagging <RECORDING_ID>
~~~

2 FPS:

~~~powershell
ms-odd-tagging <RECORDING_ID> --frames-per-second 2
~~~

모든 canonical frame:

~~~powershell
ms-odd-tagging <RECORDING_ID> --all-frames
~~~

기존 output 이어서 사용:

~~~powershell
ms-odd-tagging <RECORDING_ID> --existing-output resume
~~~

기존 output 재생성:

~~~powershell
ms-odd-tagging <RECORDING_ID> --existing-output regenerate
~~~

Canonical만 생성:

~~~powershell
ms-odd-tagging <RECORDING_ID> --stop-after canonical
~~~

여러 recording:

~~~powershell
ms-odd-tagging Rec_A Rec_B Rec_C --existing-output resume
~~~

모든 recording:

~~~powershell
$recordings = Get-ChildItem (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") -Directory | Sort-Object Name
$recordings.Name
ms-odd-tagging $recordings.Name --existing-output resume
~~~

Runtime log:

~~~powershell
Get-ChildItem (Join-Path $env:MS_ODD_OUTPUT_ROOT "runtime_logs")
~~~

## 7. 개별 Stage CLI

~~~powershell
ms-odd-canonical --help
ms-odd-frame-inputs --help
ms-odd-rules --help
ms-odd-ld-topology --help
~~~

LD topology는 repository root의 별도 wrapper가 아니라 package CLI로 실행한다.

## 8. Full ODLD Scenario Explorer

~~~powershell
python scripts/odld_explorer/generate_odld_dataset_explorers_w_scenario_tag.py `
  --source-root (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") `
  --canonical-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "01_canonical") `
  --output-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "06_scenario_explorers/odld") `
  --index-path (Join-Path $env:MS_ODD_OUTPUT_ROOT "06_scenario_explorers/odld\index.html") `
  --regenerate-existing
~~~

## 9. Simplified Taxonomy GT Workspace

~~~powershell
python -m ms_odd_tagging.simplified_taxonomy.gt_workspace_profiled `
  --frame-root (Join-Path $env:MS_ODD_OUTPUT_ROOT "02_frame_inputs") `
  --gt-root (Join-Path $env:MS_ODD_OUTPUT_ROOT "06_gt_comparison/gt") `
  --source-hz 10 `
  --sample-hz 1 `
  --host 127.0.0.1 `
  --port 8765
~~~

Browser:

~~~text
http://127.0.0.1:8765
~~~

## 10. VLM

~~~powershell
ms-odd-qwen-vlm-poc --help
~~~

Local endpoint 확인:

~~~powershell
Get-NetTCPConnection -LocalPort 8001 -ErrorAction SilentlyContinue
~~~

VLM candidate/evidence/inference 구조는 `02_PIPELINE.md`를 참고한다.

## 11. Test

~~~powershell
python -m pytest
~~~
