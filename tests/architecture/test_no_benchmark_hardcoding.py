"""Guardrails against Benchmark-specific optimization."""

from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from data_agent_core.benchmark.benchmark_runner import run_dabstep_benchmark


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


class BenchmarkHardcodingBoundaryTest(unittest.TestCase):
    def test_core_analysis_modules_do_not_reference_benchmark_leak_fields(self) -> None:
        forbidden_terms = {
            'task["task_id"]',
            "task['task_id']",
            "task.get(\"task_id\")",
            "task.get('task_id')",
            "expected_answer",
            "standard_answer",
            "hidden_answer",
        }
        scan_roots = [
            REPO_ROOT / "data_agent_core" / "agent",
            REPO_ROOT / "data_agent_core" / "core",
            REPO_ROOT / "data_agent_core" / "executors",
            REPO_ROOT / "data_agent_core" / "llm",
            REPO_ROOT / "data_agent_core" / "output",
            REPO_ROOT / "data_agent_core" / "verifier",
        ]
        violations: list[str] = []
        for root in scan_roots:
            for path in root.rglob("*.py"):
                text = path.read_text().lower()
                for term in forbidden_terms:
                    if term in text:
                        violations.append(f"{path.relative_to(REPO_ROOT)} contains {term}")
        self.assertEqual([], violations)

    def test_benchmark_runner_does_not_pass_answer_or_task_id_to_agent(self) -> None:
        calls: list[dict[str, str]] = []

        class FakeAgent:
            def __init__(self, context_dir: pathlib.Path) -> None:
                self.context_dir = context_dir

            def analyze(self, question: str, guidelines: str = "", execution_mode: str = "auto"):
                calls.append(
                    {
                        "question": question,
                        "guidelines": guidelines,
                        "execution_mode": execution_mode,
                    }
                )
                return _FakeResponse(), _FakeTrace()

        with tempfile.TemporaryDirectory() as temp_dir:
            dataset_root = pathlib.Path(temp_dir)
            tasks_dir = dataset_root / "data" / "tasks"
            context_dir = dataset_root / "data" / "context"
            tasks_dir.mkdir(parents=True)
            context_dir.mkdir(parents=True)
            (tasks_dir / "dev.jsonl").write_text(
                json.dumps(
                    {
                        "task_id": "secret-task",
                        "question": "Which country has the most transactions?",
                        "guidelines": "Answer with a country code.",
                        "answer": "NL",
                    }
                )
                + "\n"
            )

            with patch("data_agent_core.benchmark.benchmark_runner.DataAnalysisAgent", FakeAgent):
                run_dabstep_benchmark(dataset_root=dataset_root, split="dev", limit=1, output_dir=dataset_root / "out")

        self.assertEqual(
            [{"question": "Which country has the most transactions?", "guidelines": "Answer with a country code.", "execution_mode": "auto"}],
            calls,
        )


class _FakeResponse:
    answer = "NL"
    success = True
    debug = {"operation": "fake"}


class _FakeTrace:
    run_id = "run_fake"

    def to_dict(self) -> dict[str, str]:
        return {"run_id": self.run_id}


if __name__ == "__main__":
    unittest.main()
