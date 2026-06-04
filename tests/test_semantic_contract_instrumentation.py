from __future__ import annotations

import unittest

from data_agent_core.contracts.analysis_contracts import LogicForm, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.output.response_builder import build_response
from data_agent_core.verifier.rule_checker import verify_execution
from scripts.run_agent_random_conversation_eval import ScenarioResult, TurnEvidence, TurnPlan, _coverage_summary, _turn_issues


class SemanticContractInstrumentationTest(unittest.TestCase):
    def test_analysis_plan_attaches_topn_task_contract(self) -> None:
        logic = LogicForm(
            task_type="ranking",
            operation="ranking",
            metric="sales",
            group_by="city",
            parameters={"metric": "sales", "dimension": "city", "limit": 3},
            output_format={"answer_type": "table"},
        )

        plan = build_analysis_plan(logic)

        self.assertIsNotNone(plan.task_contract)
        self.assertEqual("topn", plan.task_contract.task_family)
        self.assertEqual(3, plan.task_contract.required_n)
        self.assertEqual("topn", logic.task_contract["task_family"])

    def test_response_exposes_contract_and_oracle_without_default_passed(self) -> None:
        logic = LogicForm(task_type="detail_lookup", operation="detail_lookup")
        plan = build_analysis_plan(logic)
        execution_result = ExecutionResult(backend="pandas", success=True, value={"row_count": 2})
        verification = verify_execution(
            execution_result,
            plan=plan,
            user_question=UserQuestion(dataset_id="ds", question="看一下明细", execution_mode="dual"),
        )

        response = build_response(
            run_id="run_test",
            user_question=UserQuestion(dataset_id="ds", question="看一下明细", execution_mode="dual"),
            plan=plan,
            execution_result=execution_result,
            verification=verification,
        ).to_dict()

        self.assertEqual("legacy_unverified", response["semantic_status"])
        self.assertIsNone(response["contract_satisfied"])
        self.assertIsNone(response["contract_family"])
        self.assertEqual([], response["violations"])
        self.assertFalse(response["oracle_result"]["oracle_available"])

    def test_contract_failure_is_reported_with_violation_code(self) -> None:
        logic = LogicForm(
            task_type="ranking",
            operation="ranking",
            metric="sales",
            group_by="city",
            parameters={"metric": "sales", "dimension": "city", "limit": 3},
            output_format={"answer_type": "table"},
        )
        plan = build_analysis_plan(logic)
        execution_result = ExecutionResult(backend="pandas", success=True, columns=["city"], rows=[{"city": "上海"}], value=[{"city": "上海"}])

        verification = verify_execution(
            execution_result,
            plan=plan,
            user_question=UserQuestion(dataset_id="ds", question="城市 sales Top 3 是哪些？", execution_mode="dual"),
        )

        self.assertEqual("failed", verification.semantic_status)
        self.assertIsNotNone(verification.contract_report)
        codes = [item["code"] for item in verification.contract_report["violations"]]
        self.assertIn("required_output_column_missing", codes)

    def test_eval_coverage_counts_semantic_contract_fields(self) -> None:
        result = ScenarioResult(
            scenario_id="semantic_contract_smoke",
            capability_family="ranking",
            run_index=1,
            passed=True,
            simulator_source="deterministic",
            issues=[],
            turns=[
                TurnEvidence(
                    index=1,
                    question="哪个城市销售额最高？",
                    expected_kind="analysis",
                    capability_family="ranking",
                    required_operation="ranking",
                    success=True,
                    answer_type="table",
                    operation="ranking",
                    conversation_id="conv",
                    state_name="analysis_ready",
                    semantic_status="passed",
                    contract_satisfied=True,
                    contract_family="topn",
                    contract_checked=True,
                    oracle_available=True,
                    oracle_passed=True,
                    oracle_issue_codes=["oracle_expected_result_missing"],
                )
            ],
        )

        coverage = _coverage_summary([result])

        self.assertEqual(1, coverage["semantic_contract_turns"])
        self.assertEqual(1, coverage["oracle_result_turns"])
        self.assertEqual(1, coverage["oracle_available_turns"])
        self.assertEqual(1, coverage["oracle_passed_turns"])
        self.assertEqual(0, coverage["oracle_failed_turns"])
        self.assertEqual(1, coverage["contract_checked_turns"])
        self.assertEqual(1, coverage["contract_satisfied_turns"])
        self.assertEqual(1, coverage["semantic_passed_turns"])

    def test_eval_turn_issues_fail_oracle_mismatch(self) -> None:
        evidence = TurnEvidence(
            index=1,
            question="哪个城市销售额最高？",
            expected_kind="analysis",
            capability_family="ranking",
            required_operation="ranking",
            success=True,
            answer_type="table",
            operation="ranking",
            conversation_id="conv",
            state_name="analysis_ready",
            oracle_available=True,
            oracle_passed=False,
            oracle_issue_codes=["deterministic_fixture_oracle_mismatch"],
        )

        issues = _turn_issues(
            1,
            TurnPlan("哪个城市销售额最高？", capability_family="ranking", required_operation="ranking"),
            {
                "success": True,
                "answer": "上海最高。",
                "logic_form": {"operation": "ranking", "parameters": {"metric": "sales", "dimension": "city"}},
                "current_analysis_context": {"state_name": "analysis_ready"},
            },
            previous_conversation_id="",
            evidence=evidence,
        )

        self.assertIn("turn_1:oracle_result_failed:deterministic_fixture_oracle_mismatch", issues)


if __name__ == "__main__":
    unittest.main()
