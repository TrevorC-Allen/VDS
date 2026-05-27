#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PY="${PY:-/Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
OUTPUT_ROOT="${OUTPUT_ROOT:-outputs/eval_gate}"
GENERATE_VDS="${GENERATE_VDS:-1}"
RUN_DOMAIN="${RUN_DOMAIN:-1}"
STANDARD_ANSWER_SOURCE="${STANDARD_ANSWER_SOURCE:-${VDS_STANDARD_ANSWER_SOURCE:-deepseek}}"
REFERENCE_LLM_PROVIDER="${REFERENCE_LLM_PROVIDER:-deepseek}"
JUDGE_LLM_PROVIDER="${JUDGE_LLM_PROVIDER:-deepseek}"
COMPARISON_JUDGE="${COMPARISON_JUDGE:-llm}"
GENERIC_OUT_DIR="${OUTPUT_ROOT}/${RUN_ID}-nyc_taxi_generic"
DOMAIN_OUT_DIR="${OUTPUT_ROOT}/${RUN_ID}-nyc_taxi_domain"

VDS_ARGS=()
if [[ "${GENERATE_VDS}" != "0" ]]; then
  VDS_ARGS+=(--generate-vds-answers)
fi
STANDARD_ARGS=(--standard-answer-source "${STANDARD_ANSWER_SOURCE}")
if [[ -n "${STANDARD_ANSWERS_FILE:-}" ]]; then
  STANDARD_ARGS+=(--standard-answers-file "${STANDARD_ANSWERS_FILE}")
fi

VDS_LLM_PROVIDER="${REFERENCE_LLM_PROVIDER}" "${PY}" scripts/run_generic_dataset_eval.py \
  --dataset-name nyc_taxi \
  --files \
    "/Users/trevorcui/Desktop/验证数据集/NYC Taxi/yellow_tripdata_2025-01.parquet" \
    "/Users/trevorcui/Desktop/验证数据集/NYC Taxi/yellow_tripdata_2026-01.parquet" \
  "${STANDARD_ARGS[@]}" \
  ${VDS_ARGS[@]+"${VDS_ARGS[@]}"} \
  --output-dir "${GENERIC_OUT_DIR}" \
  --print-summary

echo "NYC taxi generic comparison: ${GENERIC_OUT_DIR}/comparison.md"
echo "NYC taxi generic VDS answers: ${GENERIC_OUT_DIR}/vds_answers.jsonl"
VDS_LLM_PROVIDER="${JUDGE_LLM_PROVIDER}" "${PY}" scripts/score_comparison_answers.py "${GENERIC_OUT_DIR}/comparison.md" --judge "${COMPARISON_JUDGE}" --print-summary
echo "NYC taxi generic scored comparison: ${GENERIC_OUT_DIR}/comparison_scored.md"

if [[ "${RUN_DOMAIN}" != "0" ]]; then
  VDS_LLM_PROVIDER=mock "${PY}" scripts/run_taxi_dual_year_eval.py \
    --config configs/eval_gate/taxi_dual_year_eval.json \
    --output-dir "${DOMAIN_OUT_DIR}" \
    --print-summary
  echo "NYC taxi domain standard answers: ${DOMAIN_OUT_DIR}/standard_answers.md"
fi
