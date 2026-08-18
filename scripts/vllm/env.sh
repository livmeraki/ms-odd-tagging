#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export MS_ODD_ROOT="${MS_ODD_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

if [[ -f "$MS_ODD_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$MS_ODD_ROOT/.env"
  set +a
fi

export PYTHONNOUSERSITE="${PYTHONNOUSERSITE:-1}"
export VLLM_USE_FLASHINFER_SAMPLER="${VLLM_USE_FLASHINFER_SAMPLER:-0}"

export MS_ODD_BIGDATA_ROOT="${MS_ODD_BIGDATA_ROOT:-/media/stradvision/25eb199d-ae8a-49d6-b7e9-675eb144ddcd}"

if [[ -n "${MS_ODD_HF_HOME:-}" ]]; then
  export HF_HOME="$MS_ODD_HF_HOME"
elif [[ -n "${SCENARIO_HF_HOME:-}" ]]; then
  export HF_HOME="$SCENARIO_HF_HOME"
elif [[ -z "${HF_HOME:-}" ]]; then
  export HF_HOME="$MS_ODD_BIGDATA_ROOT/huggingface"
fi

export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-$HF_HOME/transformers}"
export HF_HUB_CACHE="${HF_HUB_CACHE:-$HF_HOME/hub}"

export MS_ODD_VLLM_HOST="${MS_ODD_VLLM_HOST:-127.0.0.1}"
export MS_ODD_VLLM_PORT="${MS_ODD_VLLM_PORT:-8001}"
export MS_ODD_VLLM_DTYPE="${MS_ODD_VLLM_DTYPE:-half}"
export MS_ODD_VLLM_MAX_MODEL_LEN="${MS_ODD_VLLM_MAX_MODEL_LEN:-16384}"
export MS_ODD_VLLM_GPU_MEMORY_UTILIZATION="${MS_ODD_VLLM_GPU_MEMORY_UTILIZATION:-0.90}"
export MS_ODD_VLLM_LIMIT_MM_PER_PROMPT="${MS_ODD_VLLM_LIMIT_MM_PER_PROMPT:-image=6}"
