"""Regression coverage for real uploaded sales-table semantics."""

from __future__ import annotations

import unittest

import pandas as pd

from data_agent_core.contracts.analysis_contracts import UserQuestion
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.core.conversation_actions import build_analysis_context, plan_followup_actions
from data_agent_core.core.intent_parser import parse_generic_table_question
from data_agent_core.executors.pandas_executor import execute_plan
from data_agent_core.output.response_builder import build_response
from data_agent_core.verifier.rule_checker import verify_execution


FACT_TABLE = "v_trd_dist_ord_dtl"
METADATA_TABLE = "数据表结构&表说明__数据表说明"


class RealSalesMetadataFollowupRegressionTest(unittest.TestCase):
    def test_sku_volume_ranking_excludes_metadata_table_from_business_join(self) -> None:
        logic = parse_generic_table_question("什么sku销量最高", _sales_tables(with_quantity=True), "")

        self.assertEqual("ranking", logic.operation)
        self.assertEqual("sku_factor", logic.parameters.get("dimension"))
        self.assertEqual("qty", logic.parameters.get("metric"))
        self.assertEqual(FACT_TABLE, logic.parameters.get("table"))
        self.assertNotIn(METADATA_TABLE, logic.source_tables)
        self.assertNotIn(METADATA_TABLE, logic.parameters.get("source_tables") or [])
        self.assertFalse(logic.join_plan)
        self.assertFalse(logic.parameters.get("join_plan"))

        result = execute_plan(build_analysis_plan(logic, question="什么sku销量最高"), {"tables": _sales_tables(with_quantity=True)})

        self.assertTrue(result.success, result.errors)
        self.assertEqual([{"sku_factor": "SKU-A", "qty": 22}], result.value)

    def test_city_order_amount_top1_keeps_dimension_and_metric_in_result_artifact(self) -> None:
        response = _execute_response("哪个城市订单金额最大", _sales_tables(with_quantity=True))

        self.assertTrue(response["success"], response["errors"])
        self.assertEqual(["city", "sign_amt"], response["result"]["columns"])
        self.assertEqual("杭州市", response["result"]["rows"][0]["city"])
        self.assertAlmostEqual(136330.74, float(response["result"]["rows"][0]["sign_amt"]), places=2)
        self.assertNotEqual({"answer": 136330.74}, response["result"].get("value"))

        artifact = response["debug"].get("result_artifacts") or {}
        self.assertEqual("city", artifact.get("dimension"))
        self.assertEqual("sign_amt", artifact.get("metric"))
        self.assertEqual("杭州市", artifact.get("top_objects", [{}])[0].get("value"))
        self.assertAlmostEqual(136330.74, float(artifact.get("top_objects", [{}])[0].get("metric_value")), places=2)
        self.assertNotIn(METADATA_TABLE, artifact.get("source_tables") or [])

    def test_generic_adjacent_comparison_followup_inherits_previous_city_metric_and_table(self) -> None:
        first_response = _execute_response("哪个城市订单金额最大", _sales_tables(with_quantity=True))
        context = build_analysis_context(first_response, original_question="哪个城市订单金额最大")

        actions = plan_followup_actions("对比相邻时间段或相关对象的同一指标", context)

        self.assertEqual(1, len(actions))
        action = actions[0]
        contract = action.get("referent_contract") or {}
        inherited = action.get("inherited_parameters") or {}
        params = action.get("parameters") or {}
        self.assertEqual("杭州市", contract.get("referent_values", [None])[0])
        self.assertEqual("city", contract.get("referent_dimension"))
        self.assertEqual("sign_amt", params.get("metric"))
        self.assertEqual(FACT_TABLE, inherited.get("table"))
        self.assertEqual([FACT_TABLE], inherited.get("source_tables"))
        self.assertNotIn(METADATA_TABLE, inherited.get("source_tables") or [])
        self.assertEqual({"city": "杭州市"}, inherited.get("filters"))

    def test_salesperson_growth_ranking_resolves_specific_candidates(self) -> None:
        logic = parse_generic_table_question("看一下这几个销售的表现，按照增长率排名", _sales_tables(with_quantity=True), "")

        self.assertEqual("growth_ranking", logic.operation)
        self.assertEqual("emp_name", logic.parameters.get("dimension"))
        self.assertEqual("sign_amt", logic.parameters.get("metric"))
        self.assertEqual("sign_time", logic.parameters.get("time_column"))
        self.assertEqual(FACT_TABLE, logic.parameters.get("table"))
        self.assertNotIn(METADATA_TABLE, logic.parameters.get("source_tables") or [])

        result = execute_plan(build_analysis_plan(logic, question="看一下这几个销售的表现，按照增长率排名"), {"tables": _sales_tables(with_quantity=True)})

        self.assertTrue(result.success, result.errors)
        self.assertEqual("张三", result.rows[0]["emp_name"])
        self.assertIn("sign_amt_growth_rate", result.rows[0])


