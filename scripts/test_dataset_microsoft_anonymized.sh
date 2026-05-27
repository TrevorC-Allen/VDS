#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PY="${PY:-/Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
OUTPUT_ROOT="${OUTPUT_ROOT:-outputs/eval_gate}"
GENERATE_VDS="${GENERATE_VDS:-1}"
RUN_STANDARD_BENCHMARK="${RUN_STANDARD_BENCHMARK:-0}"
OUT_DIR="${OUTPUT_ROOT}/${RUN_ID}-microsoft_anonymized_generic"
BENCH_OUT_DIR="${OUTPUT_ROOT}/${RUN_ID}-microsoft_anonymized_standard_300"
DATA_ROOT="/Users/trevorcui/Desktop/微软脱敏数据"

VDS_ARGS=()
if [[ "${GENERATE_VDS}" != "0" ]]; then
  VDS_ARGS+=(--generate-vds-answers)
fi

VDS_LLM_PROVIDER=mock "${PY}" scripts/run_generic_dataset_eval.py \
  --dataset-name microsoft_anonymized \
  --files \
    "${DATA_ROOT}/ads_trd_dist_ord_target_emp_1m_df.csv" \
    "${DATA_ROOT}/ads_trd_dist_ord_target_mgr_1m_df.csv" \
    "${DATA_ROOT}/ads_trd_time_prg_df.csv" \
    "${DATA_ROOT}/v_chl_jc_cust_sku_mi.csv" \
    "${DATA_ROOT}/v_chl_route_plan_cust_cnt_1d_df.csv" \
    "${DATA_ROOT}/v_chl_visit_dtl.csv" \
    "${DATA_ROOT}/v_mkt_dsp_actv_mi.csv" \
    "${DATA_ROOT}/v_mkt_dsp_execute_mi.csv" \
    "${DATA_ROOT}/v_trd_dist_ord_dtl.csv" \
    "${DATA_ROOT}/v_trd_dist_ord_dtl_1d_rt.csv" \
    "${DATA_ROOT}/终端客户月度维表.csv" \
  ${VDS_ARGS[@]+"${VDS_ARGS[@]}"} \
  --output-dir "${OUT_DIR}" \
  --print-summary

echo "Microsoft generic comparison: ${OUT_DIR}/comparison.md"
echo "Microsoft generic VDS answers: ${OUT_DIR}/vds_answers.jsonl"
COMPARISON_JUDGE="${COMPARISON_JUDGE:-heuristic}" "${PY}" scripts/score_comparison_answers.py "${OUT_DIR}/comparison.md" --judge "${COMPARISON_JUDGE:-heuristic}" --print-summary
echo "Microsoft generic scored comparison: ${OUT_DIR}/comparison_scored.md"

if [[ "${RUN_STANDARD_BENCHMARK}" != "0" ]]; then
  VDS_LLM_PROVIDER=mock "${PY}" -m multi_agent_workflows.microsoft_anonymized_benchmark_runner \
    --dataset-root "${DATA_ROOT}" \
    --limit 300 \
    --offset 0 \
    --output-dir "${BENCH_OUT_DIR}"
  echo "Microsoft standard benchmark report: ${BENCH_OUT_DIR}/report.json"
fi
