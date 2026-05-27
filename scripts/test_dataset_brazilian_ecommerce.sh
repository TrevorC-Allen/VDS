#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PY="${PY:-/Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
OUTPUT_ROOT="${OUTPUT_ROOT:-outputs/eval_gate}"
GENERATE_VDS="${GENERATE_VDS:-1}"
OUT_DIR="${OUTPUT_ROOT}/${RUN_ID}-brazilian_ecommerce_generic"
DATA_ROOT="/Users/trevorcui/Desktop/验证数据集/Brazilian E-Commerce Public Dataset"

VDS_ARGS=()
if [[ "${GENERATE_VDS}" != "0" ]]; then
  VDS_ARGS+=(--generate-vds-answers)
fi

VDS_LLM_PROVIDER=mock "${PY}" scripts/run_generic_dataset_eval.py \
  --dataset-name brazilian_ecommerce \
  --files \
    "${DATA_ROOT}/olist_customers_dataset.csv" \
    "${DATA_ROOT}/olist_geolocation_dataset.csv" \
    "${DATA_ROOT}/olist_order_items_dataset.csv" \
    "${DATA_ROOT}/olist_order_payments_dataset.csv" \
    "${DATA_ROOT}/olist_order_reviews_dataset.csv" \
    "${DATA_ROOT}/olist_orders_dataset.csv" \
    "${DATA_ROOT}/olist_products_dataset.csv" \
    "${DATA_ROOT}/olist_sellers_dataset.csv" \
    "${DATA_ROOT}/product_category_name_translation.csv" \
  ${VDS_ARGS[@]+"${VDS_ARGS[@]}"} \
  --output-dir "${OUT_DIR}" \
  --print-summary

echo "Brazilian e-commerce comparison: ${OUT_DIR}/comparison.md"
echo "Brazilian e-commerce VDS answers: ${OUT_DIR}/vds_answers.jsonl"
