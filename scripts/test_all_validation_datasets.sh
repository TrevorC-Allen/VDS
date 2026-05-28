#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
export RUN_ID
export PY="${PY:-/Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3}"
export OUTPUT_ROOT="${OUTPUT_ROOT:-outputs/eval_gate}"
export GENERATE_VDS="${GENERATE_VDS:-1}"
export RUN_DOMAIN="${RUN_DOMAIN:-1}"
export VDS_GENERIC_EVAL_QUICK="${VDS_GENERIC_EVAL_QUICK:-0}"
export STANDARD_ANSWER_SOURCE="${STANDARD_ANSWER_SOURCE:-${VDS_STANDARD_ANSWER_SOURCE:-deepseek}}"
export REFERENCE_LLM_PROVIDER="${REFERENCE_LLM_PROVIDER:-deepseek}"
export JUDGE_LLM_PROVIDER="${JUDGE_LLM_PROVIDER:-deepseek}"
export COMPARISON_JUDGE="${COMPARISON_JUDGE:-llm}"

echo "Validation dataset run id: ${RUN_ID}"
echo "Output root: ${OUTPUT_ROOT}"
echo "GENERATE_VDS=${GENERATE_VDS}"
echo "VDS_GENERIC_EVAL_QUICK=${VDS_GENERIC_EVAL_QUICK}"
echo "STANDARD_ANSWER_SOURCE=${STANDARD_ANSWER_SOURCE}"
echo "REFERENCE_LLM_PROVIDER=${REFERENCE_LLM_PROVIDER}"
echo "COMPARISON_JUDGE=${COMPARISON_JUDGE}"
echo "JUDGE_LLM_PROVIDER=${JUDGE_LLM_PROVIDER}"
if [[ "${VDS_GENERIC_EVAL_QUICK}" == "1" ]]; then
  echo "Warning: VDS_GENERIC_EVAL_QUICK=1 is smoke coverage only, not formal acceptance."
fi
echo

bash scripts/test_dataset_uk_retail.sh
echo
bash scripts/test_dataset_health.sh
echo
bash scripts/test_dataset_nyc_taxi.sh
echo
bash scripts/test_dataset_brazilian_ecommerce.sh
echo
bash scripts/test_dataset_microsoft_anonymized.sh
echo
bash scripts/test_dataset_vds_original_5.sh

echo
echo "All validation dataset scripts finished for RUN_ID=${RUN_ID}."
