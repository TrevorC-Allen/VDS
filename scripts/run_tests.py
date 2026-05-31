"""Single unittest entrypoint for VDS local and CI runs."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


DEFAULT_CODEX_PYTHON = Path("/Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3")


def resolve_test_python() -> str:
    configured = os.environ.get("VDS_PYTHON_BIN") or os.environ.get("PY")
    if configured:
        return configured
    if DEFAULT_CODEX_PYTHON.exists():
        return str(DEFAULT_CODEX_PYTHON)
    return sys.executable


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.setdefault("VDS_LLM_PROVIDER", "mock")
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(repo_root) if not existing_pythonpath else str(repo_root) + os.pathsep + existing_pythonpath
    unittest_args = sys.argv[1:] or ["discover", "-s", "tests", "-t", ".", "-p", "test*.py"]
    command = [resolve_test_python(), "-m", "unittest", *unittest_args]
    print("Running:", " ".join(command), flush=True)
    return subprocess.run(command, cwd=repo_root, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
