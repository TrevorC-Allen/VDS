#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PY="${PY:-/Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3}"
SUITE="quick"
BASE_URL="http://127.0.0.1:8001"
PROVIDER="${VDS_LLM_PROVIDER:-auto}"
CASE_FILE="configs/eval_gate/workbench_gpt_like_cases.jsonl"
CHANGELOG_LIMIT="20"
FAIL_ON="p0"
OUTPUT_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --suite)
      SUITE="$2"
      shift 2
      ;;
    --base-url)
      BASE_URL="$2"
      shift 2
      ;;
    --provider)
      PROVIDER="$2"
      shift 2
      ;;
    --case-file)
      CASE_FILE="$2"
      shift 2
      ;;
    --changelog-limit)
      CHANGELOG_LIMIT="$2"
      shift 2
      ;;
    --fail-on)
      FAIL_ON="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    -h|--help)
      cat <<'EOF'
Usage:
  VDS_LLM_PROVIDER=deepseek bash scripts/run_vds_llm_quality_gate.sh --suite quick

Options:
  --suite quick|full|changelog|api|ui
  --base-url http://127.0.0.1:8001
  --provider auto|deepseek|openai
  --case-file configs/eval_gate/workbench_gpt_like_cases.jsonl
  --changelog-limit 20
  --fail-on p0|p1|score
  --output-dir outputs/llm_quality_gate/<run_id>
EOF
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ "${PROVIDER}" != "auto" ]]; then
  export VDS_LLM_PROVIDER="${PROVIDER}"
elif [[ -z "${VDS_LLM_PROVIDER:-}" ]]; then
  if [[ -n "${DEEPSEEK_API_KEY:-}" ]]; then
    export VDS_LLM_PROVIDER="deepseek"
  elif [[ -n "${OPENAI_API_KEY:-}" ]]; then
    export VDS_LLM_PROVIDER="openai"
  fi
fi

if [[ "${VDS_LLM_PROVIDER:-}" == "mock" || -z "${VDS_LLM_PROVIDER:-}" ]]; then
  echo "A real LLM provider is required. Set VDS_LLM_PROVIDER=deepseek/openai and provide the matching API key." >&2
  exit 2
fi

RUN_ID="${RUN_ID:-$(date +%Y-%m-%d-%H%M)-${SUITE}-gpt-like}"
COMMON_OUTPUT_ARGS=()
if [[ -n "${OUTPUT_DIR}" ]]; then
  COMMON_OUTPUT_ARGS+=(--output-dir "${OUTPUT_DIR}")
fi

echo "VDS LLM quality gate"
echo "  suite: ${SUITE}"
echo "  provider: ${VDS_LLM_PROVIDER}"
echo "  base-url: ${BASE_URL}"
echo "  run-id: ${RUN_ID}"

if [[ "${SUITE}" == "changelog" ]]; then
  if [[ ${#COMMON_OUTPUT_ARGS[@]} -gt 0 ]]; then
    "${PY}" scripts/run_changelog_gpt_like_audit.py \
      --run-id "${RUN_ID}" \
      --provider "${VDS_LLM_PROVIDER}" \
      --limit "${CHANGELOG_LIMIT}" \
      --fail-on "${FAIL_ON}" \
      "${COMMON_OUTPUT_ARGS[@]}"
  else
    "${PY}" scripts/run_changelog_gpt_like_audit.py \
      --run-id "${RUN_ID}" \
      --provider "${VDS_LLM_PROVIDER}" \
      --limit "${CHANGELOG_LIMIT}" \
      --fail-on "${FAIL_ON}"
  fi
else
  if [[ ${#COMMON_OUTPUT_ARGS[@]} -gt 0 ]]; then
    "${PY}" scripts/run_workbench_gpt_like_llm_tests.py \
      --run-id "${RUN_ID}" \
      --suite "${SUITE}" \
      --base-url "${BASE_URL}" \
      --provider "${VDS_LLM_PROVIDER}" \
      --case-file "${CASE_FILE}" \
      --fail-on "${FAIL_ON}" \
      "${COMMON_OUTPUT_ARGS[@]}"
  else
    "${PY}" scripts/run_workbench_gpt_like_llm_tests.py \
      --run-id "${RUN_ID}" \
      --suite "${SUITE}" \
      --base-url "${BASE_URL}" \
      --provider "${VDS_LLM_PROVIDER}" \
      --case-file "${CASE_FILE}" \
      --fail-on "${FAIL_ON}"
  fi
fi

echo "Quality gate finished for ${RUN_ID}."
