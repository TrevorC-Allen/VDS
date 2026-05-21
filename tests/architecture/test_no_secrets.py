"""Guardrails against committing LLM/API secrets."""

from __future__ import annotations

import pathlib
import re
import subprocess
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

SECRET_PATTERNS = {
    "openai_project_key": re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}"),
    "generic_llm_key": re.compile(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_-]{20,}"),
}


class SecretBoundaryTest(unittest.TestCase):
    def test_tracked_files_do_not_contain_api_keys(self) -> None:
        violations: list[str] = []
        for relative_path in _tracked_files():
            path = REPO_ROOT / relative_path
            if not path.is_file():
                continue
            text = path.read_text(errors="ignore")
            for label, pattern in SECRET_PATTERNS.items():
                if pattern.search(text):
                    violations.append(f"{relative_path} contains {label}")
        self.assertEqual([], violations)


def _tracked_files() -> list[pathlib.Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [pathlib.Path(line) for line in result.stdout.splitlines() if line]


if __name__ == "__main__":
    unittest.main()
