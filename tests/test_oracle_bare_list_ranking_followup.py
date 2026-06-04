from __future__ import annotations

import unittest

from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.oracle_results import build_oracle_result
from data_agent_core.task_execution_contracts import TaskExecutionContract


class OracleBareListRankingFollowupGapTest(unittest.TestCase):
    def _contract(self, metric: str = "amount", **kwargs: object) -> TaskExecutionContract:
        contract_kwargs = {
            "task_family": "topn",
            "metric": metric,
            "dimension": "city",
            "verification_rules": {
                "expected_result": None,
                "operation": "filtered_metric_ranking",
                "capability_family": "ranking_followup",
            },
        }
        contract_kwargs.update(kwargs)
        return TaskExecutionContract(
            contract_id="contract_topn_followup_gap_bare_list",
            **contract_kwargs,
        )

    def test_case1_top2_bare_list_gap(self) -> None:
        result = build_oracle_result(
            self._contract(),
            ExecutionResult(
                backend="unit-test",
                success=True,
                columns=["city", "amount"],
                rows=[
                    {"city": "上海", "amount": 325},
                    {"city": "北京", "amount": 310},
                ],
                value={"answer": "前 2 名城市之间差距有多大？"},
            ),
        )

        expected = result.expected_result or {}
        self.assertIsNotNone(result.expected_result)
        self.assertNotIn("oracle_expected_result_missing", result.issue_codes)
        self.assertEqual("ranking_followup_gap", expected.get("task_family"))
        self.assertTrue(expected.get("comparison_possible"))
        self.assertIn(15, expected.get("adjacent_gaps") or [])
        self.assertTrue(result.oracle_available)
        self.assertTrue(result.passed)

    def test_case2_top3_bare_list_gap(self) -> None:
        result = build_oracle_result(
            self._contract(),
            ExecutionResult(
                backend="unit-test",
                success=True,
                columns=["city", "amount"],
                rows=[
                    {"city": "上海", "amount": 325},
                    {"city": "北京", "amount": 310},
                    {"city": "深圳", "amount": 288},
                ],
                value={"answer": "前 3 名城市之间差距有多大？"},
            ),
        )

        expected = result.expected_result or {}
        self.assertIsNotNone(result.expected_result)
        self.assertNotIn("oracle_expected_result_missing", result.issue_codes)
        self.assertEqual("ranking_followup_gap", expected.get("task_family"))
        self.assertTrue(expected.get("comparison_possible"))
        self.assertEqual([15, 22], expected.get("adjacent_gaps"))
        self.assertEqual([0, 15, 37], expected.get("gap_to_leader"))
        self.assertTrue(result.oracle_available)
        self.assertTrue(result.passed)

    def test_case3_top1_with_profit_rate_and_insufficient_explanation_passes(self) -> None:
        result = build_oracle_result(
            self._contract(metric="利润率"),
            ExecutionResult(
                backend="unit-test",
                success=True,
                columns=["city", "利润率"],
                rows=[
                    {"city": "深圳", "利润率": 0.3258},
                ],
                value={"answer": "仅包含深圳一个城市，无法比较差距。"},
            ),
        )

        expected = result.expected_result or {}
        self.assertIsNotNone(result.expected_result)
        self.assertNotIn("oracle_expected_result_missing", result.issue_codes)
        self.assertEqual("ranking_followup_gap", expected.get("task_family"))
        self.assertFalse(expected.get("comparison_possible"))
        self.assertEqual("only_one_top_object", expected.get("reason"))
        self.assertTrue(result.oracle_available)
        self.assertTrue(result.passed)

    def test_case4_top1_without_insufficient_explanation_fails(self) -> None:
        result = build_oracle_result(
            self._contract(metric="利润率"),
            ExecutionResult(
                backend="unit-test",
                success=True,
                columns=["city", "利润率"],
                rows=[
                    {"city": "深圳", "利润率": 0.3258},
                ],
                value={"answer": "前 1 名城市差距如何？"},
            ),
        )

        expected = result.expected_result or {}
        self.assertIsNotNone(result.expected_result)
        self.assertNotIn("oracle_expected_result_missing", result.issue_codes)
        self.assertEqual("ranking_followup_gap", expected.get("task_family"))
        self.assertFalse(expected.get("comparison_possible"))
        self.assertIn("gap_insufficient_objects_not_explained", result.issue_codes)
        self.assertEqual("only_one_top_object", expected.get("reason"))
        self.assertTrue(result.oracle_available)
        self.assertFalse(result.passed)

    def test_case5_bad_shape_preserves_missing(self) -> None:
        result = build_oracle_result(
            self._contract(),
            ExecutionResult(
                backend="unit-test",
                success=True,
                value="some text",
            ),
        )

        self.assertIn("oracle_expected_result_missing", result.issue_codes)
        self.assertIsNone(result.expected_result)
        self.assertIsNotNone(result.issue_metadata)
        self.assertEqual("topn", result.issue_metadata.get("task_family"))


if __name__ == "__main__":
    unittest.main()
