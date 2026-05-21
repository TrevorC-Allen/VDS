"""Semantic metric tests for business-definition-driven analysis plans."""

from __future__ import annotations

import unittest

import pandas as pd

from data_agent_core.contracts.analysis_contracts import AnalysisPlan, LogicForm, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
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


if __name__ == "__main__":
    unittest.main()
