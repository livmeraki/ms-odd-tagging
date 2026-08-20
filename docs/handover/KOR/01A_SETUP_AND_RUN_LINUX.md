# Setup and Run — Linux

이 문서는 Linux Bash 환경에서 cleanup branch의 **현재 경로만** 실행하기 위한 runbook이다.

## 1. Clone / branch

```bash
git clone https://github.com/livmeraki/ms-odd-tagging.git
cd ms-odd-tagging
git switch refactor/repo-cleanup-20260813
git pull
```

## 2. Python environment

Python 3.10 이상을 사용한다.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

설치 확인:

```bash
ms-odd-tagging --help
python -c "import ms_odd_tagging; print('ms_odd_tagging import OK')"
```

## 3. Data / output root

```bash
export MS_ODD_DATA_ROOT="/absolute/path/to/data"
export MS_ODD_OUTPUT_ROOT="/absolute/path/to/outputs"
```

각 recording은 다음 세 파일을 가진다.

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

`02_frame_inputs` 아래 sampled frame마다 `frame.json`과 `bev.png`가 생성되어야 한다.

## 5. Normal pipeline

```bash
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

```bash
mapfile -t RECORDINGS < <(
  find "$MS_ODD_DATA_ROOT/01_raw" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort
)
ms-odd-tagging "${RECORDINGS[@]}" --existing-output resume
```

## 6. Current CLIs

```bash
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

```bash
python scripts/odld_explorer/generate_odld_dataset_explorers_w_stage_progress.py \
  --source-root "$MS_ODD_DATA_ROOT/01_raw" \
  --canonical-dir "$MS_ODD_OUTPUT_ROOT/01_canonical" \
  --output-dir "$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers" \
  --regenerate-existing
```

## 8. Simplified Taxonomy GT Workspace

```bash
ms-odd-gt-workspace \
  --frame-root "$MS_ODD_OUTPUT_ROOT/02_frame_inputs" \
  --gt-root "$MS_ODD_OUTPUT_ROOT/06_gt_comparison/gt" \
  --source-hz 10 \
  --sample-hz 1 \
  --host 127.0.0.1 \
  --port 8765
```

Browser: `http://127.0.0.1:8765`

## 9. Qwen VLM

```bash
ms-odd-qwen-vlm --help
lsof -i :8001
```

VLM은 전체 frame을 직접 분류하는 기본 경로가 아니라 candidate/episode가 생성된 뒤 필요한 구간에 적용한다.

## 10. Test

```bash
python -m pytest
```
