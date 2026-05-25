#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PY="${PY:-/Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
OUTPUT_ROOT="${OUTPUT_ROOT:-outputs/eval_gate}"
GENERATE_VDS="${GENERATE_VDS:-1}"
OUT_DIR="${OUTPUT_ROOT}/${RUN_ID}-vds_sales_generic"
DATA_ROOT="/Users/trevorcui/Desktop/Virtual Data Scientist测试数据/数据"

VDS_ARGS=()
if [[ "${GENERATE_VDS}" != "0" ]]; then
  VDS_ARGS+=(--generate-vds-answers)
fi

VDS_LLM_PROVIDER=mock "${PY}" scripts/run_generic_dataset_eval.py \
  --dataset-name vds_sales \
  --files "${DATA_ROOT}/QueryGPT_销售数据_单表版.xlsx" \
  ${VDS_ARGS[@]+"${VDS_ARGS[@]}"} \
  --output-dir "${OUT_DIR}" \
  --print-summary

echo "VDS sales comparison: ${OUT_DIR}/comparison.md"
echo "VDS sales answers: ${OUT_DIR}/vds_answers.jsonl"
