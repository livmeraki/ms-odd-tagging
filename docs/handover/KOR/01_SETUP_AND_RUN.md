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

다음 설치 명령은 Linux/macOS와 Windows에서 동일하다.

```bash
python -m pip install -e ".[server]"
```

Lanelet2 PoC는 Linux에서만 optional dependency로 제공된다.

## 4. 데이터 / 출력 경로

기본 repository 구조:

```text
data/01_raw
  -> outputs/01_canonical
  -> outputs/02_frame_inputs
  -> outputs/04_tagging
  -> outputs/05_validation
  -> outputs/06_gt_comparison
```

대용량 데이터를 외부 disk에 둘 경우 `.env` 또는 환경변수를 사용한다.

Linux/macOS:

```bash
export MS_ODD_DATA_ROOT=/path/to/ms-odd-tagging-data/data
export MS_ODD_OUTPUT_ROOT=/path/to/ms-odd-tagging-data/outputs
```

Windows PowerShell:

```powershell
$env:MS_ODD_DATA_ROOT = "D:\path\to\ms-odd-tagging-data\data"
$env:MS_ODD_OUTPUT_ROOT = "D:\path\to\ms-odd-tagging-data\outputs"
```

> 위 환경변수 설정은 현재 terminal session에만 적용된다. 새 terminal을 열면 다시 설정해야 한다.

machine-specific path를 source code에 hard-code하지 않는다.

## 5. 입력 recording 준비

OD+LD pipeline을 사용할 recording에는 최소 다음 파일이 필요하다.

```text
<recording>/
├── annotations_OD.json
├── annotations_LD.json
└── traj_lcs.txt
```

실제 raw directory layout은 `data/README.md`와 input generator의 loader를 함께 확인한다.

## 6. 첫 실행: Smoke Test

처음에는 전체 recording을 처리하지 말고, **recording 1개에서 frame input 1개만 생성하여 setup과 입력 경로가 정상인지 확인**한다.

Smoke Test에서 실제로 실행되는 순서는 다음과 같다.

```text
Raw Recording
     │
     ▼
① Canonicalization
     │
     ▼
outputs/01_canonical
     │
     ▼
② Frame Input / BEV 생성 (1 frame)
     │
     ▼
outputs/02_frame_inputs
```

즉, Smoke Test는 별도의 pipeline 단계가 아니라 **Canonicalization + Frame Input/BEV 생성까지 한 번에 확인하는 최소 실행**이다.

Linux/macOS:

```bash
python run_pipeline.py <RECORDING_ID> \
  --frame-limit 1
```

Windows PowerShell:

```powershell
python run_pipeline.py <RECORDING_ID> --frame-limit 1
```

예시 — Linux/macOS:

```bash
python run_pipeline.py Rec_Drv_GER_MACHET18_20260319_151819 \
  --frame-limit 1
```

예시 — Windows PowerShell:

```powershell
python run_pipeline.py Rec_Drv_GER_MACHET18_20260319_151819 --frame-limit 1
```

### Smoke Test 결과 확인

다음 네 가지만 확인한다.

- `Stage 1/2`, `Stage 2/2`가 error 없이 완료되었는지
- `outputs/01_canonical/`에 해당 recording의 canonical JSON이 생성되었는지
- `outputs/02_frame_inputs/`에 frame input JSON과 BEV가 1개 이상 생성되었는지
- BEV를 열었을 때 Ego, lane/road geometry, 주변 object가 정상적으로 표시되는지

위 항목이 정상이라면 전체 Recording 실행으로 진행한다.

## 7. 전체 Recording 실행

Smoke Test가 정상적으로 완료되었다면, 같은 recording 전체에 대해 input generation을 실행한다.

전체 실행 범위는 다음과 같다.

```text
Raw Recording
     │
     ▼
① Canonicalization
     │
     ▼
outputs/01_canonical
     │
     ▼
② Frame Input / BEV 생성
     │
     ▼
outputs/02_frame_inputs
```

기본 Frame Input / BEV sampling rate는 **1 FPS**이다.

> **관찰된 실행 시간:** 현재 Windows 로컬 환경에서 약 1분 길이 recording 1개를 기본 1 FPS로 처리할 때, Canonicalization + Frame Input / BEV 생성까지 대략 **30~40초/recording**이 소요되었다. 실행 시간은 hardware, recording 길이, object/LD 복잡도, cache 및 기존 output 상태에 따라 달라질 수 있다. 실제 측정값은 실행 종료 시 Runtime Summary와 `outputs/runtime_logs/`의 JSON log에서 확인한다.

