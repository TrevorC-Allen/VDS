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
OUT_DIR="${OUTPUT_ROOT}/${RUN_ID}-health_generic"
DATA_ROOT="/Users/trevorcui/Desktop/验证数据集/Health历史数据_5.9"

VDS_ARGS=()
if [[ "${GENERATE_VDS}" != "0" ]]; then
  VDS_ARGS+=(--generate-vds-answers)
fi
STANDARD_ARGS=(--standard-answer-source "${STANDARD_ANSWER_SOURCE}")
if [[ -n "${STANDARD_ANSWERS_FILE:-}" ]]; then
  STANDARD_ARGS+=(--standard-answers-file "${STANDARD_ANSWERS_FILE}")
fi

VDS_LLM_PROVIDER="${REFERENCE_LLM_PROVIDER}" "${PY}" scripts/run_generic_dataset_eval.py \
  --dataset-name health_history \
  --files \
    "${DATA_ROOT}/activity_summary.csv" \
    "${DATA_ROOT}/daily_metrics.csv" \
    "${DATA_ROOT}/ecg_classification_counts.csv" \
    "${DATA_ROOT}/ecg_device_counts.csv" \
    "${DATA_ROOT}/ecg_summary.csv" \
    "${DATA_ROOT}/health_upload_table.csv" \
    "${DATA_ROOT}/latest_measurements.csv" \
    "${DATA_ROOT}/monthly_metrics.csv" \
    "${DATA_ROOT}/record_source_counts.csv" \
    "${DATA_ROOT}/record_sources_by_type.csv" \
    "${DATA_ROOT}/record_type_counts.csv" \
    "${DATA_ROOT}/record_units_by_type.csv" \
    "${DATA_ROOT}/workout_month_summary.csv" \
    "${DATA_ROOT}/workout_source_counts.csv" \
    "${DATA_ROOT}/workout_type_summary.csv" \
    "${DATA_ROOT}/workouts.csv" \
    "${DATA_ROOT}/yearly_metrics.csv" \
  "${STANDARD_ARGS[@]}" \
  ${VDS_ARGS[@]+"${VDS_ARGS[@]}"} \
  --output-dir "${OUT_DIR}" \
  --print-summary

echo "Health comparison: ${OUT_DIR}/comparison.md"
echo "Health VDS answers: ${OUT_DIR}/vds_answers.jsonl"
VDS_LLM_PROVIDER="${JUDGE_LLM_PROVIDER}" "${PY}" scripts/score_comparison_answers.py "${OUT_DIR}/comparison.md" --judge "${COMPARISON_JUDGE}" --print-summary
echo "Health scored comparison: ${OUT_DIR}/comparison_scored.md"
