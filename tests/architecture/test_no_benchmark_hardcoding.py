"""Guardrails against Benchmark-specific optimization."""

from __future__ import annotations

import json
import pathlib
import re
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from multi_agent_workflows.dabstep_benchmark_runner import run_dabstep_multi_agent_benchmark
from multi_agent_workflows.microsoft_anonymized_benchmark_runner import run_microsoft_anonymized_benchmark
from multi_agent_workflows.uploaded_table_benchmark_runner import run_uploaded_table_benchmark
from multi_agent_workflows.vds_desktop_benchmark_runner import run_vds_desktop_benchmark


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
            "proxy answer",
            "accepted answer",
            "public proxy",
        }
        forbidden_patterns = {
            "task_id equality": re.compile(r"\b(task_id|question_id)\s*==\s*['\"]"),
            "task_id membership": re.compile(r"\b(task_id|question_id)\s+in\s+\{?[\['\"]"),
        }
        scan_roots = [
            REPO_ROOT / "data_agent_core" / "agent",
            REPO_ROOT / "data_agent_core" / "core",
            REPO_ROOT / "data_agent_core" / "executors",
            REPO_ROOT / "data_agent_core" / "llm",
            REPO_ROOT / "data_agent_core" / "output",
            REPO_ROOT / "data_agent_core" / "verifier",
            REPO_ROOT / "agent_runtime",
            REPO_ROOT / "backend",
            REPO_ROOT / "ms_agent_framework_adapter",
            REPO_ROOT / "multi_agent_workflows",
        ]
        excluded_paths = {
            REPO_ROOT / "multi_agent_workflows" / "dabstep_benchmark_runner.py",
            REPO_ROOT / "multi_agent_workflows" / "microsoft_anonymized_benchmark_runner.py",
            REPO_ROOT / "multi_agent_workflows" / "vds_desktop_benchmark_runner.py",
        }
        violations: list[str] = []
        for root in scan_roots:
            for path in root.rglob("*.py"):
                if path in excluded_paths:
                    continue
                text = path.read_text().lower()
                for term in forbidden_terms:
                    if term in text:
                        violations.append(f"{path.relative_to(REPO_ROOT)} contains {term}")
                for label, pattern in forbidden_patterns.items():
                    if pattern.search(text):
                        violations.append(f"{path.relative_to(REPO_ROOT)} contains {label}")
        self.assertEqual([], violations)

    def test_benchmark_runner_does_not_pass_answer_or_task_id_to_agent(self) -> None:
        calls: list[dict[str, str]] = []

        class FakeWorkflow:
            def __init__(self, context_dir: pathlib.Path) -> None:
                self.context_dir = context_dir

            @classmethod
            def from_dabstep_context(cls, context_dir: pathlib.Path, **_kwargs):
                return cls(context_dir)

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

            with patch("multi_agent_workflows.dabstep_benchmark_runner.DataAnalysisMultiAgentWorkflow", FakeWorkflow):
                run_dabstep_multi_agent_benchmark(dataset_root=dataset_root, split="dev", limit=1, output_dir=dataset_root / "out")

        self.assertEqual(
            [{"question": "Which country has the most transactions?", "guidelines": "Answer with a country code.", "execution_mode": "auto"}],
            calls,
        )

    def test_microsoft_runner_does_not_pass_answer_or_task_id_to_agent(self) -> None:
        calls: list[dict[str, str]] = []

        class FakeWorkflow:
            @classmethod
            def from_uploaded_tables(cls, tables, **_kwargs):
                return cls()

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
            test_dir = dataset_root / "VDS_DAB风格测试集_20260521"
            test_dir.mkdir(parents=True)
            (dataset_root / "table.csv").write_text("col\n1\n")
            (test_dir / "微软数据集_DAB风格问题和标准答案.jsonl").write_text(
                json.dumps(
                    {
                        "task_id": "secret-ms-task",
                        "question": "2026年5月服务客户数是多少？",
                        "guidelines": "答案只返回整数。",
                        "answer": "1",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

            with patch("multi_agent_workflows.microsoft_anonymized_benchmark_runner.DataAnalysisMultiAgentWorkflow", FakeWorkflow):
                run_microsoft_anonymized_benchmark(dataset_root=dataset_root, limit=1, output_dir=dataset_root / "out")

        self.assertEqual(
            [{"question": "2026年5月服务客户数是多少？", "guidelines": "答案只返回整数。", "execution_mode": "auto"}],
            calls,
        )

    def test_uploaded_table_runner_does_not_pass_answer_or_task_id_to_agent(self) -> None:
        calls: list[dict[str, str]] = []

        class FakeWorkflow:
            @classmethod
            def from_uploaded_tables(cls, tables, **_kwargs):
                return cls()

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
            table_path = dataset_root / "table.csv"
            test_path = dataset_root / "tasks.jsonl"
            table_path.write_text("col\n1\n")
            test_path.write_text(
                json.dumps(
                    {
                        "task_id": "secret-upload-task",
                        "question": "Which value appears most often?",
                        "guidelines": "Answer with text.",
                        "source_file": str(table_path),
                        "answer": "NL",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

            with patch("multi_agent_workflows.uploaded_table_benchmark_runner.DataAnalysisMultiAgentWorkflow", FakeWorkflow):
                run_uploaded_table_benchmark(
                    dataset_root=dataset_root,
                    test_set=test_path,
                    limit=1,
                    output_dir=dataset_root / "out",
                )

        self.assertEqual(
            [{"question": "Which value appears most often?", "guidelines": "Answer with text.", "execution_mode": "auto"}],
            calls,
        )

    def test_vds_desktop_runner_does_not_pass_answer_or_task_id_to_agent(self) -> None:
        calls: list[dict[str, str]] = []

        class FakeWorkflow:
            @classmethod
            def from_uploaded_tables(cls, tables, **_kwargs):
                return cls()

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
            root = pathlib.Path(temp_dir)
            question_path = root / "questions.xlsx"
            answer_path = root / "answers.xlsx"
            data_root = root / "data"
            data_root.mkdir()
            pd.DataFrame([{"题号": "S01", "BI测试问题": "本周ARR最高的Top1客户？", "口径提示": "只返回客户。"}]).to_excel(
                question_path,
                sheet_name="SaaSBI问题",
                index=False,
            )
            pd.DataFrame([{"题号": "S01", "标准GPT答案": "云启客户01"}]).to_excel(
                answer_path,
                sheet_name="五类答案汇总",
                index=False,
            )
            pd.DataFrame([{"客户名称": "云启客户01", "是否本周/上周": "本周", "ARR_row": 1.0}]).to_excel(
                data_root / "QueryGPT_SaaS订阅数据_单表版.xlsx",
                index=False,
            )

            with patch("multi_agent_workflows.vds_desktop_benchmark_runner.DataAnalysisMultiAgentWorkflow", FakeWorkflow):
                run_vds_desktop_benchmark(
                    question_workbook=question_path,
                    answer_workbook=answer_path,
                    data_root=data_root,
                    output_dir=root / "out",
                    sheet="SaaSBI问题",
                )

        self.assertEqual(
            [{"question": "本周ARR最高的Top1客户？", "guidelines": "只返回客户。", "execution_mode": "auto"}],
            calls,
        )


class _FakeResponse:
    answer = "NL"
    success = True
    debug = {"operation": "fake"}
    result = {"value": None}
    logic_form = {"output_format": {}}
    verification = {}
    warnings: list[str] = []
    errors: list[str] = []


class _FakeTrace:
    run_id = "run_fake"

    def to_dict(self) -> dict[str, str]:
        return {"run_id": self.run_id}


if __name__ == "__main__":
    unittest.main()
