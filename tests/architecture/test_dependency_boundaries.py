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

    def test_microsoft_framework_imports_stay_out_of_core(self) -> None:
        violations: list[str] = []
        for path in REPO_ROOT.rglob("*.py"):
            relative = path.relative_to(REPO_ROOT)
            if relative.parts[0] in {".git", "outputs", "storage"}:
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module.split(".")[0]]
                else:
                    continue
                if "agent_framework" in names and relative.parts[0] not in {"ms_agent_framework_adapter", "tests"}:
                    violations.append(f"{relative} imports agent_framework")
        self.assertEqual([], violations)

    def test_backend_router_stays_thin(self) -> None:
        forbidden = {
            "pandas",
            "numpy",
            "sqlite3",
            "duckdb",
            "data_agent_core.executors",
            "data_agent_core.verifier",
            "data_agent_core.benchmark",
        }
        violations: list[str] = []
        for path in (REPO_ROOT / "backend" / "routers").rglob("*.py"):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                else:
                    continue
                for name in names:
                    if name in forbidden or any(name.startswith(prefix + ".") for prefix in forbidden):
                        violations.append(f"{path.relative_to(REPO_ROOT)} imports {name}")
        self.assertEqual([], violations)


if __name__ == "__main__":
    unittest.main()