### Recording 1개 전체 실행

Linux/macOS:

```bash
python run_pipeline.py <RECORDING_ID>
```

Windows PowerShell:

```powershell
python run_pipeline.py <RECORDING_ID>
```

예시:

```powershell
python run_pipeline.py Rec_Drv_GER_MACHET18_20260319_151819
```

2 FPS로 생성하려면:

```bash
python run_pipeline.py <RECORDING_ID> --frames-per-second 2
```

모든 canonical frame에 대해 Frame Input / BEV를 생성하려면:

```bash
python run_pipeline.py <RECORDING_ID> --all-frames
```

### Data folder의 모든 Recording 실행

앞에서 `MS_ODD_DATA_ROOT`, `MS_ODD_OUTPUT_ROOT`를 설정했다면 같은 환경변수를 그대로 사용한다.

예를 들어 Windows PowerShell에서 다음과 같이 설정했다고 가정한다.

```powershell
$env:MS_ODD_DATA_ROOT = "D:\path\to\ms-odd-tagging-data\data"
$env:MS_ODD_OUTPUT_ROOT = "D:\path\to\ms-odd-tagging-data\outputs"
```

이 경우 모든 raw recording은 `$env:MS_ODD_DATA_ROOT\01_raw`에서 읽고, 결과는 자동으로 `$env:MS_ODD_OUTPUT_ROOT` 아래에 생성된다. 별도로 `--source-root`, `--output-root`를 지정할 필요가 없다.

Windows PowerShell:

```powershell
Get-ChildItem (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") -Directory | ForEach-Object {
    python run_pipeline.py $_.Name --existing-output resume
}
```

Linux/macOS:

```bash
for recording in "$MS_ODD_DATA_ROOT"/01_raw/*/; do
  python run_pipeline.py "$(basename "$recording")" --existing-output resume
done
```

환경변수를 설정하지 않은 경우 기본값인 repository의 `data/01_raw/`와 `outputs/`가 사용된다.

> Batch 실행에서는 기존 output이 있는 recording마다 prompt가 뜨지 않도록 `--existing-output resume`를 사용한다. 전체 실행 전 recording 1개로 Smoke Test를 먼저 완료하는 것을 권장한다.

### 전체 실행 후 확인

- `Stage 1/2`, `Stage 2/2`가 error 없이 완료되었는지 확인
- `outputs/01_canonical/`에 recording 전체 canonical 결과가 생성되었는지 확인
- `outputs/02_frame_inputs/`에 설정한 sampling rate에 맞는 frame input / BEV가 생성되었는지 확인
- 일부 frame의 JSON과 BEV를 열어 Ego, road geometry, 주변 object 위치가 정상인지 확인

> `run_pipeline.py`의 전체 실행은 현재 **input generation pipeline 전체 실행**을 의미한다.  
> Rule-based tagging, Scenario Explorer, Frame GT Reviewer, VLM은 이후 필요에 따라 별도로 사용한다.

---

## 8. 필요할 때 사용하는 추가 기능

아래 항목은 **8.1 → 8.2 → 8.3 순서로 실행하는 pipeline이 아니다.**  
전체 Recording 실행 이후 개발 목적에 따라 필요한 기능만 선택해서 사용한다.

| 하고 싶은 작업 | 사용할 기능 |
|---|---|
| Frame Input 없이 Canonical 결과만 생성 | Canonical만 생성 |
| Rule scenario 구성 및 detector 확인 | Rule-based Tagging 구성 확인 |
| 결과를 시각적으로 확인 | Scenario Explorer |
| Ground Truth 작성 / 검토 | Frame GT Reviewer |
| VLM 실험 실행 | Local VLM Inference |

### 8.1 Canonical만 생성

**Frame Input / BEV 없이 canonicalization 결과만 필요할 때** 사용하는 선택 명령이다.

Linux/macOS:

```bash
python run_pipeline.py <RECORDING_ID> \
  --stop-after canonical
```

Windows PowerShell:

```powershell
python run_pipeline.py <RECORDING_ID> --stop-after canonical
```

결과:

```text
outputs/01_canonical/
```

