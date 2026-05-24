#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_ROOT="${VDS_WORKBENCH_RUNTIME_ROOT:-/Users/trevorcui/.vds-workbench-runtime/VDS}"

mkdir -p "$RUNTIME_ROOT"

rsync -a --delete \
  --exclude ".git" \
  --exclude ".playwright-cli" \
  --exclude "__pycache__" \
  --exclude ".pytest_cache" \
  --exclude "outputs" \
  --exclude "storage" \
  "$REPO_ROOT/" "$RUNTIME_ROOT/"

chmod +x "$RUNTIME_ROOT/scripts/run_workbench_server.sh"

echo "Synced Workbench runtime to $RUNTIME_ROOT"
