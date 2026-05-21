"""Architecture boundary tests."""

from __future__ import annotations

import ast
import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


class DependencyBoundaryTest(unittest.TestCase):
    def test_data_agent_core_does_not_import_outer_layers(self) -> None:
        forbidden = {
            "backend",
            "ms_agent_framework_adapter",
            "multi_agent_workflows",
            "agent_framework",
        }
        violations: list[str] = []
        for path in (REPO_ROOT / "data_agent_core").rglob("*.py"):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module.split(".")[0]]
                else:
                    continue
                for name in names:
                    if name in forbidden:
                        violations.append(f"{path.relative_to(REPO_ROOT)} imports {name}")
        self.assertEqual([], violations)

    def test_adapter_does_not_import_microsoft_framework_yet(self) -> None:
        violations: list[str] = []
        for path in (REPO_ROOT / "ms_agent_framework_adapter").rglob("*.py"):
            source = path.read_text()
            if "microsoft.agent" in source.lower() or "semantic_kernel" in source.lower():
                violations.append(str(path.relative_to(REPO_ROOT)))
        self.assertEqual([], violations)


if __name__ == "__main__":
    unittest.main()
