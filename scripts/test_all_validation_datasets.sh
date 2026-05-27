#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
export RUN_ID
export PY="${PY:-/Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3}"
export OUTPUT_ROOT="${OUTPUT_ROOT:-outputs/eval_gate}"
export GENERATE_VDS="${GENERATE_VDS:-1}"
export RUN_DOMAIN="${RUN_DOMAIN:-1}"
export VDS_GENERIC_EVAL_QUICK="${VDS_GENERIC_EVAL_QUICK:-1}"

echo "Validation dataset run id: ${RUN_ID}"
echo "Output root: ${OUTPUT_ROOT}"
echo "GENERATE_VDS=${GENERATE_VDS}"
echo "VDS_GENERIC_EVAL_QUICK=${VDS_GENERIC_EVAL_QUICK}"
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
