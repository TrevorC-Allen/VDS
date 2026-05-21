"""Tests for reusable Chinese retail analytics capabilities.

The fixtures are synthetic and are not copied from benchmark answers.
"""

from __future__ import annotations

import unittest

import pandas as pd

from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.core.intent_parser import parse_generic_table_question
from data_agent_core.executors.pandas_executor import execute_plan
from data_agent_core.output.response_builder import format_answer


class ChineseRetailCapabilitiesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tables = {
            "v_trd_dist_ord_dtl": pd.DataFrame(
                [
                    {
                        "sign_time": "2026-05-02",
                        "sign_amt": 100.005,
                        "sign_box_cnt": 2.5,
                        "emp_name": "张三",
                        "p_emp_name": "赵经理",
                        "cust_code": "C1",
                        "cust_name": "一号店",
                        "ctg_name": "天然水",
                        "cmdt_tag_name": "普通本品",
                        "ord_type_name": "业代订单",
                        "sku_code": "S1",
                        "sku_name": "绿茶SKU",
                        "ord_status_name": "已签收",
                    },
                    {
                        "sign_time": "2026-05-03",
                        "sign_amt": 200.0,
                        "sign_box_cnt": 3.0,
                        "emp_name": "李四",
                        "p_emp_name": "赵经理",
                        "cust_code": "C2",
                        "cust_name": "二号店",
                        "ctg_name": "东方树叶",
                        "cmdt_tag_name": "活动本品",
                        "ord_type_name": "业代订单",
                        "sku_code": "S2",
                        "sku_name": "红茶SKU",
                        "ord_status_name": "已取消",
                    },
                    {
                        "sign_time": "2026-04-03",
                        "sign_amt": 50.0,
                        "sign_box_cnt": 1.0,
                        "emp_name": "张三",
                        "p_emp_name": "赵经理",
                        "cust_code": "C1",
                        "cust_name": "一号店",
                        "ctg_name": "东方树叶",
                        "cmdt_tag_name": "普通本品",
                        "ord_type_name": "业代订单",
                        "sku_code": "S3",
                        "sku_name": "乌龙茶SKU",
                        "ord_status_name": "已签收",
                    },
                ]
            ),
            "v_trd_dist_ord_dtl_1d_rt": pd.DataFrame(
                [
                    {"sign_time": "2026-05-19", "sign_amt": 25.0, "ord_status_name": "全部签收", "ctg_name": "天然水", "emp_name": "张三"},
                    {"sign_time": "2026-05-19", "sign_amt": 75.0, "ord_status_name": "全部签收", "ctg_name": "东方树叶", "emp_name": "张三"},
                    {"sign_time": "2026-05-19", "sign_amt": 125.0, "ord_status_name": "全部签收", "ctg_name": "天然水", "emp_name": "李四"},
                ]
            ),
            "v_chl_route_plan_cust_cnt_1d_df": pd.DataFrame(
                [
                    {"visit_date": "2026-05-19", "cust_code": "C1", "cust_name": "一号店", "emp_name": "张三", "route_code": "R1"},
                    {"visit_date": "2026-05-19", "cust_code": "C2", "cust_name": "二号店", "emp_name": "张三", "route_code": "R1"},
                ]
            ),
            "终端客户月度维表": pd.DataFrame(
                [
                    {"年月": 202605, "终端客户编码": "C1", "终端客户": "一号店", "是否合约店": "是", "是否冰柜客户": "是", "终端客户状态": "正常", "主任": "赵经理", "业代": "张三", "合作开始日期": "2026-05-01"},
                    {"年月": 202605, "终端客户编码": "C2", "终端客户": "二号店", "是否合约店": "否", "是否冰柜客户": "否", "终端客户状态": "正常", "主任": "赵经理", "业代": "张三", "合作开始日期": "2026-04-01"},
                ]
            ),
            "v_mkt_dsp_actv_mi": pd.DataFrame(
                [
                    {"execute_ym": 202605, "dsp_name": "水堆", "cust_code": "C1", "cust_name": "一号店", "confirm_amt": 10.0, "p_emp_name": "赵经理", "check_result_name": "合格"},
                    {"execute_ym": 202605, "dsp_name": "水堆", "cust_code": "C2", "cust_name": "二号店", "confirm_amt": 5.0, "p_emp_name": "赵经理", "check_result_name": "不合格"},
                    {"execute_ym": 202605, "dsp_name": "我司冰柜", "cust_code": "C2", "cust_name": "二号店", "confirm_amt": 8.0, "p_emp_name": "赵经理", "check_result_name": "合格"},
                ]
            ),
            "v_chl_visit_dtl": pd.DataFrame(
                [
                    {"visit_date": "2026-05-19", "emp_name": "张三", "p_emp_name": "赵经理", "cust_code": "C1", "if_visit_sucess": 1, "target_flag": 1},
                    {"visit_date": "2026-05-20", "emp_name": "张三", "p_emp_name": "赵经理", "cust_code": "C2", "if_visit_sucess": 0, "target_flag": 1},
                    {"visit_date": "2026-05-20", "emp_name": "李四", "p_emp_name": "赵经理", "cust_code": "C3", "if_visit_sucess": 1, "target_flag": 0},
                ]
            ),
            "ads_trd_dist_ord_target_emp_1m_df": pd.DataFrame(
                [{"stat_month": 202605, "emp_name": "张三", "p_emp_name": "赵经理", "target": 2200.0}]
            ),
            "ads_trd_dist_ord_target_mgr_1m_df": pd.DataFrame(
                [{"stat_month": 202605, "mgr_name": "赵经理", "target_amt": 5000.0}]
            ),
            "ads_trd_time_prg_df": pd.DataFrame([{"month_id": 202605, "dist_day_cnt": 22}]),
        }

    def _answer(self, question: str, guidelines: str = "") -> str:
        logic = parse_generic_table_question(question, self.tables, guidelines)
        result = execute_plan(build_analysis_plan(logic), {"tables": self.tables})
        self.assertTrue(result.success, result.errors)
        return format_answer(result.value, logic.output_format)

    def test_distribution_ranking_uses_history_table_and_half_up_money(self) -> None:
        answer = self._answer("2026年5月历史分销金额最高的业代是谁？", "答案只返回业代姓名。")
        self.assertEqual(answer, "李四")
        money = self._answer("张三在2026年5月的历史分销金额是多少？", "答案只返回数字，保留2位小数。")
        self.assertEqual(money, "100.01")

    def test_route_contract_product_quantity_uses_store_set_join(self) -> None:
        answer = self._answer("张三在2026-05-19计划拜访线路上的合约店，2026年5月东方树叶分销数量是多少？", "答案只返回数字，保留3位小数。")
        self.assertEqual(answer, "0.000")

    def test_daily_progress_rate_uses_today_amount_target_and_dist_days(self) -> None:
        answer = self._answer("以2026-05-19为业务日期，张三当天分销金额相对日目标的分销进度是多少？", "答案只返回百分比，保留2位小数。日目标=2026年5月分销目标/2026年5月分销天数。")
        self.assertEqual(answer, "100.00%")

    def test_display_pass_rate_and_signed_store_count(self) -> None:
        pass_rate = self._answer("2026年5月水堆陈列检查合格率是多少？", "答案只返回百分比，保留2位小数。")
        self.assertEqual(pass_rate, "50.00%")
        count = self._answer("2026年5月签约了“我司冰柜”陈列项的门店家数是多少？", "答案只返回整数。")
        self.assertEqual(count, "1")

    def test_retail_target_counts_achievement_and_service_rates(self) -> None:
        target_count = self._answer("2026年5月有分销目标的业代有多少名？", "答案只返回整数。")
        self.assertEqual(target_count, "1")
        achievement = self._answer("张三在2026年5月的分销目标达成率是多少？", "答案只返回百分比，保留2位小数。")
        self.assertEqual(achievement, "4.55%")
        service_count = self._answer("2026年5月服务客户数是多少？", "答案只返回整数。")
        self.assertEqual(service_count, "2")
        contract_rate = self._answer("2026年5月服务客户中合约店占比是多少？", "答案只返回百分比，保留2位小数。")
        self.assertEqual(contract_rate, "50.00%")

    def test_retail_record_counts_field_values_and_feature_count(self) -> None:
        freezer_count = self._answer("2026年5月终端客户月度维表中冰柜客户有多少家？", "答案只返回整数。")
        self.assertEqual(freezer_count, "1")
        display_count = self._answer("2026年5月陈列计划中不合格记录有多少条？", "答案只返回整数。")
        self.assertEqual(display_count, "1")
        visit_count = self._answer("2026年5月计划拜访记录有多少条？", "答案只返回整数。")
        self.assertEqual(visit_count, "2")
        statuses = self._answer("2026年5月历史分销明细中出现了哪些订单状态？", "答案只返回列表。")
        self.assertEqual(statuses, "已取消, 已签收")

    def test_retail_today_route_sku_and_visit_success_capabilities(self) -> None:
        today_emp = self._answer("今日分销明细中分销金额最高的业代是谁？", "答案只返回姓名。")
        self.assertEqual(today_emp, "李四")
        sku = self._answer("2026年5月历史分销金额最高的SKU是什么？", "答案只返回SKU名称。")
        self.assertEqual(sku, "红茶SKU")
        category = self._answer("张三在2026-05-19计划拜访线路上的历史分销金额贡献最高的品类是什么？", "答案只返回品类。")
        self.assertEqual(category, "东方树叶")
        success_rate = self._answer("张三在2026年5月的拜访成功率是多少？", "答案只返回百分比，保留2位小数。")
        self.assertEqual(success_rate, "50.00%")


if __name__ == "__main__":
    unittest.main()
