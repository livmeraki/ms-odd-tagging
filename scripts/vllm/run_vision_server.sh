#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/env.sh"

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
  shift
fi

MODEL="${1:-${MS_ODD_VLLM_VISION_MODEL:-Qwen/Qwen3-VL-8B-Instruct}}"
REPO_PYTHON="$MS_ODD_ROOT/.venv/bin/python"
ADJACENT_PYTHON="$(cd "$MS_ODD_ROOT/.." && pwd)/vllm_scenario_tagging/.venv/bin/python"

has_vllm() {
  [[ -x "$1" ]] && "$1" -c "import vllm" >/dev/null 2>&1
}

if [[ -n "${MS_ODD_VLLM_PYTHON:-}" ]]; then
  PYTHON_BIN="$MS_ODD_VLLM_PYTHON"
elif has_vllm "$REPO_PYTHON"; then
  PYTHON_BIN="$REPO_PYTHON"
elif has_vllm "$ADJACENT_PYTHON"; then
  PYTHON_BIN="$ADJACENT_PYTHON"
else
  PYTHON_BIN="$(command -v python)"
fi

if ! has_vllm "$PYTHON_BIN"; then
  echo "vLLM is not installed for $PYTHON_BIN." >&2
  echo 'Install the server extra first: python -m pip install -e ".[server]"' >&2
  echo "Or set MS_ODD_VLLM_PYTHON to a Python executable that has vLLM installed." >&2
  exit 1
fi

mkdir -p "$HF_HOME" "$HF_HUB_CACHE" "$TRANSFORMERS_CACHE" "$MS_ODD_ROOT/logs"

cd "$MS_ODD_ROOT"
COMMAND=(
  "$PYTHON_BIN" -m vllm.entrypoints.openai.api_server
  --model "$MODEL"
  --host "$MS_ODD_VLLM_HOST"
  --port "$MS_ODD_VLLM_PORT"
  --dtype "$MS_ODD_VLLM_DTYPE"
  --max-model-len "$MS_ODD_VLLM_MAX_MODEL_LEN"
  --gpu-memory-utilization "$MS_ODD_VLLM_GPU_MEMORY_UTILIZATION"
  --limit-mm-per-prompt "$MS_ODD_VLLM_LIMIT_MM_PER_PROMPT"
)

if [[ "$DRY_RUN" == "1" ]]; then
  printf 'MS_ODD_ROOT=%s\n' "$MS_ODD_ROOT"
  printf 'PYTHON_BIN=%s\n' "$PYTHON_BIN"
  printf 'HF_HOME=%s\n' "$HF_HOME"
  printf 'HOST=%s\n' "$MS_ODD_VLLM_HOST"
  printf 'PORT=%s\n' "$MS_ODD_VLLM_PORT"
  printf 'MODEL=%s\n' "$MODEL"
  printf 'MAX_MODEL_LEN=%s\n' "$MS_ODD_VLLM_MAX_MODEL_LEN"
  printf 'LIMIT_MM_PER_PROMPT=%s\n' "$MS_ODD_VLLM_LIMIT_MM_PER_PROMPT"
  printf 'COMMAND='
  printf '%q ' "${COMMAND[@]}"
  printf '\n'
  exit 0
fi

exec "${COMMAND[@]}"