def _execute_response(question: str, tables: dict[str, pd.DataFrame]) -> dict[str, object]:
    logic = parse_generic_table_question(question, tables, "")
    plan = build_analysis_plan(logic, question=question)
    result = execute_plan(plan, {"tables": tables, "primary_table": FACT_TABLE})
    verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds_sales", question=question))
    return build_response(
        run_id="run_sales_regression",
        user_question=UserQuestion(dataset_id="ds_sales", question=question),
        plan=plan,
        execution_result=result,
        verification=verification,
    ).to_dict()


def _sales_tables(*, with_quantity: bool) -> dict[str, pd.DataFrame]:
    fact_rows = [
        {"dist_ord_item_id": "A1", "sku_factor": "SKU-A", "city": "杭州市", "emp_name": "张三", "sign_amt": 50000.25, "sign_time": "2026-01-15", **({"qty": 10} if with_quantity else {})},
        {"dist_ord_item_id": "A2", "sku_factor": "SKU-B", "city": "上海市", "emp_name": "李四", "sign_amt": 60000.00, "sign_time": "2026-01-20", **({"qty": 18} if with_quantity else {})},
        {"dist_ord_item_id": "A3", "sku_factor": "SKU-A", "city": "杭州市", "emp_name": "张三", "sign_amt": 86330.49, "sign_time": "2026-02-15", **({"qty": 12} if with_quantity else {})},
        {"dist_ord_item_id": "A4", "sku_factor": "SKU-B", "city": "上海市", "emp_name": "李四", "sign_amt": 30000.00, "sign_time": "2026-02-20", **({"qty": 4} if with_quantity else {})},
        {"dist_ord_item_id": "A5", "sku_factor": "SKU-C", "city": "北京市", "emp_name": "王五", "sign_amt": 45000.00, "sign_time": "2026-01-18", **({"qty": 6} if with_quantity else {})},
        {"dist_ord_item_id": "A6", "sku_factor": "SKU-C", "city": "北京市", "emp_name": "王五", "sign_amt": 47000.00, "sign_time": "2026-02-18", **({"qty": 5} if with_quantity else {})},
    ]
    metadata_rows = [
        {"table_name": FACT_TABLE, "field_name": "dist_ord_item_id", "field_desc": "分销订单明细行 ID", "dist_ord_item_id": "字段说明"},
        {"table_name": FACT_TABLE, "field_name": "sku_factor", "field_desc": "SKU 因子/商品标识", "dist_ord_item_id": "字段说明"},
        {"table_name": FACT_TABLE, "field_name": "sign_amt", "field_desc": "订单签收金额", "dist_ord_item_id": "字段说明"},
    ]
    return {
        FACT_TABLE: pd.DataFrame(fact_rows),
        METADATA_TABLE: pd.DataFrame(metadata_rows),
    }


if __name__ == "__main__":
    unittest.main()
