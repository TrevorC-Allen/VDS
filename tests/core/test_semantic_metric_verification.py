"""Semantic metric tests for business-definition-driven analysis plans."""

from __future__ import annotations

import unittest

import pandas as pd

from data_agent_core.contracts.analysis_contracts import AnalysisPlan, LogicForm, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.executors import pandas_executor, sql_executor
from data_agent_core.verifier.result_comparator import compare_results
from data_agent_core.verifier.rule_checker import verify_execution


class SemanticMetricVerificationTest(unittest.TestCase):
    def test_fraud_ranking_uses_volume_rate_not_raw_count(self) -> None:
        payments = pd.DataFrame(
            [
                {"ip_country": "AA", "eur_amount": 100.0, "has_fraudulent_dispute": True},
                {"ip_country": "AA", "eur_amount": 900.0, "has_fraudulent_dispute": False},
                {"ip_country": "ZZ", "eur_amount": 40.0, "has_fraudulent_dispute": True},
                {"ip_country": "ZZ", "eur_amount": 60.0, "has_fraudulent_dispute": False},
            ]
        )
        plan = AnalysisPlan(
            plan_id="semantic_fraud_rate_plan",
            logic_form=LogicForm(
                task_type="ranking",
                operation="rank_by_metric",
                metric="fraud_volume_rate",
                metric_definition={
                    "name": "fraud_volume_rate",
                    "description": "Fraudulent volume divided by total volume.",
                },
                numerator={"column": "eur_amount", "filter": {"has_fraudulent_dispute": True}, "aggregation": "sum"},
                denominator={"column": "eur_amount", "aggregation": "sum"},
                group_by="ip_country",
                objective="maximum",
                options={"A": "AA", "B": "ZZ"},
                parameters={"table": "payments", "group_by": "ip_country", "options": {"A": "AA", "B": "ZZ"}},
            ),
        )

        pandas_result = pandas_executor.execute_plan(plan, {"payments": payments})
        sql_result = sql_executor.execute_plan(plan, {"payments": payments})
        comparison = compare_results(pandas_result, sql_result)

        self.assertTrue(pandas_result.success)
        self.assertTrue(sql_result.success)
        self.assertTrue(comparison.consistent)
        self.assertEqual(pandas_result.value["answer"], "B. ZZ")
        self.assertEqual(pandas_result.value["selected"], "ZZ")
        self.assertEqual(pandas_result.value["metric"], "fraud_volume_rate")

    def test_result_comparator_allows_float_representation_noise_in_ranked_rows(self) -> None:
        pandas_result = ExecutionResult(
            backend="pandas",
            success=True,
            value=[{"城市": "郑州", "毛利": 600301.9199999999}],
        )
        sql_result = ExecutionResult(
            backend="sqlite",
            success=True,
            value=[{"城市": "郑州", "毛利": 600301.92}],
        )

        comparison = compare_results(pandas_result, sql_result)

        self.assertTrue(comparison.consistent, comparison.issues)

    def test_verifier_requests_correction_when_fraud_ranking_uses_count(self) -> None:
        plan = AnalysisPlan(
            plan_id="raw_count_plan",
            logic_form=LogicForm(
                task_type="ranking",
                operation="top_count",
                metric="transaction_count",
                group_by="ip_country",
                parameters={"table": "payments", "group_by": "ip_country", "options": {"A": "AA", "B": "ZZ"}},
            ),
        )
        primary = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["answer"],
            rows=[{"answer": "A. AA"}],
            value="A. AA",
        )

        verification = verify_execution(
            primary,
            plan=plan,
            user_question=UserQuestion(
                dataset_id="synthetic_payments",
                question="What is the top country for fraud? A. AA, B. ZZ",
            ),
        )

        self.assertFalse(verification.passed)
        self.assertFalse(verification.semantic_passed)
        self.assertEqual(verification.correction_action["action"], "replace_logic_form")
        self.assertEqual(verification.correction_action["to_operation"], "rank_by_metric")
        self.assertEqual(verification.correction_action["metric"], "fraud_volume_rate")

    def test_analysis_plan_completes_generalization_contract(self) -> None:
        plan = build_analysis_plan(
            LogicForm(
                task_type="aggregation",
                operation="metric_per_distinct_entity",
                metric="eur_amount",
                parameters={
                    "table": "payments",
                    "metric": "eur_amount",
                    "entity_field": "email_address",
                    "aggregation": "sum",
                },
                output_format={"answer_type": "number"},
            )
        )

        logic = plan.logic_form
        self.assertEqual("unique_entity", logic.denominator["role"])
        self.assertEqual("email_address", logic.denominator["field"])
        self.assertEqual("entity", logic.entity_grain["role"])
        self.assertEqual("all_time", logic.time_window["type"])
        self.assertEqual("number", logic.output_contract["answer_type"])
        contract = plan.constraints["generalization_contract"]
        for field_name in ("metric_definition", "numerator", "denominator", "entity_grain", "time_window", "candidate_set", "filters", "output_contract"):
            self.assertTrue(contract[field_name], field_name)

    def test_count_per_unique_entity_satisfies_count_metric_question(self) -> None:
        payments = pd.DataFrame(
            [
                {"email_address": "a@example.com", "eur_amount": 10.0},
                {"email_address": "a@example.com", "eur_amount": 20.0},
                {"email_address": "b@example.com", "eur_amount": 30.0},
            ]
        )
        plan = build_analysis_plan(
            LogicForm(
                task_type="aggregation",
                operation="metric_per_distinct_entity",
                metric="__row_count__",
                metric_definition={"name": "transactions_per_unique_email", "aggregation": "mean"},
                parameters={
                    "table": "payments",
                    "metric": "__row_count__",
                    "entity_field": "email_address",
                    "aggregation": "count",
                },
                output_format={"answer_type": "number"},
            )
        )
        primary = pandas_executor.execute_plan(plan, {"payments": payments})
        comparison = compare_results(primary, sql_executor.execute_plan(plan, {"payments": payments}))

        verification = verify_execution(
            primary,
            comparison=comparison,
            plan=plan,
            user_question=UserQuestion(
                dataset_id="synthetic_payments",
                question="What is the average number of transactions per unique shopper based on email addresses?",
            ),
        )

        self.assertTrue(primary.success, primary.errors)
        self.assertTrue(comparison.consistent, comparison.issues)
        self.assertTrue(verification.passed, verification.semantic_verification_notes)
        self.assertAlmostEqual(1.5, float(primary.value))

    def test_analysis_plan_normalizes_llm_candidate_set_without_source(self) -> None:
        plan = build_analysis_plan(
            LogicForm(
                task_type="ranking",
                operation="vds_period_rank_change",
                metric="PSD_row",
                candidate_set={"option": "all stores present in both weeks"},
                parameters={
                    "table": "sales",
                    "metric": "PSD_row",
                    "entity": "门店名称",
                    "current_period": "本周",
                    "previous_period": "上周",
                    "direction": "decline",
                    "limit": 10,
                },
                output_format={"answer_type": "table"},
            )
        )

        self.assertEqual("data", plan.logic_form.candidate_set["source"])
        self.assertEqual("门店名称", plan.logic_form.candidate_set["field"])

    def test_verifier_rejects_missing_unique_denominator_for_per_unique_question(self) -> None:
        plan = build_analysis_plan(
            LogicForm(
                task_type="aggregation",
                operation="aggregation",
                metric="eur_amount",
                parameters={"table": "payments", "metric": "eur_amount", "aggregation": "mean"},
                output_format={"answer_type": "number"},
            )
        )
        primary = ExecutionResult(backend="pandas", success=True, value=25.0)

        verification = verify_execution(
            primary,
            plan=plan,
            user_question=UserQuestion(
                dataset_id="synthetic_payments",
                question="What is the average transaction amount per unique email?",
            ),
        )

        self.assertFalse(verification.passed)
        self.assertFalse(verification.semantic_passed)
        self.assertEqual("repair_denominator", verification.correction_action["action"])

    def test_verifier_allows_distinct_count_for_unique_shopper_question(self) -> None:
        plan = build_analysis_plan(
            LogicForm(
                task_type="schema_query",
                operation="distinct_count",
                parameters={"table": "payments", "field": "email_address"},
                output_format={"answer_type": "number"},
            )
        )
        primary = ExecutionResult(backend="pandas", success=True, value=46284)

        verification = verify_execution(
            primary,
            plan=plan,
            user_question=UserQuestion(
                dataset_id="synthetic_payments",
                question="How many unique shoppers are there in the payments dataset based on email addresses?",
            ),
        )

        self.assertTrue(verification.passed, verification.semantic_verification_notes)
        self.assertTrue(verification.semantic_passed)

    def test_verifier_rejects_missing_filter_even_when_execution_succeeds(self) -> None:
        plan = build_analysis_plan(
            LogicForm(
                task_type="ranking",
                operation="ranking",
                metric="销售额",
                parameters={"table": "sales", "metric": "销售额", "dimension": "城市", "aggregation": "sum"},
                output_format={"answer_type": "table"},
            )
        )
        primary = ExecutionResult(backend="pandas", success=True, value=[{"城市": "上海", "销售额": 500.0}])

        verification = verify_execution(
            primary,
            plan=plan,
            user_question=UserQuestion(
                dataset_id="synthetic_sales",
                question="区域为华北时，哪个城市销售额最高？",
            ),
        )

        self.assertFalse(verification.passed)
        self.assertFalse(verification.semantic_passed)
        self.assertEqual("repair_filters", verification.correction_action["action"])

    def test_verifier_rejects_count_question_planned_as_sum(self) -> None:
        plan = build_analysis_plan(
            LogicForm(
                task_type="aggregation",
                operation="aggregation",
                metric="销售额",
                parameters={"table": "sales", "metric": "销售额", "dimension": "区域", "aggregation": "sum"},
                output_format={"answer_type": "table"},
            )
        )
        primary = ExecutionResult(backend="pandas", success=True, value=[{"区域": "华北", "销售额": 300.0}])

        verification = verify_execution(
            primary,
            plan=plan,
            user_question=UserQuestion(dataset_id="synthetic_sales", question="按区域统计记录数"),
        )

        self.assertFalse(verification.passed)
        self.assertFalse(verification.semantic_passed)
        self.assertEqual("repair_metric_definition", verification.correction_action["action"])
        self.assertEqual("count", verification.correction_action["required_aggregation"])

    def test_verifier_allows_vds_growth_count_share_metric_comparison(self) -> None:
        plan = build_analysis_plan(
            LogicForm(
                task_type="aggregation",
                operation="vds_period_growth_count_share",
                metric="PSD_row",
                parameters={
                    "table": "sales",
                    "metric": "PSD_row",
                    "entity": "门店名称",
                    "current_period": "本周",
                    "previous_period": "上周",
                },
                output_format={"answer_type": "text"},
            )
        )
        primary = ExecutionResult(
            backend="pandas",
            success=True,
            value={"answer": "2, 66.67%", "count": 2, "share": 66.6667, "total": 3},
        )

        verification = verify_execution(
            primary,
            plan=plan,
            user_question=UserQuestion(dataset_id="synthetic_sales", question="本周PSD较上周增长的门店数量和占比？"),
        )

        self.assertTrue(verification.passed, verification.semantic_verification_notes)
        self.assertTrue(verification.semantic_passed)

    def test_verifier_allows_schema_backed_retail_top_count(self) -> None:
        plan = build_analysis_plan(
            LogicForm(
                task_type="ranking",
                operation="retail_display_item_top",
                parameters={"ym": 202605},
                output_format={"answer_type": "text"},
            )
        )
        primary = ExecutionResult(backend="pandas", success=True, value="水堆")

        verification = verify_execution(
            primary,
            plan=plan,
            user_question=UserQuestion(dataset_id="synthetic_retail", question="2026年5月陈列计划中出现次数最多的陈列项是什么？"),
        )

        self.assertTrue(verification.passed, verification.semantic_verification_notes)
        self.assertTrue(verification.semantic_passed)
        self.assertEqual("count", plan.logic_form.metric_definition["aggregation"])

    def test_verifier_allows_retail_business_quantity_metric(self) -> None:
        plan = build_analysis_plan(
            LogicForm(
                task_type="aggregation",
                operation="retail_route_contract_product_quantity",
                parameters={"person": "张三", "date": "2026-05-19", "ym": 202605, "product": "天然水"},
                output_format={"answer_type": "number"},
            )
        )
        primary = ExecutionResult(backend="pandas", success=True, value=12.789)

        verification = verify_execution(
            primary,
            plan=plan,
            user_question=UserQuestion(
                dataset_id="synthetic_retail",
                question="张三在2026-05-19计划拜访线路上的合约店，2026年5月天然水分销数量是多少？",
            ),
        )

        self.assertTrue(verification.passed, verification.semantic_verification_notes)
        self.assertTrue(verification.semantic_passed)

    def test_verifier_allows_retail_formula_with_structured_filter_context(self) -> None:
        plan = build_analysis_plan(
            LogicForm(
                task_type="ratio",
                operation="retail_display_fee_rate",
                parameters={"person": "张三", "ym": 202605, "role": "employee"},
                output_format={"answer_type": "percentage"},
            )
        )
        primary = ExecutionResult(backend="pandas", success=True, value=102.06)

        verification = verify_execution(
            primary,
            plan=plan,
            user_question=UserQuestion(
                dataset_id="synthetic_retail",
                question="张三在2026年5月的陈列费率是多少？陈列费率=陈列确认金额/分销金额。",
            ),
        )

        self.assertTrue(verification.passed, verification.semantic_verification_notes)
        self.assertTrue(verification.semantic_passed)

    def test_verifier_rejects_metric_share_with_count_denominator(self) -> None:
        plan = build_analysis_plan(
            LogicForm(
                task_type="aggregation",
                operation="top_k_share",
                metric="销售额",
                group_by="城市",
                parameters={"table": "sales", "metric": "销售额", "dimension": "城市", "aggregation": "sum", "limit": 2},
                denominator={"aggregation": "count", "scope": "filtered_total"},
                output_format={"answer_type": "percentage"},
            )
        )
        primary = ExecutionResult(backend="pandas", success=True, value=60.0)

        verification = verify_execution(
            primary,
            plan=plan,
            user_question=UserQuestion(dataset_id="synthetic_sales", question="前2个城市销售额占比是多少？"),
        )

        self.assertFalse(verification.passed)
        self.assertFalse(verification.semantic_passed)
        self.assertEqual("repair_denominator", verification.correction_action["action"])
        self.assertEqual("销售额", verification.correction_action["field"])

    def test_verifier_rejects_fee_selection_outside_candidate_table(self) -> None:
        plan = build_analysis_plan(
            LogicForm(
                task_type="fee_rule",
                operation="best_fraud_aci_choice",
                filters={"merchant": "SyntheticMerchant", "year": 2023, "month": 1},
                output_format={"answer_type": "scheme_fee"},
            )
        )
        primary = ExecutionResult(
            backend="pandas",
            success=True,
            value={
                "selected": "Z",
                "fee": 1.0,
                "candidate_table": [{"aci": "D", "fee": 2.0}, {"aci": "E", "fee": 1.0}],
            },
        )

        verification = verify_execution(
            primary,
            plan=plan,
            user_question=UserQuestion(
                dataset_id="synthetic_fee_rules",
                question="For fraudulent transactions, which ACI leads to the lowest possible fees?",
            ),
        )

        self.assertFalse(verification.passed)
        self.assertFalse(verification.semantic_passed)
        self.assertEqual("reselect_from_candidate_table", verification.correction_action["action"])

    def test_verifier_rejects_fee_candidate_table_without_numeric_fee(self) -> None:
        plan = build_analysis_plan(
            LogicForm(
                task_type="fee_rule",
                operation="aci_fee_extreme",
                parameters={"transaction_value": 10.0},
                output_format={"answer_type": "aci"},
            )
        )
        primary = ExecutionResult(
            backend="pandas",
            success=True,
            value={"selected": "A", "candidate_table": [{"aci": "A", "fee": None}]},
        )

        verification = verify_execution(
            primary,
            plan=plan,
            user_question=UserQuestion(
                dataset_id="synthetic_fee_rules",
                question="Which ACI is the most expensive for a transaction of 10 euros?",
            ),
        )

        self.assertFalse(verification.passed)
        self.assertFalse(verification.semantic_passed)
        self.assertEqual("repair_fee_candidate_table", verification.correction_action["action"])


if __name__ == "__main__":
    unittest.main()
