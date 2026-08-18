# Setup and Run

## 1. 목적

이 문서는 새 담당자가 repository를 받아 **환경을 설치하고 recording 1개를 실제로 실행하는 것**까지 빠르게 진행할 수 있도록 정리한 runbook이다.

## 2. 기본 환경

현재 package는 Python 3.10 이상을 요구한다.

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

package를 editable install하지 않을 경우 `PYTHONPATH=src`를 설정해야 한다.

Linux/macOS:

```bash
export PYTHONPATH=src
```

PowerShell:

```powershell
$env:PYTHONPATH = "src"
```

## 3. 주요 dependency

`pyproject.toml` 기준 기본 dependency는 Pillow이며, 개발 환경에는 pytest가 포함된다. VLM server를 사용할 경우 `server` optional dependency에 vLLM, tokenizers, numpy, sympy, networkx 등이 정의되어 있다.

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

```bash
export MS_ODD_DATA_ROOT=/path/to/ms-odd-tagging-data/data
export MS_ODD_OUTPUT_ROOT=/path/to/ms-odd-tagging-data/outputs
```

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

## 6. 가장 빠른 Smoke Test

OD+LD recording 1개를 canonicalize하고 frame input 1개만 생성:

```bash
python run_pipeline.py <RECORDING_ID> \
  --odld \
  --frame-limit 1
```

예시:

```bash
python run_pipeline.py Rec_Drv_GER_MACHET18_20260319_151819 \
  --odld \
  --frame-limit 1
```

> 주의: 현재 `run_pipeline.py` CLI는 `--odld`를 사용한다. 과거 실험 command에 존재했던 다른 canonical mode 이름과 혼동하지 말고 현재 `--help`를 source of truth로 사용한다.

## 7. Canonical만 생성

```bash
python run_pipeline.py <RECORDING_ID> \
  --odld \
  --stop-after canonical
```

결과는 기본적으로 다음 위치에 생성된다.

```text
outputs/01_canonical/
```

## 8. Frame Input / BEV 생성

기본 sampling rate는 1 FPS이다.

```bash
python run_pipeline.py <RECORDING_ID> --odld
```

2 FPS:

```bash
python run_pipeline.py <RECORDING_ID> --odld --frames-per-second 2
```

모든 canonical frame에 대해 생성:

```bash
python run_pipeline.py <RECORDING_ID> --odld --all-frames
```

중요한 점은 **BEV/model input이 1 FPS로 sampling되더라도 dynamic rule tagging 자체는 전체 canonical frame을 사용할 수 있다는 것**이다.

## 9. Rule-based Tagging

현재 rule registry CLI 확인:

```bash
python -m ms_odd_tagging.tagger.rule_based.registry --help
```

설정 파일은 기본적으로 다음을 사용한다.

```text
configs/direct_scenarios.yaml
```

새 담당자는 실행 전에 반드시 `enabled_scenarios`와 각 threshold의 `provenance`를 확인한다. `provisional`, `engineering_default`, `poc_requires_calibration` 값은 검증 수준이 다름을 의미한다.

## 10. Scenario Explorer

canonical 또는 raw trajectory 기반 standalone explorer 생성:

```bash
python -m ms_odd_tagging.visualization.scenario_explorer \
  outputs/01_canonical \
  --output-dir outputs/07_scenario_explorers
```

rule 결과가 이상할 경우 숫자만 보지 말고 explorer에서 OD/LD/ego trajectory를 함께 시각적으로 확인하는 것을 권장한다.

## 11. Frame GT Reviewer

```bash
python -m ms_odd_tagging.gt_comparison.authoring \
  --frame-input-root outputs/02_frame_inputs_revised \
  --output-root outputs/frame_gt_authoring \
  --all
```

생성 후:

```text
outputs/frame_gt_authoring/index.html
```

을 browser에서 연다.

현재 reviewer는 exact source frame의 BEV를 사용하며 legacy motional window 방식은 active pipeline에서 사용하지 않는다.

## 12. Local VLM Inference

OpenAI-compatible vLLM endpoint 사용 예:

```bash
python -m ms_odd_tagging.tagger.model_based.local_vllm \
  --recording <RECORDING_ID> \
  --model-input-root outputs/02_frame_inputs \
  --output-root outputs/04_tagging \
  --endpoint http://127.0.0.1:8001/v1/chat/completions
```

VLM 기능은 optional이며, deterministic rule pipeline을 먼저 확인한 뒤 사용한다.

## 13. 개별 Stage 확인

```bash
python -m ms_odd_tagging.input_generator.canonical --help
python -m ms_odd_tagging.input_generator.canonical_odld --help
python -m ms_odd_tagging.input_generator.frame_input --help
python -m ms_odd_tagging.validator.frame_schema --help
python -m ms_odd_tagging.tagger.rule_based.registry --help
python -m ms_odd_tagging.visualization.scenario_explorer --help
```

## 14. 실행 전 체크리스트

- Python 3.10+인지 확인
- package install 또는 `PYTHONPATH=src` 설정
- recording에 OD/LD/trajectory가 모두 있는지 확인
- external data root 환경변수 확인
- `python -m pytest` 통과 여부 확인
- smoke test는 `--frame-limit 1`부터 수행
- output을 Git에 commit하지 않기
