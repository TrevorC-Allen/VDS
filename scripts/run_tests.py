"""Single unittest entrypoint for VDS local and CI runs."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.setdefault("VDS_LLM_PROVIDER", "mock")
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(repo_root) if not existing_pythonpath else str(repo_root) + os.pathsep + existing_pythonpath
    unittest_args = sys.argv[1:] or ["discover", "-s", "tests", "-t", ".", "-p", "test*.py"]
    command = [sys.executable, "-m", "unittest", *unittest_args]
    print("Running:", " ".join(command), flush=True)
    return subprocess.run(command, cwd=repo_root, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
