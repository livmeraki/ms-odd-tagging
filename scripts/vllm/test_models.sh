#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/env.sh"

PYTHON_BIN="${MS_ODD_VLLM_PYTHON:-$MS_ODD_ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python)"
fi

curl -sS "http://$MS_ODD_VLLM_HOST:$MS_ODD_VLLM_PORT/v1/models" | "$PYTHON_BIN" -m json.tool
