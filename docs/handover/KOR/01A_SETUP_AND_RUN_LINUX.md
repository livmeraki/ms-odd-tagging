# Setup and Run — Linux

## 1. Clone

```bash
git clone https://github.com/livmeraki/ms-odd-tagging.git
cd ms-odd-tagging
git switch refactor/repo-cleanup-20260813
git pull
```

## 2. Environment

Python 3.10 이상을 사용한다.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

```bash
ms-odd-tagging --help
```

## 3. Data / output

```bash
export MS_ODD_DATA_ROOT="/absolute/path/to/data"
export MS_ODD_OUTPUT_ROOT="/absolute/path/to/outputs"
```

```text
$MS_ODD_DATA_ROOT/01_raw/<RECORDING_ID>/
├── annotations_OD.json
├── annotations_LD.json
└── traj_lcs.txt
```

## 4. Smoke test

```bash
ms-odd-tagging <RECORDING_ID> \
  --frame-limit 1 \
  --existing-output regenerate
```

확인:

```bash
find "$MS_ODD_OUTPUT_ROOT/01_canonical" -maxdepth 1 -type f | head
find "$MS_ODD_OUTPUT_ROOT/02_frame_inputs" -type f | head
```

## 5. Pipeline

```bash
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

```bash
mapfile -t RECORDINGS < <(
  find "$MS_ODD_DATA_ROOT/01_raw" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort
)
ms-odd-tagging "${RECORDINGS[@]}" --existing-output resume
```

## 6. Commands

```bash
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

```bash
python scripts/odld_explorer/generate.py \
  --source-root "$MS_ODD_DATA_ROOT/01_raw" \
  --canonical-dir "$MS_ODD_OUTPUT_ROOT/01_canonical" \
  --output-dir "$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers" \
  --index-path "$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers/index.html" \
  --regenerate-existing
```

## 8. GT Workspace

```bash
ms-odd-gt \
  --frame-root "$MS_ODD_OUTPUT_ROOT/02_frame_inputs" \
  --gt-root "$MS_ODD_OUTPUT_ROOT/06_gt_comparison/gt" \
  --source-hz 10 \
  --sample-hz 1 \
  --host 127.0.0.1 \
  --port 8765
```

Browser: `http://127.0.0.1:8765`

## 9. VLM

로컬 vLLM server가 `8001` port에서 실행 중이어야 실제 inference가 가능하다.

```bash
lsof -i :8001
ms-odd-vlm --help
```

## 10. Test

```bash
python -m pytest
```
