"""Tests for reusable Chinese VDS BI period-comparison capabilities."""

from __future__ import annotations

import unittest

import pandas as pd

from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.core.intent_parser import parse_generic_table_question
from data_agent_core.executors.pandas_executor import execute_plan
from data_agent_core.llm.client import MockLLMClient
from data_agent_core.llm.planner import complete_stage_with_llm


class VdsBiCapabilitiesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tables = {
            "sales": pd.DataFrame(
                [
                    {"门店名称": "A店", "商圈": "核心", "项目类别": "品类A", "是否本周/上周": "本周", "PSD_row": 120.0, "AT_row": 50.0},
                    {"门店名称": "B店", "商圈": "社区", "项目类别": "品类A", "是否本周/上周": "本周", "PSD_row": 180.0, "AT_row": 30.0},
                    {"门店名称": "C店", "商圈": "社区", "项目类别": "品类B", "是否本周/上周": "本周", "PSD_row": 90.0, "AT_row": 10.0},
                    {"门店名称": "A店", "商圈": "核心", "项目类别": "品类A", "是否本周/上周": "上周", "PSD_row": 200.0, "AT_row": 10.0},
                    {"门店名称": "B店", "商圈": "社区", "项目类别": "品类A", "是否本周/上周": "上周", "PSD_row": 100.0, "AT_row": 40.0},
                    {"门店名称": "C店", "商圈": "社区", "项目类别": "品类B", "是否本周/上周": "上周", "PSD_row": 80.0, "AT_row": 20.0},
                    {"门店名称": "A店", "商圈": "核心", "项目类别": "品类A", "是否本周/上周": "上上周", "PSD_row": 160.0, "AT_row": 8.0},
                ]
            )
        }

    def _execute(self, question: str):
        logic = parse_generic_table_question(question, self.tables)
        result = execute_plan(build_analysis_plan(logic), {"tables": self.tables})
        self.assertTrue(result.success, result.errors)
        return logic, result.value

    def test_period_rank_decline_and_rise_parse_chinese_metric_and_entity(self) -> None:
        logic, value = self._execute("本周PSD与上周相比，排名下降最多的Top2门店？")

        self.assertEqual("vds_period_rank_change", logic.operation)
        self.assertEqual("PSD_row", logic.parameters["metric"])
        self.assertEqual("门店名称", logic.parameters["entity"])
        self.assertEqual("decline", logic.parameters["direction"])
        self.assertEqual("A店", value[0]["门店名称"])

    def test_period_delta_top_supports_increase_decrease_and_optional_filters(self) -> None:
        logic, value = self._execute("本周与上周相比，PSD增加最多的Top2门店？")
        filtered_logic, filtered = self._execute("本周与上周相比，品类A的PSD减少最多的Top10门店？")

        self.assertEqual("vds_period_delta_top", logic.operation)
        self.assertEqual("increase", logic.parameters["direction"])
        self.assertEqual("B店", value[0]["门店名称"])
        self.assertEqual("项目类别", filtered_logic.parameters["filter_column"])
        self.assertEqual("品类A", filtered_logic.parameters["filter_value"])
        self.assertEqual("A店", filtered[0]["门店名称"])

    def test_growth_count_share_and_threshold_count_are_generic(self) -> None:
        _, count_share = self._execute("本周PSD较上周增长的门店数量和占比？")
        threshold_logic, threshold = self._execute("本周PSD环比增长率超过10%的门店有多少家？")

        self.assertEqual(2, count_share["count"])
        self.assertAlmostEqual(66.666666, count_share["share"], places=5)
        self.assertEqual("vds_period_threshold_count", threshold_logic.operation)
        self.assertEqual(2, threshold)

    def test_vds_period_parser_supports_other_domains(self) -> None:
        tables = {
            "saas": pd.DataFrame(
                [
                    {"客户名称": "甲客户", "是否本周/上周": "本周", "ARR_row": 3000.0},
                    {"客户名称": "乙客户", "是否本周/上周": "本周", "ARR_row": 2000.0},
                    {"客户名称": "甲客户", "是否本周/上周": "上周", "ARR_row": 1000.0},
                    {"客户名称": "乙客户", "是否本周/上周": "上周", "ARR_row": 2500.0},
                ]
            )
        }
        logic = parse_generic_table_question("本周ARR与上周相比，排名上升最多的Top10客户？", tables)
        result = execute_plan(build_analysis_plan(logic), {"tables": tables})

        self.assertEqual("vds_period_rank_change", logic.operation)
        self.assertEqual("客户名称", logic.parameters["entity"])
        self.assertTrue(result.success, result.errors)
        self.assertEqual("甲客户", result.value[0]["客户名称"])

    def test_current_filtered_metric_top_preserves_entity_and_metric_code(self) -> None:
        tables = {
            "saas": pd.DataFrame(
                [
                    {
                        "客户名称": "甲客户",
                        "区域": "华南",
                        "套餐名称": "Pro",
                        "订阅状态": "流失",
                        "实施复杂度": "高",
                        "是否本周/上周": "本周",
                        "订阅收入": 10.0,
                        "ARR_row": 1000.0,
                        "CHR_row": 0.8,
                        "NRR_row": 1.1,
                    },
                    {
                        "客户名称": "乙客户",
                        "区域": "华北",
                        "套餐名称": "Growth",
                        "订阅状态": "暂停",
                        "实施复杂度": "低",
                        "是否本周/上周": "本周",
                        "订阅收入": 20.0,
                        "ARR_row": 3000.0,
                        "CHR_row": 0.5,
                        "NRR_row": 0.8,
                    },
                    {
                        "客户名称": "丙客户",
                        "区域": "华东",
                        "套餐名称": "Pro",
                        "订阅状态": "正常续费",
                        "实施复杂度": "中",
                        "是否本周/上周": "本周",
                        "订阅收入": 999999.0,
                        "ARR_row": 9000.0,
                        "CHR_row": 0.9,
                        "NRR_row": 0.9,
                    },
                    {
                        "客户名称": "丁客户",
                        "区域": "华东",
                        "套餐名称": "Pro",
                        "订阅状态": "暂停",
                        "实施复杂度": "高",
                        "是否本周/上周": "上周",
                        "订阅收入": 1000.0,
                        "ARR_row": 5000.0,
                        "CHR_row": 0.99,
                        "NRR_row": 1.2,
                    },
                    {
                        "客户名称": "戊客户",
                        "区域": "华中",
                        "套餐名称": "Pro",
                        "订阅状态": "暂停",
                        "实施复杂度": "低",
                        "是否本周/上周": "本周",
                        "订阅收入": 1.0,
                        "ARR_row": 2000.0,
                        "CHR_row": 0.7,
                        "NRR_row": 1.3,
                    },
                    {
                        "客户名称": "己客户",
                        "区域": "华南",
                        "套餐名称": "Starter",
                        "订阅状态": "正常续费",
                        "实施复杂度": "高",
                        "是否本周/上周": "本周",
                        "订阅收入": 500000.0,
                        "ARR_row": 4000.0,
                        "CHR_row": 0.4,
                        "NRR_row": 0.7,
                    },
                ]
            )
        }

        logic = parse_generic_table_question("本周流失和暂停对ARR影响最大的Top10客户？", tables)
        result = execute_plan(build_analysis_plan(logic), {"tables": tables})
        pro_logic = parse_generic_table_question("本周Pro套餐CHR最高的Top10客户？", tables)
        pro_result = execute_plan(build_analysis_plan(pro_logic), {"tables": tables})
        pause_logic = parse_generic_table_question("本周暂停客户ARR最高的前2个客户", tables)
        pause_result = execute_plan(build_analysis_plan(pause_logic), {"tables": tables})
        low_logic = parse_generic_table_question("本周正常续费客户NRR最低的Top5客户", tables)
        low_result = execute_plan(build_analysis_plan(low_logic), {"tables": tables})

        self.assertEqual("vds_current_filtered_metric_top", logic.operation)
        self.assertEqual("ARR_row", logic.parameters["metric"])
        self.assertEqual("客户名称", logic.parameters["entity"])
        self.assertEqual(["流失", "暂停"], logic.parameters["value_filters"]["订阅状态"])
        self.assertTrue(result.success, result.errors)
        self.assertEqual(["乙客户", "戊客户", "甲客户"], [row["客户名称"] for row in result.value])
        self.assertNotIn("区域", result.value[0])

        self.assertEqual("vds_current_filtered_metric_top", pro_logic.operation)
        self.assertEqual("CHR_row", pro_logic.parameters["metric"])
        self.assertEqual(["Pro"], pro_logic.parameters["value_filters"]["套餐名称"])
        self.assertNotIn("实施复杂度", pro_logic.parameters["value_filters"])
        self.assertTrue(pro_result.success, pro_result.errors)
        self.assertEqual(["丙客户", "甲客户", "戊客户"], [row["客户名称"] for row in pro_result.value])

        self.assertTrue(pause_result.success, pause_result.errors)
        self.assertEqual(["乙客户", "戊客户"], [row["客户名称"] for row in pause_result.value])
        self.assertTrue(low_result.success, low_result.errors)
        self.assertEqual(["己客户", "丙客户"], [row["客户名称"] for row in low_result.value])
        self.assertEqual("asc", low_logic.parameters["sort_order"])

    def test_current_threshold_peer_anomaly_and_rate_top_are_generic(self) -> None:
        tables = {
            "learning": pd.DataFrame(
                [
                    {"校区名称": "甲校区", "学区": "东部", "城市": "上海", "人员类型": "新学员", "是否本周/上周": "本周", "CR_row": 0.70, "AST_row": 300.0},
                    {"校区名称": "乙校区", "学区": "东部", "城市": "上海", "人员类型": "新学员", "是否本周/上周": "本周", "CR_row": 0.90, "AST_row": 50.0},
                    {"校区名称": "丙校区", "学区": "西部", "城市": "成都", "人员类型": "老学员", "是否本周/上周": "本周", "CR_row": 0.95, "AST_row": 40.0},
                    {"校区名称": "甲校区", "学区": "东部", "城市": "上海", "人员类型": "新学员", "是否本周/上周": "上周", "CR_row": 0.60, "AST_row": 120.0},
                    {"校区名称": "乙校区", "学区": "东部", "城市": "上海", "人员类型": "新学员", "是否本周/上周": "上周", "CR_row": 0.95, "AST_row": 40.0},
                    {"校区名称": "丙校区", "学区": "西部", "城市": "成都", "人员类型": "老学员", "是否本周/上周": "上周", "CR_row": 0.70, "AST_row": 20.0},
                ]
            )
        }
        threshold_logic = parse_generic_table_question("本周新学员CR低于80%的校区Top10？", tables)
        threshold = execute_plan(build_analysis_plan(threshold_logic), {"tables": tables})
        anomaly_logic = parse_generic_table_question("本周AST高于同学区平均值2倍的校区有哪些？", tables)
        anomaly = execute_plan(build_analysis_plan(anomaly_logic), {"tables": tables})
        rate_logic = parse_generic_table_question("本周城市维度CR环比增长率Top10？", tables)
        rate = execute_plan(build_analysis_plan(rate_logic), {"tables": tables})

        self.assertEqual("vds_current_threshold_top", threshold_logic.operation)
        self.assertEqual("人员类型", threshold_logic.parameters["filter_column"])
        self.assertTrue(threshold.success, threshold.errors)
        self.assertEqual("甲校区", threshold.value[0]["校区名称"])
        self.assertEqual("vds_peer_anomaly", anomaly_logic.operation)
        self.assertTrue(anomaly.success, anomaly.errors)
        self.assertEqual("甲校区", anomaly.value[0]["校区名称"])
        self.assertEqual("vds_period_rate_top", rate_logic.operation)
        self.assertTrue(rate.success, rate.errors)
        self.assertEqual("成都", rate.value[0]["城市"])

    def test_current_category_share_top_is_generic(self) -> None:
        tables = {
            "learning": pd.DataFrame(
                [
                    {"校区名称": "甲校区", "状态": "已退课", "是否本周/上周": "本周", "CR_row": 0.1},
                    {"校区名称": "甲校区", "状态": "学习中", "是否本周/上周": "本周", "CR_row": 0.2},
                    {"校区名称": "乙校区", "状态": "已退课", "是否本周/上周": "本周", "CR_row": 0.3},
                    {"校区名称": "乙校区", "状态": "已退课", "是否本周/上周": "本周", "CR_row": 0.4},
                    {"校区名称": "乙校区", "状态": "学习中", "是否本周/上周": "本周", "CR_row": 0.5},
                    {"校区名称": "乙校区", "状态": "已退课", "是否本周/上周": "上周", "CR_row": 0.6},
                ]
            )
        }
        logic = parse_generic_table_question("本周已退课人数占比最高的Top10校区？", tables, "已退课记录数/本周校区总记录数。")
        result = execute_plan(build_analysis_plan(logic), {"tables": tables})

        self.assertEqual("vds_current_category_share_top", logic.operation)
        self.assertEqual("状态", logic.parameters["category_column"])
        self.assertEqual("已退课", logic.parameters["category_value"])
        self.assertTrue(result.success, result.errors)
        self.assertEqual("乙校区", result.value[0]["校区名称"])
        self.assertAlmostEqual(66.666666, result.value[0]["share"], places=5)

    def test_llm_stage_payload_serializes_pandas_timestamps(self) -> None:
        result = complete_stage_with_llm(
            llm_client=MockLLMClient(),
            stage_name="verifier",
            stage_goal="verify timestamp-safe payload",
            question="本周PSD与上周相比，排名下降最多的Top10门店？",
            guidelines="",
            context_summary={},
            payload={"rows": [{"日期": pd.Timestamp("2026-05-22"), "PSD_row": 1.0}]},
            required_output={"reasoning_summary": "string"},
        )

        self.assertEqual("verifier", result.stage_name)
        self.assertGreaterEqual(result.confidence, 0.0)


if __name__ == "__main__":
    unittest.main()
