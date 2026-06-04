"""Failing coverage for derived-metric follow-up formula inheritance."""

from __future__ import annotations

import unittest

import pandas as pd

from data_agent_core.contracts.analysis_contracts import LogicForm, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.core.conversation_actions import build_analysis_context, plan_followup_actions
from data_agent_core.executors.pandas_executor import execute_plan
from data_agent_core.oracle_results import build_oracle_result
from data_agent_core.output.response_builder import build_response
from data_agent_core.output.text_answer_framework import apply_text_answer_framework
from data_agent_core.task_contract_builder import apply_referent_contract
from data_agent_core.task_execution_contracts import TaskExecutionContract, verify_task_execution_contract
from data_agent_core.verifier.rule_checker import verify_execution


PROFIT_MARGIN = {
    "name": "profit_margin",
    "numerator": "profit",
    "denominator": "revenue",
    "formula": "profit / revenue",
}

CONVERSION_RATE = {
    "name": "conversion_rate",
    "numerator": "conversions",
    "denominator": "visits",
    "formula": "conversions / visits",
}


class DerivedMetricFollowupFormulaTest(unittest.TestCase):
    def test_first_turn_derived_metric_topn_artifact_records_formula_metadata(self) -> None:
        response = _execute_response(_profit_margin_topn_logic(), _business_frame(), "按城市统计利润率 Top 5 是哪些？")
        rows = response["result"]["rows"]
        artifact = response["debug"].get("result_artifacts") or {}
        context = build_analysis_context(response, original_question="按城市统计利润率 Top 5 是哪些？")
        context_artifact = (context.get("active_result_artifacts") or [{}])[0]

        self.assertIn("profit_margin", rows[0])
        self.assertEqual("profit_margin", artifact.get("metric"))
        self.assertEqual("city", artifact.get("dimension"))
        self.assertEqual([row["city"] for row in rows[:5]], [item["value"] for item in artifact.get("top_objects") or []])
        self.assertEqual(sorted([row["profit_margin"] for row in rows[:5]], reverse=True), [row["profit_margin"] for row in rows[:5]])

        for payload in (artifact, context_artifact):
            with self.subTest(payload=payload.get("artifact_type") or payload.get("task_family")):
                self.assertEqual("profit_margin", payload.get("derived_metric_name"))
                self.assertEqual("profit / revenue", payload.get("metric_formula"))
                self.assertEqual("profit", payload.get("numerator_column"))
                self.assertEqual("revenue", payload.get("denominator_column"))
                self.assertNotEqual("profit", payload.get("metric"))
                self.assertNotEqual("revenue", payload.get("metric"))

    def test_followup_drilldown_action_inherits_top_cities_and_formula_metadata(self) -> None:
        first_response = _execute_response(_profit_margin_topn_logic(), _business_frame(), "按城市统计利润率 Top 5 是哪些？")
        context = build_analysis_context(first_response, original_question="按城市统计利润率 Top 5 是哪些？")

        actions = plan_followup_actions("这些城市里，哪个产品线利润率最高？", context)

        self.assertTrue(actions, "derived_metric_followup_missing: should plan a product_line drilldown action")
        contract = actions[0].get("referent_contract") or {}
        params = contract.get("action_parameters") or {}
        self.assertEqual("drilldown_followup", contract.get("capability_family"))
        self.assertEqual(["北京", "深圳", "上海", "杭州", "广州"], contract.get("referent_values"))
        self.assertEqual("city", contract.get("referent_dimension"))
        self.assertEqual("product_line", params.get("dimension"))
        self.assertEqual("profit_margin", params.get("derived_metric_name"))
        self.assertEqual("profit / revenue", params.get("metric_formula"))
        self.assertEqual("profit", params.get("numerator_column"))
        self.assertEqual("revenue", params.get("denominator_column"))
        self.assertEqual({"city": ["北京", "深圳", "上海", "杭州", "广州"]}, params.get("merged_filters"))

    def test_followup_drilldown_execution_uses_sum_ratio_not_average_or_raw_profit(self) -> None:
        first_response = _execute_response(_profit_margin_topn_logic(), _business_frame(), "按城市统计利润率 Top 5 是哪些？")
        context = build_analysis_context(first_response, original_question="按城市统计利润率 Top 5 是哪些？")
        actions = plan_followup_actions("这些城市里，哪个产品线利润率最高？", context)
        self.assertTrue(actions, "derived_metric_followup_missing: should plan a product_line drilldown action")

        logic = LogicForm(
            task_type="ranking",
            operation="ranking",
            metric="profit_margin",
            group_by="product_line",
            filters={},
            parameters={
                "table": "orders",
                "metric": "profit_margin",
                "dimension": "product_line",
                "limit": 3,
                "sort_order": "desc",
                "derived_metric": dict(PROFIT_MARGIN),
            },
            output_format={"answer_type": "table"},
        )
        apply_referent_contract(logic, actions[0]["referent_contract"])
        plan = build_analysis_plan(logic, question="这些城市里，哪个产品线利润率最高？")
        result = execute_plan(plan, {"tables": {"orders": _business_frame()}, "primary_table": "orders"})

        self.assertEqual({"city": ["北京", "深圳", "上海", "杭州", "广州"]}, logic.filters)
        self.assertEqual("product_line", logic.parameters.get("dimension"))
        self.assertAlmostEqual(0.45, result.rows[0]["profit_margin"])
        self.assertEqual("Analytics", result.rows[0]["product_line"])
        self.assertNotEqual("Cloud", result.rows[0]["product_line"], "wrong_sort_metric: raw profit would rank Cloud first")
        self.assertNotAlmostEqual(0.4667, result.rows[0]["profit_margin"], places=3, msg="wrong_aggregation: avg city ratios would produce 0.4667")

    def test_conversion_rate_trend_followup_keeps_formula_metadata_in_rows_and_artifact(self) -> None:
        logic = LogicForm(
            task_type="aggregation",
            operation="aggregation",
            metric="conversion_rate",
            group_by="channel",
            filters={"channel": ["Paid", "Organic"]},
            parameters={
                "table": "traffic",
                "metric": "conversion_rate",
                "dimension": "channel",
                "series_dimension": "month",
                "derived_metric": dict(CONVERSION_RATE),
            },
            output_format={"answer_type": "table"},
        )
        response = _execute_response(logic, _traffic_frame(), "这些渠道按月份的转化率趋势怎么样？")
        rows = response["result"]["rows"]
        artifact = response["debug"].get("result_artifacts") or {}

        self.assertEqual({"Paid", "Organic"}, {row["channel"] for row in rows})
        self.assertIn("month", rows[0])
        self.assertIn("conversion_rate", rows[0])
        for row in rows:
            self.assertEqual("conversion_rate", row.get("derived_metric_name"))
            self.assertEqual("conversions / visits", row.get("metric_formula"))
            self.assertEqual("conversions", row.get("numerator_column"))
            self.assertEqual("visits", row.get("denominator_column"))
        self.assertEqual("conversion_rate", artifact.get("derived_metric_name"))
        self.assertEqual("conversions / visits", artifact.get("metric_formula"))
        self.assertNotEqual(["month", "conversions"], response["result"]["columns"])
        self.assertNotEqual(["month", "visits"], response["result"]["columns"])

    def test_contract_requires_derived_metric_formula_components_and_safe_division(self) -> None:
        plan = build_analysis_plan(_profit_margin_topn_logic(), question="按城市统计利润率 Top 5 是哪些？")
        contract = plan.task_contract
        rules = contract.verification_rules

        self.assertEqual("profit_margin", getattr(contract, "derived_metric_name", None))
        self.assertEqual("profit / revenue", rules.get("metric_formula"))
        self.assertEqual("profit", rules.get("numerator_column"))
        self.assertEqual("revenue", rules.get("denominator_column"))
        self.assertTrue(rules.get("requires_inherited_formula_on_followup"))
        self.assertTrue(rules.get("requires_denominator_non_zero_safe_division"))

    def test_contract_reports_missing_derived_metric_formula_components(self) -> None:
        contract = TaskExecutionContract(
            contract_id="contract_derived_metric_missing_parts",
            task_family="topn",
            metric="profit_margin",
            dimension="city",
            verification_rules={
                "requires_execution_success": True,
                "requires_derived_metric_formula": True,
                "requires_numerator_column": True,
                "requires_denominator_column": True,
                "requires_denominator_non_zero_safe_division": True,
            },
        )
        report = verify_task_execution_contract(
            contract,
            ExecutionResult(
                backend="unit-test",
                success=True,
                columns=["city", "profit_margin"],
                rows=[{"city": "北京", "profit_margin": 0.6}],
                value=[{"city": "北京", "profit_margin": 0.6}],
            ),
        )

        codes = {item.code for item in report.violations}
        self.assertIn("derived_metric_formula_missing", codes)
        self.assertIn("derived_metric_numerator_missing", codes)
        self.assertIn("derived_metric_denominator_missing", codes)

    def test_oracle_rejects_wrong_derived_metric_aggregation_sort_filter_and_metadata(self) -> None:
        contract = TaskExecutionContract(
            contract_id="contract_derived_metric_drilldown",
            task_family="drilldown_followup",
            metric="profit_margin",
            dimension="product_line",
            requires_previous_artifact=True,
            referent_dimension="city",
            referent_values=["北京", "深圳", "上海", "杭州", "广州"],
            verification_rules={
                "expected_result": {
                    "task_family": "drilldown_followup",
                    "dimension": "product_line",
                    "metric": "profit_margin",
                    "referent_dimension": "city",
                    "referent_values": ["北京", "深圳", "上海", "杭州", "广州"],
                    "merged_filters": {"city": ["北京", "深圳", "上海", "杭州", "广州"]},
                    "derived_metric_name": "profit_margin",
                    "metric_formula": "profit / revenue",
                    "numerator_column": "profit",
                    "denominator_column": "revenue",
                    "rows": [
                        {"product_line": "Analytics", "profit_margin": 0.45},
                        {"product_line": "Support", "profit_margin": 0.375},
                        {"product_line": "Cloud", "profit_margin": 0.3},
                    ],
                }
            },
        )
        cases = {
            "avg_ratio": (
                [{"product_line": "Cloud", "profit_margin": 0.45}, {"product_line": "Analytics", "profit_margin": 0.4}],
                {"filters": {"city": ["北京", "深圳", "上海", "杭州", "广州"]}, "metric_formula": "profit / revenue"},
                "derived_metric_wrong_aggregation",
            ),
            "raw_profit_sort": (
                [{"product_line": "Cloud", "profit": 450}, {"product_line": "Analytics", "profit": 300}],
                {"filters": {"city": ["北京", "深圳", "上海", "杭州", "广州"]}, "metric_formula": "profit / revenue"},
                "derived_metric_wrong_sort_metric",
            ),
            "missing_filter": (
                [{"product_line": "Analytics", "profit_margin": 0.45}],
                {"filters": {}, "metric_formula": "profit / revenue"},
                "derived_metric_filter_missing",
            ),
            "missing_formula": (
                [{"product_line": "Analytics", "profit_margin": 0.45}],
                {"filters": {"city": ["北京", "深圳", "上海", "杭州", "广州"]}},
                "derived_metric_formula_missing",
            ),
        }
        for label, (rows, value, expected_code) in cases.items():
            with self.subTest(label=label):
                result = build_oracle_result(
                    contract,
                    ExecutionResult(backend="unit-test", success=True, columns=list(rows[0]), rows=rows, value=value),
                )
                self.assertTrue(result.oracle_available)
                self.assertFalse(result.passed)
                self.assertIn(expected_code, result.issue_codes)

    def test_response_first_sentence_explains_formula_and_inherited_followup_scope(self) -> None:
        response = apply_text_answer_framework(
            {
                "success": True,
                "answer_type": "table",
                "answer": "已完成排序。",
                "logic_form": {
                    "operation": "ranking",
                    "filters": {"city": ["北京", "上海", "深圳", "杭州", "广州"]},
                    "parameters": {
                        "table": "orders",
                        "metric": "profit_margin",
                        "dimension": "product_line",
                        "referent_dimension": "city",
                        "referent_values": ["北京", "上海", "深圳", "杭州", "广州"],
                        "derived_metric": dict(PROFIT_MARGIN),
                    },
                    "task_contract": {
                        "task_family": "drilldown_followup",
                        "metric": "profit_margin",
                        "dimension": "product_line",
                        "referent_dimension": "city",
                        "referent_values": ["北京", "上海", "深圳", "杭州", "广州"],
                    },
                },
                "result": {
                    "columns": ["product_line", "profit_margin"],
                    "rows": [{"product_line": "Analytics", "profit_margin": 0.5}, {"product_line": "Support", "profit_margin": 0.375}],
                },
            },
            question="这些城市里，哪个产品线利润率最高？",
        )
        answer = response["answer"]
        first_sentence = answer.split("。", 1)[0]

        self.assertIn("Analytics", first_sentence)
        self.assertIn("产品利润率排名", answer)
        self.assertIn("利润率按 profit / revenue 计算", answer)
        self.assertIn("继承同一利润率口径", answer)
        self.assertNotIn("利润最高", answer)


