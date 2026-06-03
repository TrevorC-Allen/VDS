from __future__ import annotations

import unittest

from data_agent_core.oracle_results import oracle_trend_followup_series
from scripts.run_agent_random_conversation_eval import (
    TurnPlan,
    _deterministic_fixture_oracle_result,
)


class OracleTrendFollowupSeriesHelperTest(unittest.TestCase):
    def _fixture_turn(self) -> TurnPlan:
        return TurnPlan(
            question="按月份看趋势",
            expected_kind="followup_analysis",
            capability_family="trend_followup",
            required_operation="aggregation",
        )

    def _fixture_logic(self) -> dict[str, object]:
        return {
            "operation": "aggregation",
            "parameters": {
                "metric": "sales",
                "dimension": "month",
            },
        }

    def _fixture_response(self, rows: list[dict[str, object]], answer: str) -> dict[str, object]:
        return {
            "success": True,
            "answer": answer,
            "result": {
                "rows": rows,
            },
        }

    def _run_fixture(self, rows: list[dict[str, object]], answer: str) -> dict[str, object]:
        return _deterministic_fixture_oracle_result(
            self._fixture_logic(),
            self._fixture_response(rows, answer),
            {},
            turn=self._fixture_turn(),
        )

    def test_case1_case_up_then_down(self) -> None:
        rows = [
            {"month": "2026-01", "sales": 396},
            {"month": "2026-02", "sales": 550},
            {"month": "2026-03", "sales": 482},
        ]
        oracle = oracle_trend_followup_series([{"month": row["month"], "value": row["sales"]} for row in rows])

        self.assertEqual("up_then_down", oracle["trend_shape"])
        self.assertEqual({"month": "2026-02", "value": 550}, oracle["peak"])
        self.assertEqual({"month": "2026-01", "value": 396}, oracle["low"])
        self.assertEqual("2026-01", oracle["max_change"]["from"])
        self.assertEqual("2026-02", oracle["max_change"]["to"])
        self.assertEqual(154, int(float(oracle["max_change"]["delta"])) )
        self.assertEqual(["整体上升", "单调上升", "持续上升"], oracle["forbidden_descriptions"])

        result = self._run_fixture(rows, answer="走势先升后降，2026-02达到峰值。")
        self.assertTrue(result["oracle_available"])
        self.assertTrue(result["passed"])
        self.assertEqual("up_then_down", result["actual_result"]["trend_shape"])
        self.assertEqual(["整体上升", "单调上升", "持续上升"], result["actual_result"]["forbidden_descriptions"])
        self.assertNotIn("整体上升", str(result["actual_result"].get("trend_description") or ""))
        self.assertNotIn("单调上升", str(result["actual_result"].get("trend_description") or ""))
        self.assertNotIn("持续上升", str(result["actual_result"].get("trend_description") or ""))

        forbidden_case = self._run_fixture(rows, answer="该序列表现整体上升。")
        self.assertFalse(forbidden_case["passed"])
        self.assertIn("trend_followup_forbidden_trend_description_present", forbidden_case["issue_codes"])

    def test_case2_case_increasing(self) -> None:
        rows = [
            {"month": "2026-01", "sales": 100},
            {"month": "2026-02", "sales": 200},
            {"month": "2026-03", "sales": 300},
        ]

        expected_shape = oracle_trend_followup_series([{"month": row["month"], "value": row["sales"]} for row in rows])["trend_shape"]
        self.assertEqual("increasing", expected_shape)

        result = self._run_fixture(rows, answer="趋势持续上升")
        self.assertTrue(result["oracle_available"])
        self.assertTrue(result["passed"])
        self.assertEqual("increasing", result["expected_result"]["trend_shape"])

    def test_case3_case_decreasing(self) -> None:
        rows = [
            {"month": "2026-01", "sales": 300},
            {"month": "2026-02", "sales": 200},
            {"month": "2026-03", "sales": 100},
        ]

        expected_shape = oracle_trend_followup_series([{"month": row["month"], "value": row["sales"]} for row in rows])["trend_shape"]
        self.assertEqual("decreasing", expected_shape)

        result = self._run_fixture(rows, answer="趋势持续下降")
        self.assertTrue(result["oracle_available"])
        self.assertTrue(result["passed"])
        self.assertEqual("decreasing", result["expected_result"]["trend_shape"])

    def test_case4_case_insufficient_periods(self) -> None:
        rows = [{"month": "2026-01", "sales": 100}]

        expected_shape = oracle_trend_followup_series([{"month": row["month"], "value": row["sales"]} for row in rows])["trend_shape"]
        self.assertEqual("insufficient_periods_for_trend", expected_shape)

        result = self._run_fixture(rows, answer="仅有一个周期，无法判断趋势。")
        self.assertTrue(result["oracle_available"])
        self.assertTrue(result["passed"])
        self.assertEqual("insufficient_periods_for_trend", result["expected_result"]["trend_shape"])
        self.assertIsNone(result["expected_result"].get("peak"))


if __name__ == "__main__":
    unittest.main()
