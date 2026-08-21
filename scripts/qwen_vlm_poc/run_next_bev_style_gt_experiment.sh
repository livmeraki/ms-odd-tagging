#!/usr/bin/env bash
set -euo pipefail

DATA_ROOT="${DATA_ROOT:-/media/stradvision/25eb199d-ae8a-49d6-b7e9-675eb144ddcd/ms-odd-tagging-data}"
REC="${REC:-Rec_Drv_GER_MACHET18_20260422_101126}"
ENDPOINT_BASE="${ENDPOINT_BASE:-http://127.0.0.1:8001}"
MODEL_ENDPOINT="${MODEL_ENDPOINT:-${ENDPOINT_BASE}/v1/chat/completions}"
CONFIG="${CONFIG:-configs/qwen_vlm_poc_reduced_2img_512.json}"
RUN_NAME="${RUN_NAME:-run_next_compact_2img_512px_$(date +%Y%m%d_%H%M%S)}"
FORCE_CACHE_REFRESH="${FORCE_CACHE_REFRESH:-1}"

GT="${DATA_ROOT}/outputs/bev_style_gt_experiment_${REC}/gt.csv"
INPUT_DIR="${DATA_ROOT}/outputs/01_canonical"
CANDIDATE_DIR="${DATA_ROOT}/outputs/bev_style_candidate_test_${REC}/candidates/waiting_for_pedestrian_to_cross/${REC}"
OUTPUT_ROOT="${DATA_ROOT}/outputs/bev_style_gt_experiment_${REC}/${RUN_NAME}"

if ! curl -fsS "${ENDPOINT_BASE}/v1/models" >/dev/null; then
  echo "vLLM endpoint is not ready: ${ENDPOINT_BASE}/v1/models" >&2
  exit 2
fi

if [[ ! -f "${GT}" ]]; then
  echo "Missing GT CSV: ${GT}" >&2
  exit 2
fi

if [[ ! -d "${CANDIDATE_DIR}" ]]; then
  echo "Missing candidate directory: ${CANDIDATE_DIR}" >&2
  exit 2
fi

mapfile -t CANDIDATES < <(find "${CANDIDATE_DIR}" -maxdepth 1 -type f -name '*.json' | sort)
if [[ "${#CANDIDATES[@]}" -eq 0 ]]; then
  echo "No candidate bundles found in: ${CANDIDATE_DIR}" >&2
  exit 2
fi

python - "${GT}" "${#CANDIDATES[@]}" <<'PY'
import csv
import sys
from pathlib import Path

gt = Path(sys.argv[1])
candidate_count = int(sys.argv[2])
rows = list(csv.DictReader(gt.open(newline="", encoding="utf-8")))
bad = [
    row.get("candidate_id", "<missing>")
    for row in rows
    if (row.get("expected_decision") or "").strip().lower() not in {"true", "false"}
]
if bad:
    raise SystemExit("GT expected_decision must be true/false for: " + ", ".join(bad[:10]))
print(f"GT rows: {len(rows)}")
print(f"Candidate bundles: {candidate_count}")
PY

cmd=(
  python scripts/qwen_vlm_poc/run_bev_style_gt_experiment.py
  --gt "${GT}"
  --output-root "${OUTPUT_ROOT}"
  --input-dir "${INPUT_DIR}"
  --config "${CONFIG}"
  --endpoint "${MODEL_ENDPOINT}"
  --compact-vlm-input
)

if [[ "${FORCE_CACHE_REFRESH}" == "1" ]]; then
  cmd+=(--force-cache-refresh)
fi

for candidate in "${CANDIDATES[@]}"; do
  cmd+=(--candidate-bundle "${candidate}")
done

printf 'Running:'
printf ' %q' "${cmd[@]}"
printf '\n'
"${cmd[@]}"

echo
echo "Output root: ${OUTPUT_ROOT}"
echo "Gallery: ${OUTPUT_ROOT}/gallery.html"
echo "Report: ${OUTPUT_ROOT}/report.html"
echo "Scene results: ${OUTPUT_ROOT}/scene_results.csv"
echo "Summary: ${OUTPUT_ROOT}/summary.csv"
