"""Unit tests for multi-table join ranking deterministic oracle fixture path."""

from __future__ import annotations

import unittest

import pandas as pd

from scripts.run_agent_random_conversation_eval import (
    TurnPlan,
    _deterministic_fixture_oracle_result,
)


def _orders_and_customers_tables() -> dict[str, pd.DataFrame]:
    return {
        "orders": pd.DataFrame(
            {
                "customer_id": ["C1", "C2", "C3", "C4"],
                "amount": [80, 310, 245, 20],
            }
        ),
        "customers": pd.DataFrame(
            {
                "customer_id": ["C1", "C2", "C3", "C5"],
                "city": ["上海", "北京", "上海", "深圳"],
            }
        ),
    }


class OracleMultiTableJoinRankingFixtureTest(unittest.TestCase):
    def _turn(self) -> TurnPlan:
        return TurnPlan(
            question="关联明细表和维表后，哪个城市的金额最高？",
            expected_kind="analysis",
            capability_family="multi_table_join_ranking",
            required_operation="ranking",
        )

    def _run_fixture(self, logic: dict[str, object], response: dict[str, object], tables: dict[str, pd.DataFrame]) -> dict[str, object]:
        return _deterministic_fixture_oracle_result(logic, response, tables, turn=self._turn())

    def test_case1_normal_join_ranking_passes(self) -> None:
        logic = {
            "operation": "ranking",
            "parameters": {"metric": "amount", "dimension": "city"},
            "source_tables": ["orders", "customers"],
            "join_plan": {"left": "orders.customer_id", "right": "customers.customer_id"},
        }
        response = {
            "logic_form": logic,
            "success": True,
            "result": {"rows": [{"rank": 1, "city": "上海", "amount": 325}, {"rank": 2, "city": "北京", "amount": 310}]},
        }

        result = self._run_fixture(logic, response, _orders_and_customers_tables())

        self.assertTrue(result["oracle_available"])
        self.assertTrue(result["passed"], result.get("diff_summary"))
        self.assertEqual([], result["issue_codes"])
        self.assertEqual(
            "orders.customer_id",
            result["expected_result"].get("join_key", {}).get("left"),  # type: ignore[index]
        )
        self.assertEqual(
            "orders.customer_id",
            result["actual_result"].get("join_key", {}).get("left"),  # type: ignore[index]
        )
        expected = result["expected_result"] if isinstance(result["expected_result"], dict) else {}
        self.assertIn("source_tables", expected)
        self.assertIn("join_key", expected)
        self.assertEqual("上海", expected.get("top_object", {}).get("city"))
        self.assertEqual("上海", result["actual_result"].get("top_object", {}).get("city"))
        self.assertEqual(325, expected.get("top_value"))
        self.assertEqual(325, result["actual_result"].get("top_value"))

    def test_case2_join_key_missing_reports_issue(self) -> None:
        logic = {
            "operation": "ranking",
            "parameters": {"metric": "amount", "dimension": "city"},
            "source_tables": ["orders", "customers"],
        }
        response = {
            "logic_form": logic,
            "success": True,
            "result": {"rows": [{"rank": 1, "city": "上海", "amount": 325}, {"rank": 2, "city": "北京", "amount": 310}]},
        }

        result = self._run_fixture(logic, response, _orders_and_customers_tables())

        self.assertFalse(result["passed"])
        self.assertIn("join_key_missing", result["issue_codes"])

    def test_case3_top_object_mismatch_outputs_diff(self) -> None:
        logic = {
            "operation": "ranking",
            "parameters": {"metric": "amount", "dimension": "city"},
            "source_tables": ["orders", "customers"],
            "join_plan": {"left": "orders.customer_id", "right": "customers.customer_id"},
        }
        response = {
            "logic_form": logic,
            "success": True,
            "result": {"rows": [{"rank": 1, "city": "北京", "amount": 310}, {"rank": 2, "city": "上海", "amount": 325}]},
        }

        result = self._run_fixture(logic, response, _orders_and_customers_tables())

        self.assertFalse(result["passed"])
        self.assertIn("join_ranking_top_object_mismatch", result["issue_codes"])
        self.assertIsNotNone(result["diff_summary"])
        self.assertNotEqual(
            result["expected_result"].get("top_object"),  # type: ignore[arg-type]
            result["actual_result"].get("top_object"),
        )


if __name__ == "__main__":
    unittest.main()