def _profit_margin_topn_logic() -> LogicForm:
    return LogicForm(
        task_type="ranking",
        operation="ranking",
        metric="profit_margin",
        group_by="city",
        filters={},
        parameters={
            "table": "orders",
            "metric": "profit_margin",
            "dimension": "city",
            "limit": 5,
            "sort_order": "desc",
            "available_columns": ["city", "product_line", "month", "profit", "revenue"],
            "derived_metric": dict(PROFIT_MARGIN),
        },
        output_format={"answer_type": "table"},
    )


def _execute_response(logic: LogicForm, frame: pd.DataFrame, question: str) -> dict[str, object]:
    plan = build_analysis_plan(logic, question=question)
    result = execute_plan(plan, {"tables": {str(logic.parameters.get("table") or "orders"): frame}, "primary_table": str(logic.parameters.get("table") or "orders")})
    verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds", question=question))
    return build_response(
        run_id="run_derived_metric_formula",
        user_question=UserQuestion(dataset_id="ds", question=question),
        plan=plan,
        execution_result=result,
        verification=verification,
    ).to_dict()


def _business_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"city": "北京", "product_line": "Analytics", "month": "2026-01", "profit": 60, "revenue": 100},
            {"city": "北京", "product_line": "Cloud", "month": "2026-01", "profit": 30, "revenue": 50},
            {"city": "上海", "product_line": "Analytics", "month": "2026-01", "profit": 80, "revenue": 200},
            {"city": "上海", "product_line": "Support", "month": "2026-01", "profit": 30, "revenue": 100},
            {"city": "深圳", "product_line": "Cloud", "month": "2026-01", "profit": 120, "revenue": 300},
            {"city": "深圳", "product_line": "Support", "month": "2026-01", "profit": 45, "revenue": 100},
            {"city": "杭州", "product_line": "Analytics", "month": "2026-01", "profit": 40, "revenue": 100},
            {"city": "杭州", "product_line": "Cloud", "month": "2026-01", "profit": 60, "revenue": 200},
            {"city": "广州", "product_line": "Cloud", "month": "2026-01", "profit": 70, "revenue": 250},
            {"city": "广州", "product_line": "Support", "month": "2026-01", "profit": 75, "revenue": 200},
            {"city": "苏州", "product_line": "Cloud", "month": "2026-01", "profit": 20, "revenue": 100},
        ]
    )


def _traffic_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"channel": "Paid", "month": "2026-01", "conversions": 20, "visits": 100},
            {"channel": "Paid", "month": "2026-02", "conversions": 30, "visits": 120},
            {"channel": "Organic", "month": "2026-01", "conversions": 15, "visits": 100},
            {"channel": "Organic", "month": "2026-02", "conversions": 18, "visits": 90},
            {"channel": "Referral", "month": "2026-01", "conversions": 8, "visits": 80},
        ]
    )


if __name__ == "__main__":
    unittest.main()
