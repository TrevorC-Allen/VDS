from __future__ import annotations

import unittest

from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.oracle_results import build_oracle_result
from data_agent_core.task_execution_contracts import TaskExecutionContract


class OracleGapInsufficientObjectsTest(unittest.TestCase):
    def _contract(self) -> TaskExecutionContract:
        return TaskExecutionContract(
            contract_id="contract_gap_top1",
            task_family="gap",
            metric="利润率",
            dimension="city",
            verification_rules={"expected_result": None},
        )

    def test_top1_gap_followup_with_insufficient_explanation_passes(self) -> None:
        result = build_oracle_result(
            self._contract(),
            ExecutionResult(
                backend="unit-test",
                success=True,
                columns=["city", "利润率"],
                rows=[{"city": "深圳", "利润率": 0.32}],
                value={"answer": "只有深圳一个 Top 城市，无法比较 Top 城市之间的差距。"},
            ),
        )

        expected = result.expected_result or {}
        self.assertIsNotNone(result.expected_result)
        self.assertEqual("gap_or_ranking_followup", expected.get("task_family"))
        self.assertFalse(expected.get("comparison_possible"))
        self.assertEqual("only_one_top_object", expected.get("reason"))
        self.assertEqual(1, expected.get("actual_object_count"))
        self.assertNotIn("oracle_expected_result_missing", result.issue_codes)
        self.assertTrue(result.passed)

    def test_top1_gap_followup_without_insufficient_explanation_fails(self) -> None:
        result = build_oracle_result(
            self._contract(),
            ExecutionResult(
                backend="unit-test",
                success=True,
                columns=["city", "利润率"],
                rows=[{"city": "深圳", "利润率": 0.32}],
                value={"answer": "深圳比其他 Top 城市利润率差距更明显。"},
            ),
        )

        expected = result.expected_result or {}
        self.assertIsNotNone(result.expected_result)
        self.assertFalse(expected.get("comparison_possible"))
        self.assertNotIn("oracle_expected_result_missing", result.issue_codes)
        self.assertFalse(result.passed)
        self.assertIn("gap_insufficient_objects_not_explained", result.issue_codes)


if __name__ == "__main__":
    unittest.main()
