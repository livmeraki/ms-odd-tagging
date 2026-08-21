# Setup and Run — Windows

Windows PowerShell 기준 실행 방법이다.

## 1. Clone

```powershell
git clone https://github.com/livmeraki/ms-odd-tagging.git
Set-Location ms-odd-tagging
git switch refactor/repo-cleanup-20260813
git pull
```

## 2. Environment

Python 3.10 이상을 사용한다.

```powershell
python -m venv .venv-win
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv-win\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

```powershell
ms-odd-tagging --help
```

## 3. Data / output

```powershell
$env:MS_ODD_DATA_ROOT = "D:\path\to\data"
$env:MS_ODD_OUTPUT_ROOT = "D:\path\to\outputs"
```

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

## 5. Pipeline

```powershell
# 1 FPS
ms-odd-tagging <RECORDING_ID>

# 2 FPS
ms-odd-tagging <RECORDING_ID> --frames-per-second 2

# all frames
ms-odd-tagging <RECORDING_ID> --all-frames

# reuse output
ms-odd-tagging <RECORDING_ID> --existing-output resume

# regenerate
ms-odd-tagging <RECORDING_ID> --existing-output regenerate

# canonical only
ms-odd-tagging <RECORDING_ID> --stop-after canonical
```

모든 recording:

```powershell
$recordings = Get-ChildItem (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") -Directory | Sort-Object Name
ms-odd-tagging $recordings.Name --existing-output resume
```

## 6. Commands

```powershell
ms-odd-canonical --help
ms-odd-frames --help
ms-odd-rules --help
ms-odd-lane --help
ms-odd-topology --help
ms-odd-vlm --help
ms-odd-gt --help
ms-odd-validate --help
```

## 7. ODLD Explorer

```powershell
python scripts/odld_explorer/generate.py `
  --source-root (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") `
  --canonical-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "01_canonical") `
  --output-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "07_odld_scenario_explorers") `
  --index-path (Join-Path $env:MS_ODD_OUTPUT_ROOT "07_odld_scenario_explorers\index.html") `
  --regenerate-existing
```

## 8. GT Workspace

```powershell
ms-odd-gt `
  --frame-root (Join-Path $env:MS_ODD_OUTPUT_ROOT "02_frame_inputs") `
  --gt-root (Join-Path $env:MS_ODD_OUTPUT_ROOT "06_gt_comparison\gt") `
  --source-hz 10 `
  --sample-hz 1 `
  --host 127.0.0.1 `
  --port 8765
```

직접 module로 실행할 경우:

```powershell
python -m ms_odd_tagging.gt.workspace `
  --frame-root (Join-Path $env:MS_ODD_OUTPUT_ROOT "02_frame_inputs") `
  --gt-root (Join-Path $env:MS_ODD_OUTPUT_ROOT "06_gt_comparison\gt") `
  --source-hz 10 `
  --sample-hz 1 `
  --host 127.0.0.1 `
  --port 8765
```

Browser: `http://127.0.0.1:8765`

## 9. VLM on Windows

Native Windows에서는 candidate 생성, BEV/evidence 생성, VLM client 실행이 가능하다.

```powershell
ms-odd-vlm `
  --recording <RECORDING_ID> `
  --scenario on_intersection `
  --candidate-only
```

Local inference server는 vLLM을 사용하므로 native Windows에서 실행하지 않는다. 실제 inference는 Linux, WSL2 Linux 또는 별도 Linux GPU server에서 vLLM을 실행하고 Windows client가 해당 endpoint를 호출한다.

```powershell
ms-odd-vlm `
  --recording <RECORDING_ID> `
  --scenario on_intersection `
  --endpoint "http://<LINUX_HOST>:8001/v1/chat/completions"
```

연결 확인:

```powershell
Test-NetConnection <LINUX_HOST> -Port 8001
```

## 10. Test

```powershell
python -m pytest
```
