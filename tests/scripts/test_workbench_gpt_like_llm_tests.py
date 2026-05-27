"""Tests for Workbench GPT-like quality gate utilities."""

from __future__ import annotations

import tempfile
import unittest
from unittest import mock
from pathlib import Path

from scripts import run_workbench_gpt_like_llm_tests as gate


class _FakeJudgeClient:
    def complete_json(self, messages: list[dict[str, str]], temperature: float = 0.0) -> dict[str, object]:
        return {
            "problem_understanding": 5,
            "data_grounding": 4,
            "answer_usefulness": 5,
            "gpt_like_structure": 4,
            "safety_boundary": 5,
            "overall": "pass",
            "severity": "none",
            "reason": "回答有结论、有依据、无内部泄漏。",
            "required_followup": "",
        }


class WorkbenchGPTLikeGateTest(unittest.TestCase):
    def test_select_cases_filters_quick_without_full_only_cases(self) -> None:
        cases = [
            {"id": "A", "question": "你好", "suite": "quick", "tags": ["api"]},
            {"id": "B", "question": "字段", "suite": "full", "tags": ["api"]},
            {"id": "C", "question": "UI", "suite": "full", "tags": ["ui"]},
        ]

        quick = gate.select_cases(cases, "quick")
        full = gate.select_cases(cases, "full")
        ui = gate.select_cases(cases, "ui")

        self.assertEqual(["A"], [case["id"] for case in quick])
        self.assertEqual(["A", "B", "C"], [case["id"] for case in full])
        self.assertEqual(["C"], [case["id"] for case in ui])

    def test_deterministic_checks_detect_not_applicable_and_forbidden_terms(self) -> None:
        case = {
            "id": "CHAT-002",
            "question": "我能干什么？",
            "must_not_include": ["Not Applicable", "task_id"],
            "severity_on_fail": "P0",
        }
        response = {
            "success": True,
            "answer_type": "analysis",
            "answer": "Not Applicable because task_id matched.",
            "result": {"columns": [], "rows_head": []},
        }

        checks = gate.deterministic_checks(case, response)

        self.assertFalse(checks["passed"])
        self.assertEqual("P0", checks["severity"])
        issues = {item["issue"] for item in checks["issues"]}
        self.assertIn("unexpected_not_applicable", issues)
        self.assertIn("forbidden_token:task_id", issues)

    def test_judge_payload_uses_public_response_only(self) -> None:
        case = {
            "id": "OVERVIEW-001",
            "question": "这个数据主要讲什么？",
            "dataset_fixture": "sales_cn",
            "capability_family": "dataset_overview",
            "gpt_like_expectation": "总结数据。",
        }
        public_response = {
            "success": True,
            "answer_type": "overview",
            "answer": "这是一份销售表。",
            "result": {"columns": ["指标", "数值"], "rows_head": [["行数", "5"]]},
        }
        deterministic = {"passed": True, "severity": "none", "issues": []}

        judgement = gate.judge_public_response(case, public_response, deterministic, _FakeJudgeClient())

        self.assertEqual("pass", judgement["overall"])
        self.assertEqual("none", judgement["severity"])
        self.assertEqual(5.0, judgement["scores"]["problem_understanding"])

    def test_artifact_writer_creates_required_test_run_document(self) -> None:
        case = {
            "case_id": "CHAT-001",
            "suite": "quick",
            "tags": ["api"],
            "question": "没有文件时你能做什么？",
            "dataset_fixture": "no_dataset",
            "capability_family": "chat_without_dataset",
            "expected_answer_type": "chat",
            "gpt_like_expectation": "说明能力边界。",
            "conversation_id": "",
            "latency_ms": 1.0,
            "public_response": {"answer_type": "chat", "answer": "上传数据后可以分析。"},
            "deterministic": {"passed": True, "severity": "none", "issues": []},
            "llm_judgement": {
                "overall": "pass",
                "severity": "none",
                "reason": "OK",
                "required_followup": "",
                "scores": gate.empty_scores(),
            },
            "severity": "none",
            "overall": "pass",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary = gate.build_summary(
                run_id="2026-05-26-1330-quick-gpt-like",
                suite="quick",
                base_url="http://127.0.0.1:8001",
                output_dir=root / "out",
                cases=[case],
                elapsed_seconds=0.1,
            )
            (root / "out").mkdir()
            (root / "docs").mkdir()
            gate.write_quality_artifacts(summary, [case], root / "out", root / "docs")

            self.assertTrue((root / "out" / "summary.json").exists())
            self.assertTrue((root / "out" / "responses.jsonl").exists())
            self.assertTrue((root / "out" / "llm_judgements.jsonl").exists())
            doc = root / "docs" / "2026-05-26-1330-quick-gpt-like.md"
            self.assertTrue(doc.exists())
            self.assertIn("required durable test evidence", doc.read_text(encoding="utf-8"))

    def test_formal_mock_provider_is_rejected(self) -> None:
        with mock.patch.dict("os.environ", {"VDS_LLM_PROVIDER": "mock"}, clear=True):
            with self.assertRaises(SystemExit):
                gate.load_quality_judge_client(allow_mock=False)


if __name__ == "__main__":
    unittest.main()
