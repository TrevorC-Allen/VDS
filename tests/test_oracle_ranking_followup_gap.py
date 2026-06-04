from __future__ import annotations

import unittest

from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.oracle_results import oracle_topn_followup_gap
from data_agent_core.task_execution_contracts import TaskExecutionContract
from data_agent_core.oracle_results import build_oracle_result


class OracleRankingFollowupGapTest(unittest.TestCase):
    def _contract(self, expected: dict[str, object]) -> TaskExecutionContract:
        return TaskExecutionContract(
            contract_id="contract_ranking_followup_gap_expected",
            task_family="topn",
            metric="metric_value",
            dimension="value",
            verification_rules={
                "expected_result": expected,
                "operation": "ranking",
                "capability_family": "ranking_followup",
            },
        )

    def test_oracle_gap_case_1_exact_match_and_passes(self) -> None:
        expected = {
            "top_objects": [
                {"rank": 1, "value": "深圳", "metric_value": 749},
                {"rank": 2, "value": "上海", "metric_value": 563},
                {"rank": 3, "value": "北京", "metric_value": 276},
            ],
            "adjacent_gaps": [186, 287],
            "gap_to_leader": [0, 186, 473],
        }
        actual = {
            "top_objects": [
                {"rank": 1, "value": "深圳", "metric_value": 749},
                {"rank": 2, "value": "上海", "metric_value": 563},
                {"rank": 3, "value": "北京", "metric_value": 276},
            ],
            "adjacent_gaps": [186, 287],
            "gap_to_leader": [0, 186, 473],
        }

        result = oracle_topn_followup_gap(expected, actual, answer="深圳相比上海差距186，北京相比上海差距287。")

        self.assertTrue(result.oracle_available)
        self.assertTrue(result.passed)
        self.assertEqual([], result.issue_codes)
        self.assertEqual([186, 287], (result.actual_result or {}).get("adjacent_gaps"))
        self.assertEqual([0, 186, 473], (result.actual_result or {}).get("gap_to_leader"))

    def test_oracle_topn_expected_task_family_ranking_followup_gap(self) -> None:
        expected = {
            "task_family": "ranking_followup_gap",
            "comparison_possible": True,
            "actual_object_count": 2,
            "dimension": "value",
            "metric": "metric_value",
            "adjacent_gaps": [186],
            "gap_to_leader": [0, 186],
            "top_objects": [
                {"rank": 1, "value": "深圳", "metric_value": 749},
                {"rank": 2, "value": "上海", "metric_value": 563},
            ],
        }

        contract = self._contract(expected)

        result = build_oracle_result(
            contract,
            ExecutionResult(
                backend="unit-test",
                success=True,
                rows=[
                    {"value": "深圳", "metric_value": 749},
                    {"value": "上海", "metric_value": 563},
                ],
                value={"answer": "深圳相比上海差距186。"},
            ),
        )

        self.assertTrue(result.oracle_available)
        self.assertIsNotNone(result.expected_result)
        self.assertEqual("ranking_followup_gap", (result.expected_result or {}).get("task_family"))

    def test_oracle_gap_case_2_only_top1_reports_insufficient_objects(self) -> None:
        expected = {
            "task_family": "gap_or_ranking_followup",
            "comparison_possible": False,
            "reason": "only_one_top_object",
            "minimum_required_objects": 2,
            "actual_object_count": 1,
            "object_dimension": "value",
            "metric": "metric_value",
        }
        actual = {
            "top_objects": [{"rank": 1, "value": "深圳", "metric_value": 749}],
            "adjacent_gaps": [],
            "gap_to_leader": [0],
        }

        result = oracle_topn_followup_gap(expected, actual, answer="只有深圳一条，没法算相邻差距。")

        self.assertTrue(result.passed)
        self.assertEqual([], result.issue_codes)
        self.assertFalse((result.expected_result or {}).get("comparison_possible"))

    def test_oracle_gap_case_3_metric_value_missing_flags_issue(self) -> None:
        expected = {
            "top_objects": [
                {"rank": 1, "value": "深圳", "metric_value": 749},
                {"rank": 2, "value": "上海", "metric_value": 563},
            ],
            "adjacent_gaps": [186],
            "gap_to_leader": [0, 186],
        }
        actual = {
            "top_objects": [
                {"rank": 1, "value": "深圳", "metric_value": 749},
                {"rank": 2, "value": "上海", "metric_value": None},
            ],
            "adjacent_gaps": [186],
            "gap_to_leader": [0, 186],
        }

        result = oracle_topn_followup_gap(expected, actual, answer="Top1和Top2之间差距需要再算。")

        self.assertFalse(result.passed)
        self.assertIn("gap_metric_value_missing", result.issue_codes)


if __name__ == "__main__":
    unittest.main()
