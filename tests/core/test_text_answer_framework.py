"""Tests for GPT-like Chinese answer text framing."""

from __future__ import annotations

import unittest

from data_agent_core.output.text_answer_framework import apply_text_answer_framework


class TextAnswerFrameworkTest(unittest.TestCase):
    def test_overview_answer_has_gpt_like_sections_and_business_story(self) -> None:
        response = {
            "success": True,
            "answer_type": "overview",
            "answer": "这张表有 120 行、8 列。",
            "overview_report": {
                "table": "销售明细",
                "source_file": "sales.xlsx",
                "row_count": 120,
                "column_count": 8,
                "likely_meaning": "订单或交易明细，适合看金额、数量、客户/商品和时间趋势。",
                "metric_column": "销售额",
                "dimension_column": "区域",
                "period_column": "月份",
                "field_meanings": [{"field": "客户ID"}, {"field": "商品"}],
            },
            "result": {"columns": ["指标", "数值"], "rows": [{"指标": "记录数", "数值": "120"}]},
            "verification": {"passed": True, "notes": ["Dataset overview was computed from the uploaded table."]},
        }

        framed = apply_text_answer_framework(response, question="这个数据主要讲什么？")["answer"]

        self.assertIn("核心结论是", framed)
        self.assertIn("简要结论：", framed)
        self.assertIn("口径说明：", framed)
        self.assertIn("如果你愿意，下一步可以继续看：", framed)
        self.assertIn("订单或交易明细", framed)
        self.assertIn("指标=销售额", framed)
        self.assertNotEqual("这张表有 120 行、8 列。", framed.strip())

    def test_target_vs_actual_frame_surfaces_best_worst_and_scope(self) -> None:
        response = {
            "success": True,
            "answer_type": "table",
            "answer": "2026-03 完成率最高，2026-05 完成率最低。",
            "logic_form": {
                "operation": "target_actual_completion",
                "source_tables": ["月度目标实际表"],
            },
            "result": {
                "columns": ["月份", "分销目标", "实际分销金额", "完成率"],
                "rows": [
                    {"月份": "2026-03", "分销目标": 229038.78, "实际分销金额": 281687.32, "完成率": 122.99},
                    {"月份": "2026-04", "分销目标": 160000, "实际分销金额": 132000, "完成率": 82.5},
                    {"月份": "2026-05", "分销目标": 200000, "实际分销金额": 13780, "完成率": 6.89},
                ],
            },
            "source_references": [
                {
                    "file_name": "demo.xlsx",
                    "tables": [{"table_name": "月度目标实际表", "row_count": 3, "column_count": 4}],
                }
            ],
        }

        framed = apply_text_answer_framework(response, question="目标 vs 实际哪个月份完成率最好？")["answer"]

        self.assertIn("2026-03 表现最好", framed)
        self.assertIn("122.99", framed)
        self.assertIn("2026-05", framed)
        self.assertIn("目标来源=", framed)
        self.assertIn("实际来源=", framed)
        self.assertIn("完成率=", framed)

    def test_cleaning_frame_keeps_simulation_boundary(self) -> None:
        response = {
            "success": True,
            "answer_type": "cleaning_simulation",
            "answer": "建议先做清洗模拟。",
            "result": {
                "columns": ["表名", "规则", "影响行数", "影响比例", "建议"],
                "rows": [{"表名": "订单表", "规则": "缺失值", "影响行数": 12, "影响比例": "10%", "建议": "先标记"}],
                "value": {
                    "table_count": 1,
                    "total_rows": 120,
                    "estimated_impacted_rows": 12,
                    "estimated_impacted_rate": "10%",
                    "direct_action_rows": 3,
                    "direct_action_rate": "2.5%",
                },
            },
        }

        framed = apply_text_answer_framework(response, question="这个数据怎么清洗？")["answer"]

        self.assertIn("不会直接修改原始数据", framed)
        self.assertIn("用户确认", framed)
        self.assertIn("缺失值", framed)
        self.assertIn("口径说明：", framed)

    def test_not_applicable_becomes_clarification_frame(self) -> None:
        response = {
            "success": False,
            "answer_type": "text",
            "answer": "Not Applicable",
            "logic_form": {"operation": "not_applicable"},
            "warnings": ["缺少利润率字段和月份过滤条件"],
            "errors": [],
        }

        framed = apply_text_answer_framework(response, question="请计算 2026 年利润率趋势")["answer"]

        self.assertNotEqual("Not Applicable", framed.strip())
        self.assertIn("暂时不能可靠回答", framed)
        self.assertIn("可计算字段", framed)
        self.assertIn("时间范围或周期粒度", framed)
        self.assertIn("指标口径", framed)
        self.assertIn("最少需要补充", framed)

    def test_framework_removes_internal_artifact_markers(self) -> None:
        response = {
            "success": True,
            "answer_type": "text",
            "answer": "trace: task_id=abc standard_answer=secret\n上海最高。",
            "logic_form": {"operation": "ranking", "source_tables": ["销售表"]},
            "result": {"columns": ["城市", "销售额"], "rows": [{"城市": "上海", "销售额": 300}]},
        }

        framed = apply_text_answer_framework(response, question="哪个城市销售额最高？")["answer"].lower()

        self.assertIn("上海", framed)
        for forbidden in ("task_id", "standard_answer", "trace", "scorer"):
            self.assertNotIn(forbidden, framed)

    def test_simple_top1_ranking_answer_stays_short_and_avoids_audit_noise(self) -> None:
        response = {
            "success": True,
            "answer_type": "table",
            "answer": "qa_store_b.csv 中销售额最高的产品是香蕉，销售额 90。",
            "logic_form": {"operation": "ranking", "source_tables": ["qa_store_b"], "parameters": {"table": "qa_store_b"}},
            "result": {"columns": ["product", "sales"], "rows": [{"product": "香蕉", "sales": 90}]},
            "verification": {
                "passed": True,
                "notes": ["Verifier checked execution success, optional backend consistency, and semantic metric contract."],
            },
        }

        framed = apply_text_answer_framework(response, question="qa_store_b.csv里面哪个产品销售额最高？")["answer"]

        self.assertIn("香蕉", framed)
        self.assertIn("90", framed)
        self.assertNotIn("Verifier checked execution success", framed)
        self.assertNotIn("semantic metric contract", framed)
        self.assertNotIn("当前结果表只返回", framed)
        self.assertNotIn("仍需按当前数据范围和指标口径解读", framed)
        self.assertNotIn("排序口径应以结果表的聚合字段和排序字段为准", framed)

    def test_simple_top1_derived_metric_keeps_short_answer_with_formula_scope(self) -> None:
        response = {
            "success": True,
            "answer_type": "table",
            "answer": "上海利润率最高。",
            "logic_form": {
                "operation": "ranking",
                "source_tables": ["city_profit"],
                "parameters": {
                    "table": "city_profit",
                    "dimension": "city",
                    "metric": "利润率",
                    "derived_metric": {
                        "name": "利润率",
                        "numerator": "profit",
                        "denominator": "sales",
                        "formula": "sum(profit)/sum(sales)",
                    },
                },
            },
            "result": {"columns": ["city", "利润率"], "rows": [{"city": "上海", "利润率": 0.4}]},
            "verification": {
                "passed": True,
                "notes": ["Verifier checked execution success, optional backend consistency, and semantic metric contract."],
            },
        }

        framed = apply_text_answer_framework(response, question="哪个城市利润率最高？")["answer"]

        self.assertIn("上海", framed)
        self.assertIn("40.00%", framed)
        self.assertIn("sum(profit)/sum(sales)", framed)
        self.assertNotIn("当前结果表只返回", framed)
        self.assertNotIn("仍需按当前数据范围和指标口径解读", framed)

    def test_simple_top1_trusted_join_keeps_short_answer_with_join_scope(self) -> None:
        response = {
            "success": True,
            "answer_type": "table",
            "answer": "北京销售额最高。",
            "logic_form": {
                "operation": "ranking",
                "source_tables": ["orders", "customers"],
                "parameters": {"dimension": "city", "metric": "sales"},
                "join_plan": {
                    "trusted": True,
                    "left_table": "orders",
                    "right_table": "customers",
                    "left_key": "customer_id",
                    "right_key": "customer_id",
                },
            },
            "result": {"columns": ["city", "sales"], "rows": [{"city": "北京", "sales": 170}]},
        }

        framed = apply_text_answer_framework(response, question="哪个城市总销售额最高？")["answer"]

        self.assertIn("北京", framed)
        self.assertIn("170", framed)
        self.assertIn("orders.customer_id", framed)
        self.assertIn("customers.customer_id", framed)
        self.assertNotIn("当前结果表只返回", framed)
        self.assertNotIn("仍需按当前数据范围和指标口径解读", framed)


if __name__ == "__main__":
    unittest.main()