### 8.2 Rule-based Tagging 구성 확인

현재 rule registry와 사용 가능한 option을 확인할 때 사용한다.

```bash
python -m ms_odd_tagging.tagger.rule_based.registry --help
```

설정 파일은 기본적으로 다음을 사용한다.

```text
configs/direct_scenarios.yaml
```

새 scenario를 추가하거나 detector를 수정하기 전에는 `enabled_scenarios`와 각 threshold의 `provenance`를 확인한다.

Rule / Geometry algorithm의 상세 내용은 `05_ALGORITHMS.md`를 확인한다.

### 8.3 Scenario Explorer

**Canonical / tagging 결과를 시각적으로 확인하고 디버깅할 때** 사용하는 별도 visualization tool이다.

Linux/macOS:

```bash
python -m ms_odd_tagging.visualization.scenario_explorer \
  outputs/01_canonical \
  --output-dir outputs/07_scenario_explorers
```

Windows PowerShell:

```powershell
python -m ms_odd_tagging.visualization.scenario_explorer outputs/01_canonical --output-dir outputs/07_scenario_explorers
```

rule 결과가 이상할 경우 숫자만 확인하지 말고 explorer에서 OD / LD / Ego Trajectory를 함께 시각적으로 확인하는 것을 권장한다.

### 8.4 Frame GT Reviewer

**자동 tagging 결과와 비교할 Ground Truth를 작성하거나 검토할 때** 사용하는 별도 tool이다.

Linux/macOS:

```bash
python -m ms_odd_tagging.gt_comparison.authoring \
  --frame-input-root outputs/02_frame_inputs_revised \
  --output-root outputs/frame_gt_authoring \
  --all
```

Windows PowerShell:

```powershell
python -m ms_odd_tagging.gt_comparison.authoring --frame-input-root outputs/02_frame_inputs_revised --output-root outputs/frame_gt_authoring --all
```

생성 후 다음 파일을 browser에서 연다.

```text
outputs/frame_gt_authoring/index.html
```

을 browser에서 연다.

현재 reviewer는 exact source frame의 BEV를 사용하며 legacy motional window 방식은 active pipeline에서 사용하지 않는다.

### 8.5 Local VLM Inference

VLM PoC가 필요한 경우에만 사용한다.

Linux/macOS:

```bash
python -m ms_odd_tagging.tagger.model_based.local_vllm \
  --recording <RECORDING_ID> \
  --model-input-root outputs/02_frame_inputs \
  --output-root outputs/04_tagging \
  --endpoint http://127.0.0.1:8001/v1/chat/completions
```

Windows PowerShell:

```powershell
python -m ms_odd_tagging.tagger.model_based.local_vllm --recording <RECORDING_ID> --model-input-root outputs/02_frame_inputs --output-root outputs/04_tagging --endpoint http://127.0.0.1:8001/v1/chat/completions
```

> 위 client 명령 자체는 Windows에서도 실행할 수 있지만, local vLLM server의 지원 환경은 별도로 확인해야 한다.

VLM 기능은 optional이며, deterministic rule pipeline을 먼저 확인한 뒤 사용한다.

## 9. 개별 Stage / CLI 확인

각 module의 command option을 직접 확인하려면 다음 명령을 사용한다.

```bash
python -m ms_odd_tagging.canonical.builder --help
python -m ms_odd_tagging.frame_inputs.builder --help
python -m ms_odd_tagging.validator.frame_schema --help
python -m ms_odd_tagging.tagger.rule_based.registry --help
python -m ms_odd_tagging.visualization.scenario_explorer --help
```

위 명령은 Linux/macOS와 Windows PowerShell에서 동일하다.

## 10. 실행 전 / 문제 발생 시 체크리스트

- Python 3.10+인지 확인
- Windows에서는 PowerShell 사용 권장
- package install 또는 `PYTHONPATH=src` 설정
- recording에 OD/LD/trajectory가 모두 있는지 확인
- external data root 환경변수 확인
- `python -m pytest` 실행 후 failure가 있으면 설치 문제인지 known code/test issue인지 구분해서 확인
- 첫 실행은 `--frame-limit 1` Smoke Test부터 수행
- Smoke Test 성공 후 전체 Recording 실행
- 이후 필요한 추가 기능만 선택해서 실행
- output을 Git에 commit하지 않기
