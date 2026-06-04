from __future__ import annotations

import unittest

from scripts.run_agent_random_conversation_eval import (
    ConversationScenario,
    ScenarioResult,
    TurnEvidence,
    TurnPlan,
    _failure_rows,
    _scenario_issues,
    _scenario_pass_rate,
    _turn_issues,
    _is_turn_semantically_successful,
)


def _fake_turn(
    *,
    index: int = 1,
    semantic_status: str = "passed",
    contract_satisfied: bool | None = True,
    oracle_passed: bool | None = None,
    oracle_issue_codes: list[str] | None = None,
    llm_judge_failed: bool | None = False,
    contract_violation_error_codes: list[str] | None = None,
    success: bool = True,
) -> TurnEvidence:
    return TurnEvidence(
        index=index,
        question=f"Turn {index}",
        expected_kind="analysis",
        capability_family="ranking",
        required_operation="ranking",
        success=success,
        answer_type="table",
        operation="ranking",
        conversation_id="conv_no_stale",
        state_name="analysis_ready",
        semantic_status=semantic_status,
        contract_satisfied=contract_satisfied,
        contract_family="topn",
        contract_checked=True,
        contract_violation_error_codes=contract_violation_error_codes or [],
        oracle_available=False,
        oracle_passed=oracle_passed,
        oracle_issue_codes=oracle_issue_codes or [],
        action_count=1,
        next_action_questions=[],
        llm_judge_failed=llm_judge_failed,
    )


