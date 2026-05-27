#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${VDS_REPO_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON_BIN="${VDS_PYTHON_BIN:-/Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3}"
HOST="${VDS_WORKBENCH_HOST:-127.0.0.1}"
PORT="${VDS_WORKBENCH_PORT:-8001}"

cd "$REPO_ROOT"

if [[ -f ".env.local" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env.local"
  set +a
fi

export VDS_LLM_PROVIDER="${VDS_LLM_PROVIDER:-mock}"

"$PYTHON_BIN" - <<'PY'
import importlib.util
import subprocess
import sys

missing = [
    package
    for package, module in [
        ("fastapi", "fastapi"),
        ("uvicorn", "uvicorn"),
        ("python-multipart", "python_multipart"),
    ]
    if importlib.util.find_spec(module) is None
]
if missing:
    subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
PY

exec "$PYTHON_BIN" -m uvicorn backend.main:app --host "$HOST" --port "$PORT"
