"""Tests for comparison answer rubric scoring."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.score_comparison_answers import load_comparison_rows, score_markdown, score_row, score_row_with_llm


class _FakeJudgeClient:
    def complete_json(self, messages: list[dict[str, str]], temperature: float = 0.0) -> dict[str, object]:
        return {
            "pair_similarity": 8,
            "standard": {
                "semantic_similarity": 8,
                "factuality": 8,
                "instruction_following": 8,
                "truthfulness": 8,
                "completeness": 5,
                "text_framework_alignment": 7,
                "issues": [],
                "notes": ["shorter"],
            },
            "candidate": {
                "semantic_similarity": 8,
                "factuality": 9,
                "instruction_following": 9,
                "truthfulness": 9,
                "completeness": 9,
                "text_framework_alignment": 9,
                "issues": [],
                "notes": ["more complete"],
            },
            "verdict": {"reason": "VDS 更完整，但需要人工确认。"},
        }


class ScoreComparisonAnswersTest(unittest.TestCase):
    def test_accepts_good_answers_with_different_wording(self) -> None:
        row = {
            "case_id": "generic_general_001",
            "question": "你好",
            "expected_route": "chat_without_dataset",
            "standard_answer": "你好，我可以帮你理解数据、解释字段、检查缺失和异常。当前没有上传文件，所以不能给出具体数据结论。",
            "candidate_answer": "你好，我可以先讨论分析目标和指标口径；上传数据后再基于真实文件做字段、缺失、异常和趋势分析，不会编造业务结论。",
            "comparison_status": "failed",
            "missing_terms": ["没有上传文件"],
            "number_checks": [],
        }

        scored = score_row(row, min_acceptable=75.0)

        self.assertTrue(scored["answers"]["standard"]["acceptable"])
        self.assertTrue(scored["answers"]["candidate"]["acceptable"])
        self.assertIn(scored["verdict"]["label"], {"both_acceptable_similarity_or_quality", "close_call"})

    def test_candidate_higher_is_flagged_for_review(self) -> None:
        row = {
            "case_id": "generic_uploaded_001",
            "question": "看一下这个数据。",
            "expected_route": "dataset_overview",
            "standard_answer": "已读取数据，可以继续做分析。",
            "candidate_answer": (
                "已读取 1 个表，总计 541,909 行、8 列。这个表是零售交易明细，包含 Quantity、UnitPrice、"
                "InvoiceDate、CustomerID 和 Country。可以先看字段角色、缺失、负值/极端值、国家分布和后续趋势分析方向。"
            ),
            "comparison_status": "failed",
            "missing_terms": ["质量问题"],
            "number_checks": [{"label": "total_rows", "expected": 541909.0, "tolerance": 5419.09, "passed": True}],
        }

        scored = score_row(row, min_acceptable=75.0)

        self.assertGreater(scored["answers"]["candidate"]["total_score"], scored["answers"]["standard"]["total_score"])
        self.assertEqual(scored["verdict"]["label"], "candidate_higher_needs_human_review")
        self.assertTrue(scored["verdict"]["needs_human_review"])

    def test_llm_judge_scores_drive_totals_but_candidate_higher_needs_review(self) -> None:
        row = {
            "case_id": "generic_uploaded_001",
            "question": "看一下这个数据。",
            "expected_route": "dataset_overview",
            "standard_answer": "已读取 1 个表。",
            "candidate_answer": "已读取 1 个表，并说明字段、质量问题和下一步分析。",
            "comparison_status": "failed",
            "missing_terms": [],
            "number_checks": [],
        }

        scored = score_row_with_llm(row, _FakeJudgeClient(), min_acceptable=75.0)

        self.assertEqual(scored["judge_mode"], "llm")
        self.assertGreater(scored["answers"]["candidate"]["total_score"], scored["answers"]["standard"]["total_score"])
        self.assertEqual(scored["verdict"]["label"], "candidate_higher_needs_human_review")
        self.assertEqual(scored["verdict"]["llm_reason"], "VDS 更完整，但需要人工确认。")

    def test_raw_detail_dump_is_penalized(self) -> None:
        raw_rows = "\n".join(
            f"536365,85123A,WHITE HANGING HEART T-LIGHT HOLDER,{index},2.55,17850,United Kingdom"
            for index in range(12)
        )
        row = {
            "case_id": "generic_uploaded_002",
            "question": "这个数据主要讲什么？",
            "expected_route": "dataset_overview",
            "standard_answer": "这个数据主要是零售交易明细，适合看商品、客户、时间和金额趋势。",
            "candidate_answer": raw_rows,
            "comparison_status": "failed",
            "missing_terms": [],
            "number_checks": [],
        }

        scored = score_row(row, min_acceptable=75.0)

        self.assertIn("raw_detail_dump_risk", scored["answers"]["candidate"]["issues"])
        self.assertLess(scored["answers"]["candidate"]["dimensions"]["truthfulness"], 7.0)

    def test_review_markdown_includes_original_question_and_answers(self) -> None:
        row = {
            "case_id": "generic_general_001",
            "question": "你好",
            "expected_route": "chat_without_dataset",
            "standard_answer": "当前没有上传文件，所以不能给出具体数据结论。",
            "candidate_answer": "上传数据后我可以基于真实数据分析，不会编造业务结论。",
            "comparison_status": "failed",
            "missing_terms": [],
            "number_checks": [],
        }
        scored = score_row(row, min_acceptable=75.0)
        scored["verdict"]["needs_human_review"] = True
        markdown = score_markdown(
            {
                "source": "comparison.json",
                "generated_at": "2026-05-26T00:00:00",
                "summary": {
                    "case_count": 1,
                    "standard_average_total": scored["answers"]["standard"]["total_score"],
                    "candidate_average_total": scored["answers"]["candidate"]["total_score"],
                    "average_pair_similarity": scored["pair_similarity"],
                    "needs_human_review_count": 1,
                    "verdict_counts": {scored["verdict"]["label"]: 1},
                },
                "rows": [scored],
            }
        )

        self.assertIn("- Question: 你好", markdown)
        self.assertIn("**我的标准回复**", markdown)
        self.assertIn("当前没有上传文件", markdown)
        self.assertIn("**VDS 实际回复**", markdown)
        self.assertIn("上传数据后", markdown)

    def test_loads_existing_markdown_shape(self) -> None:
        markdown = """# Generic Dataset Comparison

