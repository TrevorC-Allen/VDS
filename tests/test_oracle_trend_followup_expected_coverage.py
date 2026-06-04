from __future__ import annotations

import unittest

from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.oracle_results import build_oracle_result
from data_agent_core.task_execution_contracts import TaskExecutionContract


class OracleTrendFollowupExpectedCoverageTest(unittest.TestCase):
    def test_actual_time_series_rows_build_constraint_expected_result(self) -> None:
        contract = TaskExecutionContract(
            contract_id="contract_trend_followup",
            task_family="trend",
            metric="sales",
            dimension="month",
            time_dimension="month",
            referent_dimension="city",
            referent_values=["深圳", "上海"],
            verification_rules={"expected_result": None},
        )

        result = build_oracle_result(
            contract,
            ExecutionResult(
                backend="unit-test",
                success=True,
                columns=["month", "city", "sales"],
                rows=[
                    {"month": "2026-01", "city": "深圳", "sales": 100},
                    {"month": "2026-02", "city": "深圳", "sales": 120},
                    {"month": "2026-01", "city": "上海", "sales": 90},
                    {"month": "2026-02", "city": "上海", "sales": 80},
                ],
            ),
        )

        expected = result.expected_result or {}
        self.assertIsNotNone(result.expected_result)
        self.assertTrue(result.oracle_available)
        self.assertIsNotNone(result.passed)
        self.assertEqual("trend_followup", expected.get("task_family"))
        self.assertEqual("month", expected.get("time_dimension"))
        self.assertEqual("sales", expected.get("metric"))
        self.assertEqual(4, expected.get("point_count"))
        self.assertEqual(4, expected.get("expected_point_count"))
        self.assertIn("series_by_referent", expected)
        self.assertEqual(["深圳", "上海"], expected.get("referent_values"))
        self.assertNotIn("oracle_expected_result_missing", result.issue_codes)


if __name__ == "__main__":
    unittest.main()
