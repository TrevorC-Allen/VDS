"""Tests for comparison answer rubric scoring."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.score_comparison_answers import load_comparison_rows, score_markdown, score_row, score_row_with_llm, summarize


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


class _LowFrameworkJudgeClient:
    def complete_json(self, messages: list[dict[str, str]], temperature: float = 0.0) -> dict[str, object]:
        return {
            "pair_similarity": 7,
            "standard": {
                "semantic_similarity": 9,
                "factuality": 9,
                "instruction_following": 9,
                "truthfulness": 9,
                "completeness": 9,
                "text_framework_alignment": 9,
                "issues": [],
                "notes": [],
            },
            "candidate": {
                "semantic_similarity": 8,
                "factuality": 9,
                "instruction_following": 8,
                "truthfulness": 9,
                "completeness": 5,
                "text_framework_alignment": 4,
                "issues": [],
                "notes": ["facts are mostly right but answer is not GPT-like"],
            },
            "verdict": {"reason": "VDS 事实没有明显错误，但不像网页端 GPT。"},
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
                "已帮你看了这个数据，核心结论是：这是一份零售交易明细，适合先看销售额、商品、客户、时间和国家分布。\n\n"
                "简要结论：\n"
                "- 已读取 1 个表，总计 541,909 行、8 列。\n"
                "- 关键字段包括 Quantity、UnitPrice、InvoiceDate、CustomerID 和 Country。\n"
                "- 可以优先检查缺失、负值/极端值、国家分布和后续趋势分析方向。\n\n"
                "口径说明：数据范围为当前上传表；这里是概览判断，尚未做业务指标聚合。\n\n"
                "如果你愿意，下一步可以继续看：\n"
                "1. 哪些商品销售额最高\n"
                "2. 哪些国家订单最多\n"
                "3. 哪些记录存在异常"
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

    def test_llm_judge_caps_non_gpt_like_data_answer_even_when_factual(self) -> None:
        row = {
            "case_id": "generic_uploaded_001",
            "question": "看一下这个数据。",
            "expected_route": "dataset_overview",
            "standard_answer": "GPT reference answer",
            "candidate_answer": "已读取 1 个表，包含订单、客户和商品字段，可以继续分析。",
            "comparison_status": "failed",
            "missing_terms": [],
            "number_checks": [],
        }

        scored = score_row_with_llm(row, _LowFrameworkJudgeClient(), min_acceptable=75.0)

        candidate = scored["answers"]["candidate"]
        self.assertLessEqual(candidate["total_score"], 55.0)
        self.assertFalse(candidate["acceptable"])
        self.assertEqual(scored["verdict"]["label"], "standard_higher")

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

    def test_summary_reports_acceptance_buckets_and_unexpected_not_applicable(self) -> None:
        ordinary_row = {
            "case_id": "generic_uploaded_001",
            "category": "general_uploaded",
            "difficulty_bucket": "ordinary",
            "capability_family": "overview",
            "question": "看一下这个数据。",
            "expected_route": "dataset_overview",
            "standard_answer": "已读取 1 个表，包含字段、缺失、质量问题和下一步建议。",
            "candidate_answer": (
                "核心结论是：已读取 1 个表，可以先做数据概览。\n\n"
                "简要结论：\n- 包含字段、缺失和质量问题检查。\n\n"
                "口径说明：基于当前上传数据范围。\n\n下一步可以继续看核心指标。"
            ),
            "comparison_status": "passed",
            "missing_terms": [],
            "number_checks": [],
        }
        complex_row = {
            "case_id": "generic_business_002",
            "category": "adaptive_business",
            "difficulty_bucket": "complex",
            "capability_family": "trend",
            "question": "这个数据能不能做趋势、环比或同比？",
            "expected_route": "analysis",
            "standard_answer": "可以基于时间字段和指标字段做趋势分析，但同比需要同周期数据。",
            "candidate_answer": "Not Applicable",
            "comparison_status": "failed",
            "missing_terms": [],
            "number_checks": [],
        }

        rows = [score_row(ordinary_row, min_acceptable=75.0), score_row(complex_row, min_acceptable=75.0)]
        summary = summarize(rows)

        self.assertEqual(summary["unexpected_not_applicable_count"], 1)
        self.assertEqual(summary["acceptance_buckets"]["ordinary"]["required_pass_rate"], 1.0)
        self.assertEqual(summary["acceptance_buckets"]["complex"]["required_pass_rate"], 0.9)
        self.assertFalse(summary["acceptance_passed"])
        self.assertIn("trend", summary["capability_failures"])

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
        self.assertIn("**reference 回答**", markdown)
        self.assertNotIn("**我的标准回复**", markdown)
        self.assertIn("当前没有上传文件", markdown)
        self.assertIn("**VDS 实际回复**", markdown)
        self.assertIn("上传数据后", markdown)

    def test_review_markdown_uses_deepseek_label_when_source_is_deepseek(self) -> None:
        row = {
            "case_id": "generic_uploaded_001",
            "question": "看一下这个数据。",
            "expected_route": "dataset_overview",
            "standard_answer_source": "deepseek_reference",
            "reference_answer_label": "deepseek",
            "standard_answer": "deepseek 回答。",
            "candidate_answer": "VDS 回答。",
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
                    "source_answer_label": "deepseek",
                    "standard_average_total": scored["answers"]["standard"]["total_score"],
                    "candidate_average_total": scored["answers"]["candidate"]["total_score"],
                    "average_pair_similarity": scored["pair_similarity"],
                    "needs_human_review_count": 1,
                    "verdict_counts": {scored["verdict"]["label"]: 1},
                },
                "rows": [scored],
            }
        )

        self.assertIn("- deepseek average total:", markdown)
        self.assertIn("**deepseek 回答**", markdown)
        self.assertNotIn("**我的标准回复**", markdown)

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

    def test_loads_gpt_markdown_shape(self) -> None:
        markdown = """# Generic Dataset Comparison

## B_uploaded_general_data_understanding

### generic_uploaded_001 - general_uploaded

- Question: 看一下这个数据。
- Expected route: dataset_overview
- Answer label: gpt
- Answer source: browser_gpt_reference
- Comparison status: passed

**gpt 回答**

网页端 GPT 回答。

**VDS 实际回复**

VDS 回答。
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "comparison.md"
            path.write_text(markdown, encoding="utf-8")
            rows = load_comparison_rows(path)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reference_answer_label"], "gpt")
        self.assertEqual(rows[0]["standard_answer_source"], "browser_gpt_reference")
        self.assertIn("网页端 GPT 回答", rows[0]["standard_answer"])

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
