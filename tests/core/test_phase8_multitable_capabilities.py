"""Phase 8 multi-file and multi-table capability tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from backend.services.data_agent_service import DataAgentService
from backend.storage.temp_file_store import TempFileStore
from data_agent_core.contracts.analysis_contracts import UserQuestion
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.core.intent_parser import parse_generic_table_question
from data_agent_core.core.logic_form import make_logic_form
from data_agent_core.executors.pandas_executor import execute_plan
from data_agent_core.llm.client import MockLLMClient
from data_agent_core.output.chart_planner import build_chart_spec
from data_agent_core.verifier.rule_checker import verify_execution


class Phase8MultiTableCapabilityTest(unittest.TestCase):
    def test_multi_file_routing_selects_inventory_table(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = DataAgentService(
                file_store=TempFileStore(Path(temp_dir) / "storage"),
                llm_client=MockLLMClient(),
            )
            tables = [
                {
                    "table_name": "销售文件",
                    "source_file": "销售文件.csv",
                    "rows": [
                        {"产品": "A", "销售额": 100},
                        {"产品": "B", "销售额": 300},
                        {"产品": "C", "销售额": 200},
                    ],
                },
                {
                    "table_name": "库存文件",
                    "source_file": "库存文件.csv",
                    "rows": [
                        {"产品": "A", "库存量": 10},
                        {"产品": "B", "库存量": 30},
                        {"产品": "C", "库存量": 80},
                    ],
                },
            ]

            sales = service.run_agent_with_inline_tables(question="哪个产品销售额最高？", tables=tables)
            inventory = service.run_agent_with_inline_tables(question="哪个产品库存量最高？", tables=tables)
            explicit_inventory = service.run_agent_with_inline_tables(question="库存文件里哪个产品库存量最高？", tables=tables)

        self.assertTrue(sales["success"])
        self.assertEqual({"产品": "B", "销售额": 300}, sales["result"]["rows"][0])
        self.assertEqual(["销售文件"], sales["debug"]["source_tables"])
        self.assertTrue(inventory["success"])
        self.assertEqual({"产品": "C", "库存量": 80}, inventory["result"]["rows"][0])
        self.assertEqual(["库存文件"], inventory["debug"]["source_tables"])
        self.assertTrue(explicit_inventory["success"])
        self.assertEqual({"产品": "C", "库存量": 80}, explicit_inventory["result"]["rows"][0])
        self.assertIn("explicit_table_mention", explicit_inventory["debug"]["table_selection_reason"])

    def test_join_plan_materializes_city_aggregation(self) -> None:
        tables = _orders_and_customers()
        ranking = _execute("哪个城市订单金额最高？", tables)
        aggregation = _execute("按城市统计订单金额", tables)

        self.assertTrue(ranking["result"].success, ranking["result"].errors)
        self.assertEqual([{"城市": "北京", "订单金额": 200}], ranking["result"].value)
        self.assertEqual(["订单表", "客户表"], ranking["logic"].source_tables)
        self.assertTrue(ranking["logic"].join_plan["trusted"])
        self.assertEqual("many_to_one", ranking["logic"].join_plan["relationship"])
        self.assertEqual(3, ranking["result"].debug["join_execution_summary"]["joined_rows"])
        self.assertTrue(aggregation["result"].success, aggregation["result"].errors)
        self.assertEqual(
            [{"城市": "上海", "订单金额": 150}, {"城市": "北京", "订单金额": 200}],
            aggregation["result"].value,
        )

    def test_untrusted_join_key_requires_clarification(self) -> None:
        tables = {
            "订单表": pd.DataFrame({"客户ID": ["C1", "C2"], "订单金额": [100, 200]}),
            "客户表": pd.DataFrame({"客户编号": ["X1", "X2"], "城市": ["上海", "北京"]}),
        }
        executed = _execute("按城市统计订单金额", tables)
        verification = verify_execution(
            executed["result"],
            plan=executed["plan"],
            user_question=UserQuestion(dataset_id="ds_phase8", question="按城市统计订单金额"),
        )

        self.assertFalse(executed["result"].success)
        self.assertFalse(executed["logic"].join_plan["trusted"])
        self.assertFalse(verification.passed)
        self.assertEqual("clarify_join_key", verification.correction_action["action"])

    def test_many_to_many_join_risk_is_not_silent_success(self) -> None:
        tables = {
            "订单表": pd.DataFrame({"客户ID": ["C1", "C2", "C1"], "订单金额": [100, 200, 50]}),
            "客户表": pd.DataFrame({"客户ID": ["C1", "C1", "C2"], "城市": ["上海", "杭州", "北京"]}),
        }
        executed = _execute("按城市统计订单金额", tables)
        verification = verify_execution(
            executed["result"],
            plan=executed["plan"],
            user_question=UserQuestion(dataset_id="ds_phase8", question="按城市统计订单金额"),
        )

        self.assertFalse(executed["result"].success)
        self.assertTrue(executed["logic"].join_plan["many_to_many_risk"])
        self.assertFalse(verification.passed)
        self.assertEqual("clarify_join_key", verification.correction_action["action"])

    def test_single_table_regression_still_ranks_normally(self) -> None:
        tables = {"sales": pd.DataFrame({"city": ["Shanghai", "Beijing", "Shanghai"], "sales": [100, 150, 200]})}
        executed = _execute("Which city has the highest sales?", tables)

        self.assertTrue(executed["result"].success, executed["result"].errors)
        self.assertEqual([{"city": "Shanghai", "sales": 300}], executed["result"].value)
        self.assertEqual(["sales"], executed["logic"].source_tables)
        self.assertEqual({}, executed["logic"].join_plan)

    def test_grouped_chart_request_aggregates_instead_of_returning_detail_rows(self) -> None:
        tables = {"sales": pd.DataFrame({"city": ["上海", "北京", "上海", "北京"], "sales": [100, 120, 140, 160]})}
        executed = _execute("按城市展示销售额，生成柱状图。", tables)
        verification = verify_execution(
            executed["result"],
            plan=executed["plan"],
            user_question=UserQuestion(dataset_id="ds_phase8", question="按城市展示销售额，生成柱状图。"),
        )
        chart = build_chart_spec(plan=executed["plan"], execution_result=executed["result"], verification_passed=verification.passed)

        self.assertTrue(executed["result"].success, executed["result"].errors)
        self.assertEqual("aggregation", executed["logic"].operation)
        rows_by_city = {row["city"]: row["sales"] for row in executed["result"].value}
        self.assertEqual({"上海": 240, "北京": 280}, rows_by_city)
        self.assertTrue(verification.passed, verification.issues)
        self.assertEqual("bar", chart.chart_type)
        self.assertEqual("city", chart.x)
        self.assertEqual("sales", chart.y)
        self.assertEqual(rows_by_city, {row["city"]: row["sales"] for row in chart.data})

    def test_same_schema_multi_file_question_unions_all_sources_before_ranking(self) -> None:
        tables = {
            "a": pd.DataFrame({"门店": ["A店"], "产品": ["苹果"], "sales": [150]}),
            "b": pd.DataFrame({"门店": ["B店"], "产品": ["苹果"], "sales": [170]}),
        }
        tables["a"].attrs["source_file"] = "a.csv"
        tables["b"].attrs["source_file"] = "b.csv"
        executed = _execute("A店和B店哪个门店总销售额最高？", tables)
        verification = verify_execution(
            executed["result"],
            plan=executed["plan"],
            user_question=UserQuestion(dataset_id="ds_phase8", question="A店和B店哪个门店总销售额最高？"),
        )

        self.assertTrue(executed["result"].success, executed["result"].errors)
        self.assertEqual("ranking", executed["logic"].operation)
        self.assertEqual(["a", "b"], executed["logic"].source_tables)
        self.assertEqual([{"门店": "B店", "sales": 170}], executed["result"].value)
        self.assertTrue(verification.passed, verification.issues)
        self.assertEqual(["a", "b"], executed["result"].debug["same_schema_union_summary"]["source_tables"])

    def test_explicit_file_question_keeps_requested_product_dimension(self) -> None:
        tables = {
            "qa_store_a": pd.DataFrame({"store": ["A店", "A店"], "product": ["苹果", "香蕉"], "sales": [80, 70]}),
            "qa_store_b": pd.DataFrame({"store": ["B店", "B店"], "product": ["苹果", "香蕉"], "sales": [80, 90]}),
        }
        tables["qa_store_a"].attrs["source_file"] = "qa_store_a.csv"
        tables["qa_store_b"].attrs["source_file"] = "qa_store_b.csv"

        executed = _execute("qa_store_b.csv里面哪个产品销售额最高？", tables)
        verification = verify_execution(
            executed["result"],
            plan=executed["plan"],
            user_question=UserQuestion(dataset_id="ds_phase8", question="qa_store_b.csv里面哪个产品销售额最高？"),
        )

        self.assertTrue(executed["result"].success, executed["result"].errors)
        self.assertEqual(["qa_store_b"], executed["logic"].source_tables)
        self.assertEqual("product", executed["logic"].parameters["dimension"])
        self.assertEqual([{"product": "香蕉", "sales": 90}], executed["result"].value)
        self.assertTrue(verification.passed, verification.issues)

    def test_verifier_rejects_requested_product_dimension_collapsed_to_store(self) -> None:
        table = pd.DataFrame({"store": ["B店"], "product": ["香蕉"], "sales": [90]})
        logic = make_logic_form(
            task_type="ranking",
            operation="ranking",
            parameters={"table": "qa_store_b", "metric": "sales", "dimension": "store", "aggregation": "sum"},
            output_format={"answer_type": "table"},
        )
        plan = build_analysis_plan(logic)
        result = execute_plan(plan, {"tables": {"qa_store_b": table}, "primary_table": "qa_store_b"})
        verification = verify_execution(
            result,
            plan=plan,
            user_question=UserQuestion(dataset_id="ds_phase8", question="qa_store_b.csv里面哪个产品销售额最高？"),
        )

        self.assertTrue(result.success, result.errors)
        self.assertFalse(verification.passed)
        self.assertEqual("repair_dimension_binding", verification.correction_action["action"])

    def test_verifier_accepts_category_dimension_alias_ctg_name(self) -> None:
        table = pd.DataFrame({"ctg_name": ["饮料", "零食"], "sales": [120, 80]})
        logic = make_logic_form(
            task_type="ranking",
            operation="ranking",
            parameters={"table": "sales", "metric": "sales", "dimension": "ctg_name", "aggregation": "sum"},
            output_format={"answer_type": "table"},
        )
        plan = build_analysis_plan(logic)
        result = execute_plan(plan, {"tables": {"sales": table}, "primary_table": "sales"})
        verification = verify_execution(
            result,
            plan=plan,
            user_question=UserQuestion(dataset_id="ds_phase8", question="哪个品类销售额最高？"),
        )

        self.assertTrue(result.success, result.errors)
        self.assertTrue(verification.passed, verification.semantic_verification_notes)

    def test_channel_synonym_binds_sales_channel_before_city(self) -> None:
        tables = {
            "sales": pd.DataFrame(
                {
                    "city": ["上海", "北京", "广州"],
                    "sales_channel": ["线上", "线下", "线上"],
                    "sales": [100, 250, 180],
                }
            )
        }
        executed = _execute("哪个来源渠道销售额最高？", tables)
        verification = verify_execution(
            executed["result"],
            plan=executed["plan"],
            user_question=UserQuestion(dataset_id="ds_phase8", question="哪个来源渠道销售额最高？"),
        )

        self.assertTrue(executed["result"].success, executed["result"].errors)
        self.assertEqual("sales_channel", executed["logic"].parameters["dimension"])
        self.assertEqual([{"sales_channel": "线上", "sales": 280}], executed["result"].value)
        self.assertTrue(verification.passed, verification.issues)

    def test_category_synonym_binds_product_category_before_city(self) -> None:
        tables = {
            "sales": pd.DataFrame(
                {
                    "city": ["上海", "北京", "广州"],
                    "product_category": ["饮料", "零食", "饮料"],
                    "sales": [100, 250, 180],
                }
            )
        }
        executed = _execute("哪个商品品类销售额最高？", tables)
        verification = verify_execution(
            executed["result"],
            plan=executed["plan"],
            user_question=UserQuestion(dataset_id="ds_phase8", question="哪个商品品类销售额最高？"),
        )

        self.assertTrue(executed["result"].success, executed["result"].errors)
        self.assertEqual("product_category", executed["logic"].parameters["dimension"])
        self.assertEqual([{"product_category": "饮料", "sales": 280}], executed["result"].value)
        self.assertTrue(verification.passed, verification.issues)

    def test_profit_margin_ranking_uses_derived_ratio_metric(self) -> None:
        tables = {"sales": pd.DataFrame({"city": ["上海", "北京"], "sales": [100, 280], "profit": [40, 56]})}
        executed = _execute("哪个城市利润率最高？", tables)
        verification = verify_execution(
            executed["result"],
            plan=executed["plan"],
            user_question=UserQuestion(dataset_id="ds_phase8", question="哪个城市利润率最高？"),
        )

        self.assertTrue(executed["result"].success, executed["result"].errors)
        self.assertEqual("ranking", executed["logic"].operation)
        self.assertEqual({"name": "利润率", "numerator": "profit", "denominator": "sales", "formula": "sum(profit)/sum(sales)"}, executed["logic"].parameters["derived_metric"])
        self.assertEqual([{"city": "上海", "利润率": 0.4}], executed["result"].value)
        self.assertTrue(verification.passed, verification.issues)

    def test_verifier_rejects_profit_margin_question_ranked_by_raw_sales(self) -> None:
        table = pd.DataFrame({"city": ["上海", "北京"], "sales": [100, 280], "profit": [40, 56]})
        logic = make_logic_form(
            task_type="ranking",
            operation="ranking",
            parameters={"table": "sales", "metric": "sales", "dimension": "city", "aggregation": "sum"},
            output_format={"answer_type": "table"},
        )
        plan = build_analysis_plan(logic)
        result = execute_plan(plan, {"tables": {"sales": table}, "primary_table": "sales"})
        verification = verify_execution(
            result,
            plan=plan,
            user_question=UserQuestion(dataset_id="ds_phase8", question="哪个城市利润率最高？"),
        )

        self.assertTrue(result.success, result.errors)
        self.assertFalse(verification.passed)
        self.assertEqual("repair_metric_definition", verification.correction_action["action"])

    def test_english_id_join_materializes_city_sales_ranking(self) -> None:
        tables = {
            "orders": pd.DataFrame({"customer_id": ["C1", "C2", "C1"], "sales": [100, 120, 70]}),
            "customers": pd.DataFrame({"customer_id": ["C1", "C2"], "city": ["北京", "上海"]}),
        }
        executed = _execute("哪个城市总销售额最高？", tables)
        verification = verify_execution(
            executed["result"],
            plan=executed["plan"],
            user_question=UserQuestion(dataset_id="ds_phase8", question="哪个城市总销售额最高？"),
        )

        self.assertTrue(executed["result"].success, executed["result"].errors)
        self.assertEqual(["orders", "customers"], executed["logic"].source_tables)
        self.assertTrue(executed["logic"].join_plan["trusted"])
        self.assertEqual([{"city": "北京", "sales": 170}], executed["result"].value)
        self.assertTrue(verification.passed, verification.issues)

    def test_untrusted_join_key_does_not_verify_as_success(self) -> None:
        tables = {
            "orders": pd.DataFrame({"customer_id": ["C1", "C2"], "sales": [100, 120]}),
            "customers": pd.DataFrame({"customer_id": ["X1", "X2"], "city": ["北京", "上海"]}),
        }
        executed = _execute("哪个城市总销售额最高？", tables)
        verification = verify_execution(
            executed["result"],
            plan=executed["plan"],
            user_question=UserQuestion(dataset_id="ds_phase8", question="哪个城市总销售额最高？"),
        )

        self.assertFalse(executed["result"].success)
        self.assertFalse(executed["logic"].join_plan["trusted"])
        self.assertFalse(verification.passed)
        self.assertEqual("clarify_join_key", verification.correction_action["action"])

    def test_verifier_rejects_multi_entity_question_collapsed_to_single_filter(self) -> None:
        table = pd.DataFrame({"门店": ["A店"], "产品": ["苹果"], "sales": [150]})
        logic = parse_generic_table_question("A店和B店哪个门店总销售额最高？", {"a": table}, "")
        plan = build_analysis_plan(logic)
        result = execute_plan(plan, {"tables": {"a": table}, "primary_table": "a"})
        verification = verify_execution(
            result,
            plan=plan,
            user_question=UserQuestion(dataset_id="ds_phase8", question="A店和B店哪个门店总销售额最高？"),
        )

        self.assertTrue(result.success, result.errors)
        self.assertFalse(verification.passed)
        self.assertEqual("repair_filters", verification.correction_action["action"])

    def test_verifier_rejects_chart_request_returning_scalar_row_count(self) -> None:
        table = pd.DataFrame({"city": ["上海", "北京", "上海", "北京"], "sales": [100, 120, 140, 160]})
        logic = make_logic_form(
            task_type="aggregation",
            operation="row_count",
            parameters={"table": "sales"},
            output_format={"answer_type": "number"},
        )
        plan = build_analysis_plan(logic)
        result = execute_plan(plan, {"tables": {"sales": table}, "primary_table": "sales"})
        verification = verify_execution(
            result,
            plan=plan,
            user_question=UserQuestion(dataset_id="ds_phase8", question="按城市展示销售额，生成柱状图。"),
        )

        self.assertTrue(result.success, result.errors)
        self.assertEqual(4, result.value)
        self.assertFalse(verification.passed)
        self.assertEqual("replace_operation", verification.correction_action["action"])

    def test_same_schema_union_product_ranking_does_not_fail_verification(self) -> None:
        tables = {
            "qa_store_a": pd.DataFrame({"store": ["A店", "A店"], "product": ["苹果", "香蕉"], "sales": [100, 70]}),
            "qa_store_b": pd.DataFrame({"store": ["B店", "B店"], "product": ["苹果", "香蕉"], "sales": [80, 90]}),
        }
        tables["qa_store_a"].attrs["source_file"] = "qa_store_a.csv"
        tables["qa_store_b"].attrs["source_file"] = "qa_store_b.csv"
        executed = _execute("A店和B店合起来哪个产品销售额最高？", tables)
        verification = verify_execution(
            executed["result"],
            plan=executed["plan"],
            user_question=UserQuestion(dataset_id="ds_phase8", question="A店和B店合起来哪个产品销售额最高？"),
        )

        self.assertTrue(executed["result"].success, executed["result"].errors)
        self.assertEqual([{"product": "苹果", "sales": 180}], executed["result"].value)
        self.assertEqual(["qa_store_a", "qa_store_b"], executed["logic"].source_tables)
        self.assertTrue(verification.passed, verification.issues)

    def test_verifier_allows_multi_entity_filter_when_scope_keeps_all_named_entities(self) -> None:
        tables = {
            "qa_store_a": pd.DataFrame({"store": ["A店", "A店"], "product": ["苹果", "香蕉"], "sales": [100, 70]}),
            "qa_store_b": pd.DataFrame({"store": ["B店", "B店"], "product": ["苹果", "香蕉"], "sales": [80, 90]}),
        }
        tables["qa_store_a"].attrs["source_file"] = "qa_store_a.csv"
        tables["qa_store_b"].attrs["source_file"] = "qa_store_b.csv"
        logic = parse_generic_table_question("A店和B店合起来哪个产品销售额最高？", tables, "")
        logic.filters = {"store": ["A店", "B店"]}
        plan = build_analysis_plan(logic)
        result = execute_plan(plan, {"tables": tables, "primary_table": "qa_store_a"})
        verification = verify_execution(
            result,
            plan=plan,
            user_question=UserQuestion(dataset_id="ds_phase8", question="A店和B店合起来哪个产品销售额最高？"),
        )

        self.assertTrue(result.success, result.errors)
        self.assertEqual([{"product": "苹果", "sales": 180}], result.value)
        self.assertTrue(verification.passed, verification.issues)

    def test_monthly_trend_groups_by_month_not_city(self) -> None:
        tables = {"sales": pd.DataFrame({"month": ["2026-01", "2026-01", "2026-02"], "city": ["上海", "北京", "广州"], "sales": [100, 250, 180]})}
        executed = _execute("按月份展示销售额趋势，生成折线图。", tables)
        verification = verify_execution(
            executed["result"],
            plan=executed["plan"],
            user_question=UserQuestion(dataset_id="ds_phase8", question="按月份展示销售额趋势，生成折线图。"),
        )
        chart = build_chart_spec(plan=executed["plan"], execution_result=executed["result"], verification_passed=verification.passed)

        self.assertTrue(executed["result"].success, executed["result"].errors)
        self.assertEqual("aggregation", executed["logic"].operation)
        self.assertEqual("month", executed["logic"].parameters["dimension"])
        self.assertEqual({"2026-01": 350, "2026-02": 180}, {row["month"]: row["sales"] for row in executed["result"].value})
        self.assertTrue(verification.passed, verification.issues)
        self.assertEqual("line", chart.chart_type)
        self.assertEqual("month", chart.x)

    def test_monthly_trend_binds_numeric_stat_month(self) -> None:
        tables = {"sales": pd.DataFrame({"stat_month": [202601, 202601, 202602], "city": ["上海", "北京", "广州"], "sales": [100, 250, 180]})}
        executed = _execute("按月度展示销售额趋势，生成折线图。", tables)
        verification = verify_execution(
            executed["result"],
            plan=executed["plan"],
            user_question=UserQuestion(dataset_id="ds_phase8", question="按月度展示销售额趋势，生成折线图。"),
        )

        self.assertTrue(executed["result"].success, executed["result"].errors)
        self.assertEqual("aggregation", executed["logic"].operation)
        self.assertEqual("stat_month", executed["logic"].parameters["dimension"])
        self.assertEqual({202601: 350, 202602: 180}, {row["stat_month"]: row["sales"] for row in executed["result"].value})
        self.assertTrue(verification.passed, verification.issues)

    def test_retail_sales_trend_uses_fact_table_without_untrusted_join(self) -> None:
        tables = _retail_sales_tables()
        executed = _execute("天然水销售金额随时间的趋势是怎样的，生成曲线图", tables)
        verification = verify_execution(
            executed["result"],
            plan=executed["plan"],
            user_question=UserQuestion(dataset_id="ds_phase8", question="天然水销售金额随时间的趋势是怎样的，生成曲线图"),
        )

        self.assertTrue(executed["result"].success, executed["result"].errors)
        self.assertEqual("aggregation", executed["logic"].operation)
        self.assertEqual("v_trd_dist_ord_dtl", executed["logic"].parameters["table"])
        self.assertEqual("sign_amt", executed["logic"].parameters["metric"])
        self.assertEqual("sign_time", executed["logic"].parameters["dimension"])
        self.assertEqual({"ctg_name": "天然水"}, executed["logic"].filters)
        self.assertEqual({}, executed["logic"].join_plan)
        self.assertEqual(
            [
                {"sign_time": "2026-05-01", "sign_amt": 100.0},
                {"sign_time": "2026-06-01", "sign_amt": 80.0},
            ],
            executed["result"].value,
        )
        self.assertTrue(verification.passed, verification.issues)

    def test_retail_sales_may_amount_keeps_month_filter_executable(self) -> None:
        executed = _execute("天然水五月的销售金额", _retail_sales_tables())

        self.assertTrue(executed["result"].success, executed["result"].errors)
        self.assertEqual("aggregation", executed["logic"].operation)
        self.assertEqual("v_trd_dist_ord_dtl", executed["logic"].parameters["table"])
        self.assertEqual("sign_amt", executed["logic"].parameters["metric"])
        self.assertEqual({"ctg_name": "天然水", "sign_time": {"month": 5}}, executed["logic"].filters)
        self.assertEqual({}, executed["logic"].join_plan)
        self.assertEqual(100.0, executed["result"].value)

    def test_retail_sales_composition_uses_amount_metric_and_category_filter(self) -> None:
        executed = _execute("看一下天然水的销售组成", _retail_sales_tables())

        self.assertTrue(executed["result"].success, executed["result"].errors)
        self.assertEqual("aggregation", executed["logic"].operation)
        self.assertEqual("v_trd_dist_ord_dtl", executed["logic"].parameters["table"])
        self.assertEqual("sign_amt", executed["logic"].parameters["metric"])
        self.assertEqual("capacity", executed["logic"].parameters["dimension"])
        self.assertEqual({"ctg_name": "天然水"}, executed["logic"].filters)
        self.assertEqual([{"capacity": "550mL", "sign_amt": 180.0}], executed["result"].value)

    def test_natural_dimension_aliases_bind_to_semantic_fields(self) -> None:
        source_case = _execute("哪个来源销售额最高？", {"sales": pd.DataFrame({"city": ["北京", "上海"], "source": ["线上", "线下"], "sales": [80, 120]})})
        category_case = _execute("哪个品类销售额最高？", {"sales": pd.DataFrame({"city": ["北京", "上海"], "product_line": ["饮料", "食品"], "sales": [80, 120]})})
        month_case = _execute("按月度展示销售额趋势。", {"sales": pd.DataFrame({"city": ["北京", "上海"], "period": ["2026-01", "2026-02"], "sales": [80, 120]})})

        self.assertEqual("source", source_case["logic"].parameters["dimension"])
        self.assertEqual([{"source": "线下", "sales": 120}], source_case["result"].value)
        self.assertEqual("product_line", category_case["logic"].parameters["dimension"])
        self.assertEqual([{"product_line": "食品", "sales": 120}], category_case["result"].value)
        self.assertEqual("period", month_case["logic"].parameters["dimension"])
        self.assertEqual({"2026-01": 80, "2026-02": 120}, {row["period"]: row["sales"] for row in month_case["result"].value})

    def test_missing_channel_dimension_is_blocked_instead_of_city_fallback(self) -> None:
        tables = {"sales": pd.DataFrame({"city": ["北京", "上海"], "sales": [280, 100]})}
        executed = _execute("哪个渠道销售额最高？", tables)
        verification = verify_execution(
            executed["result"],
            plan=executed["plan"],
            user_question=UserQuestion(dataset_id="ds_phase8", question="哪个渠道销售额最高？"),
        )

        self.assertNotEqual("city", executed["logic"].parameters.get("dimension"))
        self.assertFalse(verification.passed)
        self.assertEqual("repair_dimension_binding", verification.correction_action["action"])
        self.assertTrue(verification.correction_action["missing_dimension"])

    def test_verifier_rejects_llm_city_entity_grain_for_channel_question(self) -> None:
        tables = {"sales": pd.DataFrame({"city": ["北京", "上海"], "sales": [280, 100]})}
        logic = parse_generic_table_question("哪个渠道销售额最高？", tables, "")
        logic.parameters.pop("dimension", None)
        logic.parameters["strict_missing_dimension_guard"] = False
        logic.entity_grain = {"entity_field": "city", "grain_role": "dimension"}
        plan = build_analysis_plan(logic)
        result = execute_plan(plan, {"tables": tables, "primary_table": "sales"})
        verification = verify_execution(
            result,
            plan=plan,
            user_question=UserQuestion(dataset_id="ds_phase8", question="哪个渠道销售额最高？"),
        )

        self.assertFalse(verification.passed)
        self.assertEqual("repair_dimension_binding", verification.correction_action["action"])
        self.assertEqual("city", verification.correction_action["actual_dimension"])

    def test_category_dimension_join_uses_products_table(self) -> None:
        executed = _execute("哪个品类总销售额最高？", _orders_products_customers())
        verification = verify_execution(
            executed["result"],
            plan=executed["plan"],
            user_question=UserQuestion(dataset_id="ds_phase8", question="哪个品类总销售额最高？"),
        )

        self.assertTrue(executed["result"].success, executed["result"].errors)
        self.assertEqual("category", executed["logic"].parameters["dimension"])
        self.assertEqual(["orders", "products"], executed["logic"].source_tables)
        self.assertTrue(executed["logic"].join_plan["trusted"])
        self.assertEqual([{"category": "水果", "sales": 180}], executed["result"].value)
        self.assertTrue(verification.passed, verification.issues)

    def test_category_dimension_join_with_city_filter_uses_two_dimension_tables(self) -> None:
        executed = _execute("北京哪个品类销售额最高？", _orders_products_customers())
        verification = verify_execution(
            executed["result"],
            plan=executed["plan"],
            user_question=UserQuestion(dataset_id="ds_phase8", question="北京哪个品类销售额最高？"),
        )

        self.assertTrue(executed["result"].success, executed["result"].errors)
        self.assertEqual("filtered_metric_ranking", executed["logic"].operation)
        self.assertEqual("category", executed["logic"].parameters["dimension"])
        self.assertEqual({"city": "北京"}, executed["logic"].filters)
        self.assertEqual({"orders", "products", "customers"}, set(executed["logic"].source_tables))
        self.assertEqual(2, len(executed["logic"].join_plan["steps"]))
        self.assertEqual([{"category": "零食", "sales": 120}], executed["result"].value)
        self.assertTrue(verification.passed, verification.issues)


def _orders_and_customers() -> dict[str, pd.DataFrame]:
    return {
        "订单表": pd.DataFrame({"客户ID": ["C1", "C2", "C1"], "订单金额": [100, 200, 50]}),
        "客户表": pd.DataFrame({"客户ID": ["C1", "C2"], "城市": ["上海", "北京"]}),
    }


def _orders_products_customers() -> dict[str, pd.DataFrame]:
    return {
        "orders": pd.DataFrame(
            {
                "order_id": ["O1", "O2", "O3"],
                "customer_id": ["C1", "C2", "C1"],
                "product_id": ["P1", "P2", "P3"],
                "sales": [100, 80, 120],
            }
        ),
        "products": pd.DataFrame({"product_id": ["P1", "P2", "P3"], "category": ["水果", "水果", "零食"]}),
        "customers": pd.DataFrame({"customer_id": ["C1", "C2"], "city": ["北京", "上海"]}),
    }


def _retail_sales_tables() -> dict[str, pd.DataFrame]:
    return {
        "终端客户月度维表": pd.DataFrame(
            {
                "统计日期": ["2026-05-01"],
                "所属销售客户SAP编码": [123456],
                "终端客户": ["便利店A"],
            }
        ),
        "v_trd_dist_ord_dtl": pd.DataFrame(
            {
                "ctg_name": ["天然水", "茶π", "天然水"],
                "sign_amt": [100.0, 50.0, 80.0],
                "sign_sales_amt_550_6d1_share": [0.2, 0.1, 0.3],
                "sign_time": ["2026-05-01", "2026-05-02", "2026-06-01"],
                "create_time": ["2026-04-30", "2026-05-01", "2026-05-31"],
                "capacity": ["550mL", "500mL", "550mL"],
                "cmdt_name": ["农夫山泉-天然水", "茶π", "农夫山泉-天然水"],
            }
        ),
    }


def _execute(question: str, tables: dict[str, pd.DataFrame]) -> dict[str, object]:
    logic = parse_generic_table_question(question, tables, "")
    plan = build_analysis_plan(logic)
    result = execute_plan(plan, {"tables": tables, "primary_table": next(iter(tables))})
    return {"logic": logic, "plan": plan, "result": result}


if __name__ == "__main__":
    unittest.main()
