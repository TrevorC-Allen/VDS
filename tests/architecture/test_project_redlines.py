"""Documentation guardrails for project-level redlines."""

from __future__ import annotations

import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


class ProjectRedlineDocumentationTest(unittest.TestCase):
    def test_gpt_like_parity_redline_is_documented_in_required_sources(self) -> None:
        required_sources = {
            "MAIN_GOAL.md": ["GPT-like parity redline", "文件解析", "排版", "差距很大", "打回重写"],
            "README.md": ["GPT-like parity redline", "GPT / ChatGPT Data Analysis", "差距很大", "打回重写"],
            "docs/PHASE_GATES.md": ["GPT-like parity redline", "文件解析", "Workbench", "打回重写"],
            "docs/EVALUATION_GATE.md": ["GPT-like Parity Review", "gpt_like_parity", "差距很大", "打回重写"],
            "docs/FEATURE_BACKLOG.md": ["GPT-like parity review", "文件解析", "排版样式", "打回重写"],
            "docs/ARCHITECTURE.md": ["GPT-like parity redline", "文件解析", "排版密度", "打回重写"],
        }

        missing: list[str] = []
        for relative_path, required_terms in required_sources.items():
            text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
            for term in required_terms:
                if term not in text:
                    missing.append(f"{relative_path} missing {term!r}")

        self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()
