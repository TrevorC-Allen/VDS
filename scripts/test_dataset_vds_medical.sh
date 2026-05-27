#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PY="${PY:-/Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
OUTPUT_ROOT="${OUTPUT_ROOT:-outputs/eval_gate}"
GENERATE_VDS="${GENERATE_VDS:-1}"
OUT_DIR="${OUTPUT_ROOT}/${RUN_ID}-vds_medical_generic"
DATA_ROOT="/Users/trevorcui/Desktop/Virtual Data Scientist测试数据/数据"

VDS_ARGS=()
if [[ "${GENERATE_VDS}" != "0" ]]; then
  VDS_ARGS+=(--generate-vds-answers)
fi

VDS_LLM_PROVIDER=mock "${PY}" scripts/run_generic_dataset_eval.py \
  --dataset-name vds_medical \
  --files "${DATA_ROOT}/QueryGPT_医疗服务数据_单表版.xlsx" \
  ${VDS_ARGS[@]+"${VDS_ARGS[@]}"} \
  --output-dir "${OUT_DIR}" \
  --print-summary

echo "VDS medical comparison: ${OUT_DIR}/comparison.md"
echo "VDS medical answers: ${OUT_DIR}/vds_answers.jsonl"
COMPARISON_JUDGE="${COMPARISON_JUDGE:-heuristic}" "${PY}" scripts/score_comparison_answers.py "${OUT_DIR}/comparison.md" --judge "${COMPARISON_JUDGE:-heuristic}" --print-summary
echo "VDS medical scored comparison: ${OUT_DIR}/comparison_scored.md"
