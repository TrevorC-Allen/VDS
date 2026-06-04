"""Direct-answer rendering tests for response builder output."""

from __future__ import annotations

import unittest

from data_agent_core.contracts.analysis_contracts import AnalysisPlan, LogicForm, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.contracts.verification_contracts import VerificationResult
from data_agent_core.core.conversation_actions import build_next_actions
from data_agent_core.output.response_builder import build_response
from data_agent_core.output.text_answer_framework import apply_text_answer_framework, describe_trend


class ResponseRendererDirectAnswerTest(unittest.TestCase):
    def test_topn_answer_first_sentence_lists_results(self) -> None:
        response = apply_text_answer_framework(
            {
                "success": True,
                "answer_type": "table",
                "answer": "已完成排序。",
                "logic_form": {"operation": "ranking", "parameters": {"metric": "销售额", "dimension": "城市"}},
                "result": {
                    "columns": ["城市", "销售额"],
                    "rows": [{"城市": "深圳", "销售额": 586}, {"城市": "上海", "销售额": 428}, {"城市": "北京", "销售额": 414}],
                },
            },
            question="销售额最高的 3 个城市是哪些？",
        )

        first = response["answer"].split("。", 1)[0]
        self.assertIn("销售额最高的 3 个城市是：深圳（销售额 586）、上海（销售额 428）、北京（销售额 414）", first)
        self.assertNotIn("数据摘要（关键指标）", response["answer"])
        sections = response.get("structured_answer_sections") or {}
        self.assertEqual(["销售额最高的 3 个城市是：深圳（销售额 586）、上海（销售额 428）、北京（销售额 414）。"], sections.get("direct_answer"))
        self.assertIn("第 1 位 深圳（销售额=586）", " ".join(sections.get("key_results") or []))
        self.assertIn("把 Top 项继续按时间或区域拆分", sections.get("next_questions") or [])
        self.assertNotIn("###", response["answer"])

    def test_single_best_join_answer_first_sentence_gives_city_and_amount(self) -> None:
        response = apply_text_answer_framework(
            {
                "success": True,
                "answer_type": "table",
                "answer": "上海最高。",
                "logic_form": {
                    "operation": "ranking",
                    "source_tables": ["orders", "customers"],
                    "parameters": {"metric": "金额", "dimension": "城市"},
                    "join_plan": {
                        "trusted": True,
                        "left_table": "orders",
                        "right_table": "customers",
                        "left_key": "customer_id",
                        "right_key": "customer_id",
                    },
                },
                "result": {"columns": ["城市", "金额"], "rows": [{"城市": "上海", "金额": 325}]},
            },
            question="关联 orders 和 customers 后，金额最高的城市是哪个？",
        )

        self.assertTrue(response["answer"].startswith("关联 orders 和 customers 后，金额最高的城市是上海，金额为 325。"))

    def test_gap_answer_first_sentence_gives_differences(self) -> None:
        response = apply_text_answer_framework(
            {
                "success": True,
                "answer_type": "table",
                "answer": "",
                "logic_form": {"operation": "ranking", "parameters": {"metric": "销售额", "dimension": "城市"}},
                "result": {
                    "columns": ["城市", "销售额"],
                    "rows": [{"城市": "深圳", "销售额": 586}, {"城市": "上海", "销售额": 428}, {"城市": "北京", "销售额": 414}],
                },
            },
            question="Top 3 城市之间销售额差距是多少？",
        )

        self.assertTrue(response["answer"].startswith("Top 3 城市中，深圳比上海高 158，上海比北京高 14；北京比第一名深圳低 172。"))

    def test_trend_uses_sequence_not_first_last_only(self) -> None:
        self.assertIn("先升后降", describe_trend({"2026-01": 396, "2026-02": 550, "2026-03": 482}))
        response = apply_text_answer_framework(
            {
                "success": True,
                "answer_type": "table",
                "answer": "",
                "logic_form": {"operation": "trend", "parameters": {"metric": "销售额", "dimension": "月份"}},
                "result": {
                    "columns": ["月份", "销售额"],
                    "rows": [{"月份": "2026-01", "销售额": 396}, {"月份": "2026-02", "销售额": 550}, {"月份": "2026-03", "销售额": 482}],
                },
            },
            question="按月份看销售额趋势？",
        )

        self.assertIn("先升后降", response["answer"])
        self.assertNotIn("整体呈上升趋势", response["answer"])

    def test_quality_answer_contains_field_level_table_even_when_zero(self) -> None:
        response = apply_text_answer_framework(
            {
                "success": True,
                "answer_type": "table",
                "answer": "",
                "logic_form": {"operation": "data_quality_report"},
                "result": {
                    "columns": ["字段", "类型", "缺失数", "重复数", "异常数"],
                    "rows": [
                        {"字段": "城市", "类型": "text", "缺失数": 0, "重复数": 0, "异常数": 0},
                        {"字段": "销售额", "类型": "number", "缺失数": 0, "重复数": 0, "异常数": 0},
                    ],
                },
            },
            question="检查数据质量",
        )

        self.assertIn("本次质量检查未发现缺失、重复或异常值", response["answer"])
        self.assertIn("| 字段 | 类型 | 缺失数 | 重复数 | 异常数 |", response["answer"])
        self.assertIn("| 销售额 | number | 0 | 0 | 0 |", response["answer"])

    def test_overview_response_result_exposes_field_type_list(self) -> None:
        logic = LogicForm(task_type="overview", operation="dataset_overview", output_format={"answer_type": "overview"})
        rows = [
            {"月份": "2026-01", "城市": "深圳", "销售额": 586, "订单数": 10},
            {"月份": "2026-02", "城市": "上海", "销售额": 428, "订单数": 8},
        ]
        response = build_response(
            run_id="run_overview_fields",
            user_question=UserQuestion(dataset_id="ds", question="看一下这个销售数据整体情况"),
            plan=AnalysisPlan(plan_id="plan", logic_form=logic),
            execution_result=ExecutionResult(backend="pandas", success=True, value=rows, columns=["月份", "城市", "销售额", "订单数"], rows=rows),
            verification=VerificationResult(passed=True),
        )

        self.assertEqual(["字段", "类型", "角色", "样例"], response.result["columns"])
        self.assertIn({"字段": "销售额", "类型": "number", "角色": "指标", "样例": 586}, response.result["rows"])
        self.assertIn("字段清单和类型见下表", response.answer)

    def test_next_actions_do_not_repeat_current_question(self) -> None:
        actions = build_next_actions(
            question="按城市看销售额排名前3。",
            plan={"operation": "ranking", "parameters": {"metric": "销售额", "dimension": "城市"}},
            rows=[{"城市": "深圳", "销售额": 586}, {"城市": "上海", "销售额": 428}],
        )

        self.assertTrue(all(action.get("question") != "按城市看销售额排名前3。" for action in actions))
        self.assertTrue(all("排名前3" not in str(action.get("question") or "") or "按城市" not in str(action.get("question") or "") for action in actions))

    def test_semantic_failed_does_not_render_solved_answer(self) -> None:
        response = apply_text_answer_framework(
            {
                "success": False,
                "answer_type": "table",
                "answer": "上海销售额最高，销售额为 325。",
                "logic_form": {"operation": "ranking", "parameters": {"metric": "销售额", "dimension": "城市"}},
                "verification": {"passed": False, "semantic_status": "failed"},
                "warnings": ["缺少可信关联键"],
                "result": {"columns": ["城市", "销售额"], "rows": [{"城市": "上海", "销售额": 325}]},
            },
            question="关联 orders 和 customers 后哪个城市销售额最高？",
        )

        self.assertIn("暂时不能可靠回答", response["answer"])
        self.assertNotIn("销售额最高的城市是上海", response["answer"])

    def test_insufficient_data_answer_sections_are_specific_not_boilerplate(self) -> None:
        response = apply_text_answer_framework(
            {
                "success": True,
                "answer_type": "table",
                "answer": "按城市统计订单金额，当前只有 2 个城市，无法返回 Top 5，因此返回 Top 2。",
                "logic_form": {
                    "operation": "ranking",
                    "parameters": {"metric": "订单金额", "dimension": "城市", "limit": 5},
                    "task_contract": {
                        "task_family": "topn",
                        "metric": "订单金额",
                        "dimension": "城市",
                        "required_n": 5,
                        "actual_distinct_count": 2,
                    },
                },
                "semantic_status": "passed_with_insufficient_data",
                "result": {
                    "columns": ["城市", "订单金额"],
                    "rows": [{"城市": "杭州", "订单金额": 136330.74}, {"城市": "上海", "订单金额": 98000}],
                },
            },
            question="订单金额最高的 Top 5 城市是哪些？",
        )

        self.assertTrue(response["answer"].startswith("按城市统计订单金额，当前只有 2 个城市，无法返回 Top 5"))
        self.assertNotIn("缺少指标口径、维表或映射关系", response["answer"])
        sections = response.get("structured_answer_sections") or {}
        caveats = " ".join(sections.get("caveats") or [])
        self.assertIn("当前只有 2 个城市，无法满足 Top 5", caveats)


if __name__ == "__main__":
    unittest.main()
