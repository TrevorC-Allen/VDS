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

        self.assertIn("数据摘要（关键指标）", framed)
        self.assertIn("分析洞察（发现了什么）", framed)
        self.assertIn("业务建议（可以采取什么行动）", framed)
        self.assertIn("口径与边界", framed)
        self.assertIn("下一步可继续分析", framed)
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
        self.assertIn("口径与边界", framed)

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
        self.assertNotIn("业务建议（可以采取什么行动）\n- 优先复核", framed)

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

    def test_scalar_number_delta_does_not_use_ranking_template(self) -> None:
        response = {
            "success": True,
            "answer_type": "number",
            "answer": "",
            "logic_form": {
                "operation": "mcc_change_delta",
                "source_tables": ["payments"],
                "filters": {"merchant": "Crossfit_Hanna", "year": 2023},
                "parameters": {"new_mcc": 5999},
            },
            "result": {
                "columns": ["answer"],
                "rows": [{"answer": 26210.609907000045}],
                "value": 26210.609907000045,
            },
            "debug": {"operation": "ranking_candidate_debug"},
            "insight": {
                "next_questions": [
                    "比较 Top 结果之间的answer差距有多大？",
                    "看低排名对象是否受缺失值影响？",
                ]
            },
        }

        framed = apply_text_answer_framework(
            response,
            question="Imagine the merchant Crossfit_Hanna had changed its MCC code to 5999 before 2023 started, what amount delta will it have to pay in fees for the year 2023?",
        )["answer"]

        self.assertIn("26,210.61", framed)
        self.assertNotIn("排名结果", framed)
        self.assertNotIn("关键排序结果", framed)
        self.assertNotIn("第 1 位", framed)
        self.assertNotIn("Top 结果", framed)
        self.assertNotIn("低排名", framed)
        self.assertEqual(
            [
                "按关键维度拆解这个数值",
                "对比相邻时间段或相关对象的同一指标",
                "检查异常值、缺失值或规则口径是否影响该数值",
            ],
            response["insight"]["next_questions"],
        )

    def test_multi_series_trend_frame_summarizes_top5_overall_patterns(self) -> None:
        response = {
            "success": True,
            "answer_type": "table",
            "answer": "已生成Top5品类趋势图。",
            "logic_form": {"operation": "retail_category_distribution_monthly_trend", "task_type": "trend"},
            "result": {
                "columns": ["月份", "天然水", "纯净水", "东方树叶", "水溶C100", "茶π"],
                "rows": [
                    {"月份": "2026年1月", "天然水": 300000, "纯净水": 120000, "东方树叶": 180000, "水溶C100": 150000, "茶π": 90000},
                    {"月份": "2026年2月", "天然水": 320000, "纯净水": 110000, "东方树叶": 190000, "水溶C100": 140000, "茶π": 95000},
                    {"月份": "2026年3月", "天然水": 330000, "纯净水": 130000, "东方树叶": 210000, "水溶C100": 135000, "茶π": 98000},
                    {"月份": "2026年4月", "天然水": 340000, "纯净水": 150000, "东方树叶": 260000, "水溶C100": 125000, "茶π": 102000},
                    {"月份": "2026年5月", "天然水": 345000, "纯净水": 240000, "东方树叶": 220000, "水溶C100": 120000, "茶π": 110000},
                ],
            },
        }

        framed = apply_text_answer_framework(response, question="请展示2026年1月至5月Top5品类历史分销金额趋势。")["answer"]

        self.assertIn("天然水 持续领先", framed)
        self.assertIn("纯净水 在 2026年5月 明显跃升", framed)
        self.assertIn("东方树叶 在 2026年4月 达到阶段峰值", framed)
        self.assertNotIn("水溶C100", framed.split("数据摘要（关键指标）", 1)[1].split("。", 1)[0])

    def test_repeated_sku_topn_result_surfaces_boundary_not_fake_grouping(self) -> None:
        response = {
            "success": True,
            "answer_type": "table",
            "answer": "返回 10 行 SKU 数据。",
            "logic_form": {"operation": "ranking", "parameters": {"metric": "分销金额", "dimension": "SKU编码"}},
            "result": {
                "columns": ["SKU编码", "SKU名称", "品类", "分销金额"],
                "rows": [
                    {
                        "SKU编码": "SK00100015",
                        "SKU名称": "农夫山泉-长白山天然矿泉水-380mL",
                        "品类": "天然矿泉水",
                        "分销金额": 100,
                    }
                    for _ in range(10)
                ],
            },
        }

        framed = apply_text_answer_framework(response, question="这 10 个 SKU 按品类分组汇总")["answer"]

        self.assertIn("口径与边界", framed)
        self.assertIn("没有返回 10 个不同SKU", framed)
        self.assertIn("未按 SKU 去重/聚合", framed)
        self.assertIn("先按 SKU 编码去重", framed)
        self.assertNotIn("头部品类集中度非常高", framed)

    def test_reasonableness_comparison_states_boundary_without_fake_judgment(self) -> None:
        response = {
            "success": True,
            "answer_type": "table",
            "answer": "深圳销售额 284，工单量 44。",
            "logic_form": {
                "operation": "aggregation",
                "filters": {"city": "深圳", "month": {"month": 3}},
                "parameters": {"dimension": "city", "metric": "sales", "metrics": ["sales", "tickets"]},
            },
            "result": {"columns": ["city", "sales", "tickets"], "rows": [{"city": "深圳", "sales": 284, "tickets": 44}]},
        }

        framed = apply_text_answer_framework(response, question="这个城市3月份的工单数量与销售额相比是否合理？")["answer"]

        self.assertIn("深圳 的sales 为 284，tickets 为 44", framed)
        self.assertIn("是否合理需要历史基准、业务阈值或同类对比", framed)
        self.assertIn("不能仅凭本次结果直接判断合理性", framed)
        self.assertIn("先定义合理性的业务基准", framed)


if __name__ == "__main__":
    unittest.main()
