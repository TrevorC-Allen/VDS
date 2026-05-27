#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PY="${PY:-/Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
OUTPUT_ROOT="${OUTPUT_ROOT:-outputs/eval_gate}"
GENERATE_VDS="${GENERATE_VDS:-1}"
STANDARD_ANSWER_SOURCE="${STANDARD_ANSWER_SOURCE:-${VDS_STANDARD_ANSWER_SOURCE:-deepseek}}"
REFERENCE_LLM_PROVIDER="${REFERENCE_LLM_PROVIDER:-deepseek}"
JUDGE_LLM_PROVIDER="${JUDGE_LLM_PROVIDER:-deepseek}"
COMPARISON_JUDGE="${COMPARISON_JUDGE:-llm}"
OUT_DIR="${OUTPUT_ROOT}/${RUN_ID}-uk_retail_generic"

VDS_ARGS=()
if [[ "${GENERATE_VDS}" != "0" ]]; then
  VDS_ARGS+=(--generate-vds-answers)
fi
STANDARD_ARGS=(--standard-answer-source "${STANDARD_ANSWER_SOURCE}")
if [[ -n "${STANDARD_ANSWERS_FILE:-}" ]]; then
  STANDARD_ARGS+=(--standard-answers-file "${STANDARD_ANSWERS_FILE}")
fi

VDS_LLM_PROVIDER="${REFERENCE_LLM_PROVIDER}" "${PY}" scripts/run_generic_dataset_eval.py \
  --dataset-name uk_retail \
  --files "/Users/trevorcui/Desktop/验证数据集/UK retail/Online Retail.xlsx" \
  "${STANDARD_ARGS[@]}" \
  ${VDS_ARGS[@]+"${VDS_ARGS[@]}"} \
  --output-dir "${OUT_DIR}" \
  --print-summary

echo "UK retail comparison: ${OUT_DIR}/comparison.md"
echo "UK retail VDS answers: ${OUT_DIR}/vds_answers.jsonl"
VDS_LLM_PROVIDER="${JUDGE_LLM_PROVIDER}" "${PY}" scripts/score_comparison_answers.py "${OUT_DIR}/comparison.md" --judge "${COMPARISON_JUDGE}" --print-summary
echo "UK retail scored comparison: ${OUT_DIR}/comparison_scored.md"