class NoStaleAnalysisFailedTest(unittest.TestCase):
    def test_case_a_scenario_all_green_but_legacy_success_false(self) -> None:
        turn = _fake_turn(success=False)
        response = {
            "success": False,
            "answer": "上海最高。",
            "logic_form": {"operation": "ranking"},
            "current_analysis_context": {"state_name": "analysis_ready"},
            "oracle_result": {"oracle_available": False},
            "llm_judge_failed": False,
        }
        issues = _turn_issues(
            1,
            TurnPlan("哪个城市销售额最高？", expected_kind="analysis", capability_family="ranking", required_operation="ranking"),
            response,
            previous_conversation_id="conv_no_stale",
            evidence=turn,
        )

        scenario = ConversationScenario(
            scenario_id="regional_performance_agent",
            dataset_name="regional_performance",
            capability_family="generic_metric_ranking_followup",
            turn_templates=[],
            min_turn_count=1,
        )
        scenario_issues = _scenario_issues(scenario, [turn])
        result = ScenarioResult(
            scenario_id="regional_performance_agent",
            capability_family="generic_metric_ranking_followup",
            run_index=1,
            passed=all(_is_turn_semantically_successful(item) for item in [turn]),
            simulator_source="mock",
            turns=[turn],
            issues=scenario_issues,
        )

        self.assertNotIn("turn_1:analysis_failed", issues)
        self.assertTrue(_is_turn_semantically_successful(turn))
        self.assertEqual([], scenario_issues)
        self.assertTrue(result.passed)

    def test_case_b_semantic_contract_oracle_green_turn_has_no_failure_rows(self) -> None:
        turn = _fake_turn(index=1)
        scenario = ConversationScenario(
            scenario_id="regional_performance_agent",
            dataset_name="regional_performance",
            capability_family="generic_metric_ranking_followup",
            turn_templates=[],
        )
        turns = [turn, _fake_turn(index=2), _fake_turn(index=3)]
        result = {
            "scenario_id": scenario.scenario_id,
            "run_index": 1,
            "issues": _scenario_issues(scenario, turns),
            "turns": [item.__dict__ for item in turns],
        }
        rows = _failure_rows({"results": [result], "global_issues": []})

        self.assertEqual([], rows)

    def test_insufficient_data_semantic_pass_has_no_failure_rows(self) -> None:
        turn = _fake_turn(index=1, semantic_status="passed_with_insufficient_data", oracle_passed=True)
        result = {
            "scenario_id": "regional_performance_agent",
            "run_index": 1,
            "issues": [],
            "turns": [turn.__dict__],
        }
        rows = _failure_rows({"results": [result], "global_issues": []})

        self.assertTrue(_is_turn_semantically_successful(turn))
        self.assertEqual([], rows)

    def test_case_c_oracle_expected_or_actual_missing_still_fails(self) -> None:
        turn = _fake_turn(oracle_passed=None, oracle_issue_codes=["oracle_expected_result_missing"])
        response = {
            "success": True,
            "answer": "上海最高。",
            "current_analysis_context": {"state_name": "analysis_ready"},
            "oracle_result": {"oracle_available": False},
            "llm_judge_failed": False,
        }
        issues = _turn_issues(
            1,
            TurnPlan("哪个城市销售额最高？", expected_kind="analysis", capability_family="ranking", required_operation="ranking"),
            response,
            previous_conversation_id="conv_no_stale",
            evidence=turn,
        )

        self.assertIn("turn_1:oracle_result_failed:oracle_expected_result_missing", issues)
        self.assertFalse(_is_turn_semantically_successful(turn))
        self.assertTrue(any("oracle_expected_result_missing" in issue for issue in issues))

    def test_case_c_mismatch_codes_still_fail(self) -> None:
        turn = _fake_turn(oracle_passed=None, oracle_issue_codes=["gap_mismatch"])
        response = {
            "success": True,
            "answer": "Top 结果中前 3 的差距变化。",
            "current_analysis_context": {"state_name": "analysis_ready"},
            "llm_judge_failed": False,
        }
        issues = _turn_issues(
            1,
            TurnPlan("哪个城市销售额最高？", expected_kind="analysis", capability_family="ranking", required_operation="ranking"),
            response,
            previous_conversation_id="conv_no_stale",
            evidence=turn,
        )

        self.assertTrue(any(issue.startswith("turn_1:oracle_result_failed:") for issue in issues))
        self.assertFalse(_is_turn_semantically_successful(turn))

    def test_case_d_oracle_result_failed_still_fails(self) -> None:
        turn = _fake_turn(oracle_passed=False, oracle_issue_codes=[])
        response = {
            "success": True,
            "answer": "上海最高。",
            "oracle_result": {"passed": False},
            "current_analysis_context": {"state_name": "analysis_ready"},
            "llm_judge_failed": False,
        }
        issues = _turn_issues(
            1,
            TurnPlan("哪个城市销售额最高？", expected_kind="analysis", capability_family="ranking", required_operation="ranking"),
            response,
            previous_conversation_id="conv_no_stale",
            evidence=turn,
        )

        self.assertTrue(any(issue.startswith("turn_1:oracle_result_failed:") and "oracle_mismatch" in issue for issue in issues))
        self.assertFalse(_is_turn_semantically_successful(turn))

    def test_case_e_contract_required_not_satisfied_still_fails(self) -> None:
        turn = _fake_turn(contract_satisfied=False)
        response = {
            "success": True,
            "answer": "上海最高。",
            "current_analysis_context": {"state_name": "analysis_ready"},
            "llm_judge_failed": False,
        }
        issues = _turn_issues(
            1,
            TurnPlan("哪个城市销售额最高？", expected_kind="analysis", capability_family="ranking", required_operation="ranking"),
            response,
            previous_conversation_id="conv_no_stale",
            evidence=turn,
        )

        self.assertNotIn("turn_1:analysis_failed", issues)
        self.assertFalse(_is_turn_semantically_successful(turn))

    def test_case_f_llm_judge_failed_still_fails(self) -> None:
        turn = _fake_turn(llm_judge_failed=True)
        response = {
            "success": True,
            "answer": "上海最高。",
            "current_analysis_context": {"state_name": "analysis_ready"},
            "llm_judge_failed": True,
        }
        issues = _turn_issues(
            1,
            TurnPlan("哪个城市销售额最高？", expected_kind="analysis", capability_family="ranking", required_operation="ranking"),
            response,
            previous_conversation_id="conv_no_stale",
            evidence=turn,
        )

        self.assertIn("turn_1:llm_judge_failed", issues)
        self.assertFalse(_is_turn_semantically_successful(turn))

    def test_three_conversations_all_semantically_successful(self) -> None:
        scenario = ConversationScenario(
            scenario_id="regional_performance_agent",
            dataset_name="regional_performance",
            capability_family="generic_metric_ranking_followup",
            turn_templates=[],
        )
        turns = [
            _fake_turn(index=1),
            _fake_turn(index=2),
            _fake_turn(index=3),
        ]
        results = [
            ScenarioResult(
                scenario_id="regional_performance_agent",
                capability_family="generic_metric_ranking_followup",
                run_index=1,
                passed=True,
                simulator_source="mock",
                turns=turns,
                issues=_scenario_issues(scenario, turns),
            ),
            ScenarioResult(
                scenario_id="service_region_agent",
                capability_family="service_metric_followup",
                run_index=1,
                passed=True,
                simulator_source="mock",
                turns=turns,
                issues=_scenario_issues(scenario, turns),
            ),
            ScenarioResult(
                scenario_id="multi_file_customer_revenue_agent",
                capability_family="multi_table_join",
                run_index=1,
                passed=True,
                simulator_source="mock",
                turns=turns,
                issues=_scenario_issues(scenario, turns),
            ),
        ]

        pass_rate = _scenario_pass_rate(results)
        global_issues = []
        min_pass_rate = 1.0
        if pass_rate < min_pass_rate:
            global_issues.append(f"global_pass_rate_below_threshold:{pass_rate:.4f}<{min_pass_rate:.4f}")

        self.assertEqual(1.0, pass_rate)
        self.assertEqual([], global_issues)
        self.assertTrue(all(not result.issues for result in results))
        self.assertTrue(all(_scenario_issues(scenario, result.turns) == [] for result in results))


if __name__ == "__main__":
    unittest.main()
