from __future__ import annotations

import unittest

from data_agent_core.contracts.analysis_contracts import LogicForm, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult, build_actual_execution_trace, prepare_execution_plan_for_backend
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.output.response_builder import build_response
from data_agent_core.task_execution_contracts import ContractVerificationReport, TaskExecutionContract, semantic_status_from_report
from data_agent_core.verifier.rule_checker import verify_execution


class SemanticStatusDefaultsTest(unittest.TestCase):
    def _trace_for_plan(self, plan: object) -> dict[str, object]:
        effective_plan = prepare_execution_plan_for_backend(plan, source="pandas_executor")[0]
        return build_actual_execution_trace(
            effective_plan,
            source="pandas_executor",
            include_metrics=True,
            include_aggregation=True,
            include_formula=True,
            include_groupby=True,
            include_filters=True,
            include_ranking=True,
        )

    def test_no_task_contract_defaults_to_legacy_unverified(self) -> None:
        result = semantic_status_from_report(contract=None, report=None)

        self.assertEqual("legacy_unverified", result)
        self.assertNotEqual("passed", result)

    def test_contract_failed_report_should_not_be_passed(self) -> None:
        logic = LogicForm(
            task_type="ranking",
            operation="ranking",
            metric="sales",
            group_by="city",
            parameters={"metric": "sales", "dimension": "city", "limit": 3},
            output_format={"answer_type": "table"},
        )
        plan = build_analysis_plan(logic)
        execution_result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["city"],
            rows=[{"city": "上海"}],
            value=[{"city": "上海"}],
        )
        verification = verify_execution(
            execution_result,
            plan=plan,
            user_question=UserQuestion(dataset_id="ds", question="城市 sales Top 3 是哪些？", execution_mode="dual"),
        )
        response = build_response(
            run_id="run_test_failed_contract",
            user_question=UserQuestion(dataset_id="ds", question="城市 sales Top 3 是哪些？", execution_mode="dual"),
            plan=plan,
            execution_result=execution_result,
            verification=verification,
        ).to_dict()

        self.assertIsNotNone(verification.contract_report)
        self.assertFalse(verification.contract_report["passed"])
        self.assertEqual("failed", response["semantic_status"])
        self.assertNotEqual("passed", response["semantic_status"])

    def test_contract_passed_report_can_be_passed(self) -> None:
        logic = LogicForm(
            task_type="ranking",
            operation="ranking",
            metric="sales",
            group_by="city",
            parameters={"metric": "sales", "dimension": "city", "limit": 2},
            output_format={"answer_type": "table"},
        )
        plan = build_analysis_plan(logic)
        execution_result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["city", "sales"],
            rows=[
                {"city": "上海", "sales": 1200},
                {"city": "北京", "sales": 900},
            ],
            value=[
                {"city": "上海", "sales": 1200},
                {"city": "北京", "sales": 900},
            ],
            execution_trace=self._trace_for_plan(plan),
        )
        verification = verify_execution(
            execution_result,
            plan=plan,
            user_question=UserQuestion(dataset_id="ds", question="城市 sales Top 2 是哪些？", execution_mode="dual"),
        )
        response = build_response(
            run_id="run_test_passed_contract",
            user_question=UserQuestion(dataset_id="ds", question="城市 sales Top 2 是哪些？", execution_mode="dual"),
            plan=plan,
            execution_result=execution_result,
            verification=verification,
        ).to_dict()

        self.assertIsNotNone(verification.contract_report)
        self.assertTrue(verification.contract_report["passed"])
        self.assertEqual("passed", response["semantic_status"])
        self.assertNotEqual("failed", response["semantic_status"])

    def test_contract_correction_can_mark_corrected_passed(self) -> None:
        contract = TaskExecutionContract(
            contract_id="contract_topn_test",
            task_family="topn",
            required_n=3,
            required_output_columns=["city", "sales"],
        )
        report = ContractVerificationReport(contract_id="contract_topn_test", task_family="topn", passed=True)

        self.assertEqual(
            "corrected_passed",
            semantic_status_from_report(contract=contract, report=report, corrected=True),
        )
        self.assertEqual(
            "passed",
            semantic_status_from_report(contract=contract, report=report, corrected=False),
        )


if __name__ == "__main__":
    unittest.main()
