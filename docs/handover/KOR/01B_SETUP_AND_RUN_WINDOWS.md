# Setup and Run — Windows

이 문서는 Windows PowerShell 환경에서 cleanup branch의 **현재 경로만** 실행하기 위한 runbook이다.

## 1. Clone / branch

```powershell
git clone https://github.com/livmeraki/ms-odd-tagging.git
Set-Location ms-odd-tagging
git switch refactor/repo-cleanup-20260813
git pull
```

## 2. Python environment

Python 3.10 이상을 사용한다.

```powershell
python -m venv .venv-win
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv-win\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

설치 확인:

```powershell
ms-odd-tagging --help
python -c "import ms_odd_tagging; print('ms_odd_tagging import OK')"
```

activation 없이 실행할 경우:

```powershell
.\.venv-win\Scripts\python.exe -m ms_odd_tagging.pipeline <RECORDING_ID> --frame-limit 1
```

## 3. Data / output root

```powershell
$env:MS_ODD_DATA_ROOT = "D:\path\to\data"
$env:MS_ODD_OUTPUT_ROOT = "D:\path\to\outputs"
```

각 recording은 다음 세 파일을 가진다.

```text
$env:MS_ODD_DATA_ROOT\01_raw\<RECORDING_ID>\
├── annotations_OD.json
├── annotations_LD.json
└── traj_lcs.txt
```

## 4. Smoke test

```powershell
ms-odd-tagging <RECORDING_ID> --frame-limit 1 --existing-output regenerate
```

확인:

```powershell
Get-ChildItem (Join-Path $env:MS_ODD_OUTPUT_ROOT "01_canonical") -File | Select-Object -First 10
Get-ChildItem (Join-Path $env:MS_ODD_OUTPUT_ROOT "02_frame_inputs") -File -Recurse | Select-Object -First 10
```

`02_frame_inputs` 아래 sampled frame마다 `frame.json`과 `bev.png`가 생성되어야 한다.

## 5. Normal pipeline

```powershell
# 1 FPS (default)
ms-odd-tagging <RECORDING_ID>

# 2 FPS
ms-odd-tagging <RECORDING_ID> --frames-per-second 2

# all canonical frames
ms-odd-tagging <RECORDING_ID> --all-frames

# reuse existing outputs
ms-odd-tagging <RECORDING_ID> --existing-output resume

# regenerate
ms-odd-tagging <RECORDING_ID> --existing-output regenerate

# canonical only
ms-odd-tagging <RECORDING_ID> --stop-after canonical
```

모든 recording을 실행할 때:

```powershell
$recordings = Get-ChildItem (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") -Directory | Sort-Object Name
ms-odd-tagging $recordings.Name --existing-output resume
```

## 6. Current CLIs

```powershell
ms-odd-tagging --help
ms-odd-canonical --help
ms-odd-frame-inputs --help
ms-odd-rules --help
ms-odd-following-lane --help
ms-odd-ld-topology --help
ms-odd-qwen-vlm --help
ms-odd-gt-workspace --help
ms-odd-validate-frames --help
```

## 7. Full ODLD Scenario Explorer

권장 runner는 stage별 진행 상황을 출력하는 `generate_odld_dataset_explorers_w_stage_progress.py`이다.

```powershell
python scripts/odld_explorer/generate_odld_dataset_explorers_w_stage_progress.py `
  --source-root (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") `
  --canonical-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "01_canonical") `
  --output-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "07_odld_scenario_explorers") `
  --index-path (Join-Path $env:MS_ODD_OUTPUT_ROOT "07_odld_scenario_explorers\index.html") `
  --regenerate-existing
```

## 8. Simplified Taxonomy GT Workspace

현재 GT Workspace entry point는 `ms-odd-gt-workspace`이다.

```powershell
ms-odd-gt-workspace `
  --frame-root (Join-Path $env:MS_ODD_OUTPUT_ROOT "02_frame_inputs") `
  --gt-root (Join-Path $env:MS_ODD_OUTPUT_ROOT "06_gt_comparison\gt") `
  --source-hz 10 `
  --sample-hz 1 `
  --host 127.0.0.1 `
  --port 8765
```

직접 Python module로 실행해야 한다면:

```powershell
python -m ms_odd_tagging.simplified_taxonomy.gt_workspace `
  --frame-root (Join-Path $env:MS_ODD_OUTPUT_ROOT "02_frame_inputs") `
  --gt-root (Join-Path $env:MS_ODD_OUTPUT_ROOT "06_gt_comparison\gt") `
  --source-hz 10 `
  --sample-hz 1 `
  --host 127.0.0.1 `
  --port 8765
```

Browser: `http://127.0.0.1:8765`

## 9. Qwen VLM on Windows

### Native Windows에서 가능한 부분

Windows에서도 다음은 실행할 수 있다.

- VLM candidate generation
- BEV/evidence bundle generation
- `ms-odd-qwen-vlm` client 실행
- Linux/WSL2/remote machine에서 실행 중인 OpenAI-compatible VLM endpoint 호출

예를 들어 inference 없이 candidate까지만 확인할 수 있다.

```powershell
ms-odd-qwen-vlm `
  --recording <RECORDING_ID> `
  --scenario on_intersection `
  --candidate-only
```

### Native Windows에서 지원하지 않는 부분

이 repository의 local VLM server는 `vLLM`을 사용하며, **vLLM server를 native Windows에서 실행하는 것은 지원 대상이 아니다.**

따라서 Windows에서 실제 VLM inference를 수행하려면 다음 중 하나를 사용한다.

1. Linux machine에서 vLLM server 실행
2. Windows의 WSL2 Linux 환경에서 vLLM server 실행
3. 별도 Linux GPU server의 OpenAI-compatible endpoint 사용

Windows에서는 client만 실행하고 Linux endpoint를 지정할 수 있다.

```powershell
ms-odd-qwen-vlm `
  --recording <RECORDING_ID> `
  --scenario on_intersection `
  --endpoint "http://<LINUX_HOST>:8001/v1/chat/completions"
```

endpoint 연결 확인 예:

```powershell
Test-NetConnection <LINUX_HOST> -Port 8001
```

`127.0.0.1:8001`을 사용하는 경우에는 같은 Windows host에서 접근 가능한 WSL2 또는 forwarding된 VLM server가 실제로 실행 중이어야 한다.

VLM은 모든 frame을 직접 분류하지 않고, Rule / Geometry 단계에서 생성된 candidate/episode에 필요한 evidence를 구성한 뒤 선택적으로 inference한다.

## 10. Test

```powershell
python -m pytest
```
