# MS ODD Tagging

Repository for the autonomous-driving ODD scenario tagging pipeline.

This repo keeps the following core pipeline shape:

```text
OD annotations + ego trajectory
  -> canonical frame JSON
  -> overlapping 5-second windows
  -> refined.json + BEV keyframes
  -> local/server vLLM inference
  -> schema validation
  -> optional GT comparison
```

## Layout

- `src/ms_odd_tagging/`: reusable pipeline code.
- `scripts/`: thin CLI entry points.
- `prompts/`: model prompt templates.
- `schemas/`: model output schema.
- `configs/`: example configuration only.
- `tests/fixtures/`: small test/GT fixtures.
- `data/`: local data mount point; raw/private data is ignored.
- `outputs/`: generated outputs; ignored except `outputs/README.md`.

## Install

```bash
cd /path/to/ms-odd-tagging
python -m pip install -e ".[dev]"
```

If you do not install the package, prefix commands with `PYTHONPATH=src`.

## Build Inputs For One Recording

```bash
cd /path/to/ms-odd-tagging

PYTHONPATH=src python scripts/build_canonical_od_json.py \
  --source-root /path/to/2600_MV2_OD_traj_annotations \
  --output-root outputs/canonical_frames \
  Rec_Drv_GER_MACHET18_20260227_153128

PYTHONPATH=src python scripts/build_motional_windows.py \
  --canonical-dir outputs/canonical_frames \
  --output-dir outputs/motional_windows

PYTHONPATH=src python scripts/build_bev_model_inputs.py \
  --input-dir outputs/motional_windows \
  --output-dir outputs/model_inputs
```

## Start vLLM

Use the writable Hugging Face cache mount.

```bash
cd /path/to/ms-odd-tagging

HF_HOME=/path/to/huggingface \
HF_HUB_CACHE=/path/to/huggingface/hub \
TRANSFORMERS_CACHE=/path/to/huggingface/transformers \
VLLM_USE_FLASHINFER_SAMPLER=0 \
/path/to/vllm-env/bin/python \
  -m vllm.entrypoints.openai.api_server \
  --host 127.0.0.1 \
  --port 8001 \
  --model "Qwen/Qwen3-VL-4B-Instruct" \
  --dtype half \
  --max-model-len 16384 \
  --gpu-memory-utilization 0.85 \
  --limit-mm-per-prompt '{"image":3}'
```

## Run One Window

```bash
cd /path/to/ms-odd-tagging

PYTHONPATH=src /path/to/vllm-env/bin/python \
  scripts/run_local_vllm_eval.py \
  --recording Rec_Drv_GER_MACHET18_20260227_153128 \
  --window Rec_Drv_GER_MACHET18_20260227_153128_000-049 \
  --mode json_bev \
  --endpoint http://127.0.0.1:8001/v1/chat/completions \
  --model "Qwen/Qwen3-VL-4B-Instruct" \
  --model-input-root outputs/model_inputs \
  --output-root outputs/local_vllm_eval \
  --gt-labels tests/fixtures/gt/Rec_Drv_GER_MACHET18_20260227_153128_gt.json \
  --max-tokens 1800 \
  --retry-on-invalid
```

## Run All Windows For One Recording

```bash
cd /path/to/ms-odd-tagging

for d in outputs/model_inputs/Rec_Drv_GER_MACHET18_20260227_153128/Rec_Drv_GER_MACHET18_20260227_153128_*; do
  w="$(basename "$d")"
  PYTHONPATH=src /path/to/vllm-env/bin/python \
    scripts/run_local_vllm_eval.py \
    --recording Rec_Drv_GER_MACHET18_20260227_153128 \
    --window "$w" \
    --mode json_bev \
    --endpoint http://127.0.0.1:8001/v1/chat/completions \
    --model "Qwen/Qwen3-VL-4B-Instruct" \
    --model-input-root outputs/model_inputs \
    --output-root outputs/local_vllm_eval \
    --gt-labels tests/fixtures/gt/Rec_Drv_GER_MACHET18_20260227_153128_gt.json \
    --max-tokens 1800 \
    --retry-on-invalid
done
```

## Ignored Data

Ignored by default:

- raw ALT data
- generated canonical/window/model-input trees
- BEV images
- model outputs and reports
- caches and virtual environments
- model weights and large binaries
- real `.env` and machine-specific config files

## Notes

- YAML files under `configs/` are examples only; CLI loading from YAML is not implemented.
- The vLLM server is intentionally bound to `127.0.0.1`.
- Keep raw data and generated outputs local to each machine; synchronize code through Git.
