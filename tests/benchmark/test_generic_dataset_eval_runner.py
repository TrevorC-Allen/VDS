"""Tests for generic dataset eval comparison artifacts."""

from __future__ import annotations

import unittest

from scripts.run_generic_dataset_eval import comparison_markdown, gpt_like_style_checks


class GenericDatasetEvalRunnerTest(unittest.TestCase):
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
