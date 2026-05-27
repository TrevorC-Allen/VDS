#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
export RUN_ID
export PY="${PY:-/Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3}"
export OUTPUT_ROOT="${OUTPUT_ROOT:-outputs/eval_gate}"
export GENERATE_VDS="${GENERATE_VDS:-1}"

echo "VDS original five-domain run id: ${RUN_ID}"
echo

bash scripts/test_dataset_vds_sales.sh
echo
bash scripts/test_dataset_vds_learning.sh
echo
bash scripts/test_dataset_vds_medical.sh
echo
bash scripts/test_dataset_vds_logistics.sh
echo
bash scripts/test_dataset_vds_saas.sh

echo
echo "VDS original five-domain scripts finished for RUN_ID=${RUN_ID}."