## A_no_file_general

### generic_general_001 - general_no_file

- Question: 你好
- Expected route: chat_without_dataset
- Comparison status: failed

**我的标准回复**

当前没有上传文件，所以不能给出具体数据结论。

**VDS 实际回复**

上传数据后我可以基于真实数据分析，不会编造业务结论。

**对比细节**

- Missing terms: 没有上传文件
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "comparison.md"
            path.write_text(markdown, encoding="utf-8")
            rows = load_comparison_rows(path)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["case_id"], "generic_general_001")
        self.assertIn("当前没有上传文件", rows[0]["standard_answer"])
        self.assertIn("上传数据后", rows[0]["candidate_answer"])

    def test_markdown_loader_does_not_swallow_next_group_heading(self) -> None:
        markdown = """# Generic Dataset Comparison

## A_no_file_general

### generic_general_004 - general_no_file

- Question: 你支持多文件对比吗？
- Expected route: chat_without_dataset
- Comparison status: passed

**我的标准回复**

支持多文件。

**VDS 实际回复**

支持多文件对比。


## B_uploaded_general_data_understanding

### generic_uploaded_001 - general_uploaded

- Question: 看一下这个数据。
- Expected route: dataset_overview
- Comparison status: passed

**我的标准回复**

已读取 1 个表。

**VDS 实际回复**

已读取 1 个表。
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "comparison.md"
            path.write_text(markdown, encoding="utf-8")
            rows = load_comparison_rows(path)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["candidate_answer"], "支持多文件对比。")
        self.assertNotIn("B_uploaded", rows[0]["candidate_answer"])


if __name__ == "__main__":
    unittest.main()
