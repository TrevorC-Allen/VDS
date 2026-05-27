"""Tests for generic dataset eval comparison artifacts."""

from __future__ import annotations

import json
from types import SimpleNamespace
import unittest

from scripts.run_generic_dataset_eval import (
    apply_standard_answer_source,
    build_comparison_rows,
    comparison_markdown,
    gpt_like_style_checks,
)


class FakeGPTReferenceClient:
    def __init__(self) -> None:
        self.config = SimpleNamespace(provider="openai", model="gpt-reference-test")
        self.messages: list[list[dict[str, str]]] = []

    def complete_json(self, messages: list[dict[str, str]], temperature: float = 0.0) -> dict[str, object]:
        self.messages.append(messages)
        return {
            "standard_answer": "已帮你看了这个数据，核心结论是：GPT reference 标准答案。",
            "notes": ["grounded in computed facts"],
            "confidence": 0.91,
        }


class GenericDatasetEvalRunnerTest(unittest.TestCase):
    def _case(self) -> dict[str, object]:
        return {
            "case_id": "generic_uploaded_001",
            "ae_group": "B_uploaded_general_data_understanding",
            "category": "general_uploaded",
            "question": "这个数据主要讲什么？",
            "expected_route": "dataset_overview",
            "scoring_dimensions": ["grounded"],
            "standard_answer": "deterministic template should not be sent as the standard answer",
            "expected_facts": {"table_count": 1},
            "required_terms": ["数据"],
            "expected_numbers": [],
            "technical_checks": [],
            "standard_answer_policy": "old deterministic policy",
        }

    def _facts(self) -> dict[str, object]:
        return {
            "dataset_name": "demo",
            "table_count": 1,
            "total_rows": 2,
            "dataset_wide_notes": [],
            "schema_compare": {"summary": "单表数据。"},
            "tables": [
                {
                    "table_name": "demo_table",
                    "source_file": "demo.csv",
                    "sheet": None,
                    "row_count": 2,
                    "column_count": 2,
                    "columns": [{"name": "month", "type": "VARCHAR", "semantic_hints": ["time"], "sample_values": ["2026-01"]}],
                    "field_roles": {"time": ["month"], "metrics": [], "dimensions": [], "ids": []},
                    "quality_issues": [],
                    "missing": [],
                    "numeric": [],
                    "temporal": [],
                    "categorical": [],
                    "analysis_suggestions": [],
                    "cleaning_policy": {"rules": [], "requires_user_confirmation": True, "mutation_allowed": False},
                }
            ],
        }

    def test_formal_standard_answers_use_gpt_source(self) -> None:
        client = FakeGPTReferenceClient()

        cases, generation = apply_standard_answer_source([self._case()], self._facts(), source="gpt", llm_client=client)

        self.assertEqual(cases[0]["standard_answer"], "已帮你看了这个数据，核心结论是：GPT reference 标准答案。")
        self.assertEqual(cases[0]["standard_answer_source"], "gpt")
        self.assertEqual(cases[0]["standard_answer_model"], "openai:gpt-reference-test")
        self.assertEqual(generation["source"], "gpt")
        sent_payload = json.dumps(client.messages, ensure_ascii=False)
        self.assertIn("case_fact_hints", sent_payload)
        self.assertNotIn("deterministic template should not be sent", sent_payload)

    def test_deterministic_standard_source_is_marked_as_fallback_only(self) -> None:
        cases, generation = apply_standard_answer_source([self._case()], self._facts(), source="deterministic")

        self.assertEqual(cases[0]["standard_answer_source"], "deterministic_fallback")
        self.assertEqual(cases[0]["standard_answer_model"], "deterministic")
        self.assertIn("not a formal GPT reference", cases[0]["standard_answer_policy"])
        self.assertEqual(generation["source"], "deterministic_fallback")

    def test_comparison_rows_include_standard_answer_metadata(self) -> None:
        client = FakeGPTReferenceClient()
        cases, _generation = apply_standard_answer_source([self._case()], self._facts(), source="gpt", llm_client=client)

        rows = build_comparison_rows(cases, candidate_answers={}, candidate_score=None)

        self.assertEqual(rows[0]["standard_answer_source"], "gpt")
        self.assertEqual(rows[0]["standard_answer_model"], "openai:gpt-reference-test")
        self.assertIn("GPT reference answer", rows[0]["standard_answer_policy"])

    def test_comparison_markdown_truncates_raw_detail_like_candidate_answers(self) -> None:
        raw_rows = "\n".join(
            f"536365,85123A,WHITE HANGING HEART T-LIGHT HOLDER,{index},2.55,17850,United Kingdom"
            for index in range(80)
        )
        markdown = comparison_markdown(
            {
                "dataset_name": "uk_retail",
                "candidate_score": {"passed": 0, "total": 1, "pass_rate": 0},
                "comparison": [
                    {
                        "ae_group": "B_uploaded_general_data_understanding",
                        "case_id": "generic_uploaded_002",
                        "category": "general_uploaded",
                        "question": "这个数据主要讲什么？",
                        "expected_route": "dataset_overview",
                        "comparison_status": "failed",
                        "standard_answer": "标准答案 " + ("字段说明很长，" * 300),
                        "candidate_answer": raw_rows,
                        "missing_terms": [],
                        "number_checks": [],
                    }
                ],
            }
        )

        self.assertIn("已截断", markdown)
        self.assertIn("vds_answers.jsonl", markdown)
        self.assertIn("standard_answers.jsonl", markdown)
        self.assertLess(markdown.count("WHITE HANGING HEART T-LIGHT HOLDER"), 25)

    def test_gpt_like_checks_reject_compact_value_sequence_dump(self) -> None:
        checks = gpt_like_style_checks(
            {
                "case_id": "generic_basic_001",
                "category": "basic_data_understanding",
                "question": "每个文件分别有多少行、多少列？",
                "expected_route": "dataset_overview",
            },
            "2025-01-01 00:00:00, 89, 2025-02-01 00:00:00, 95, "
            "2025-03-01 00:00:00, 101, 2025-04-01 00:00:00, 88",
        )

        by_name = {item["name"]: item["passed"] for item in checks}
        self.assertFalse(by_name["not_raw_detail_dump"])

    def test_gpt_like_checks_allow_guardrail_answer_to_name_forbidden_artifacts(self) -> None:
        checks = gpt_like_style_checks(
            {
                "case_id": "generic_tech_001",
                "category": "technical_review_guardrails",
                "question": "不要展示 raw prompt、trace、SQL 或标准答案，只给用户可读依据。",
                "expected_route": "dataset_overview",
            },
            "不会展示 raw prompt、trace、SQL、标准答案、scorer 或后端审计 JSON。我只会给用户可读的问题理解、数据依据、计算口径和结果边界。",
        )

        by_name = {item["name"]: item["passed"] for item in checks}
        self.assertTrue(by_name["no_internal_artifact_markers"])


if __name__ == "__main__":
    unittest.main()
