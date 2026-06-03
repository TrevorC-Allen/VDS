from __future__ import annotations

import unittest

from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.oracle_results import build_oracle_result
from data_agent_core.task_execution_contracts import TaskExecutionContract


class OracleExpectedResultCoverageTest(unittest.TestCase):
    def _contract(self, *, family: str, **kwargs: object) -> TaskExecutionContract:
        return TaskExecutionContract(contract_id=f"contract_{family}", task_family=family, **kwargs)

    def _assert_issue_metadata(self, result, *, family: str, capability: str, operation: str, reason_prefix: str) -> None:
        metadata = result.issue_metadata or {}
        self.assertIn("task_family", metadata)
        self.assertIn("capability_family", metadata)
        self.assertIn("operation", metadata)
        self.assertIn("reason", metadata)
        self.assertEqual(family, metadata["task_family"])
        self.assertEqual(capability, metadata["capability_family"])
        self.assertEqual(operation, metadata["operation"])
        self.assertIsInstance(metadata["reason"], str)
        self.assertIn(reason_prefix, str(metadata["reason"]))

    def test_topn_with_top_rows_reports_non_empty_expected_result(self) -> None:
        contract = self._contract(
            family="topn",
            metric="metric_value",
            dimension="value",
            verification_rules={"expected_result": None},
        )
        result = build_oracle_result(
            contract,
            ExecutionResult(
                backend="unit-test",
                success=True,
                columns=["value", "metric_value"],
                rows=[
                    {"value": "A", "metric_value": 100},
                    {"value": "B", "metric_value": 80},
                ],
            ),
        )

        self.assertIn("oracle_expected_result_missing", result.issue_codes)
        self.assertIsNotNone(result.expected_result)
        self.assertIsNotNone(result.issue_metadata)
        self._assert_issue_metadata(
            result,
            family="topn",
            capability="ranking",
            operation="ranking",
            reason_prefix="missing_expected_result_for_ranking_top_rows",
        )

    def test_topn_followup_gap_payload_returns_expected_result_and_no_missing(self) -> None:
        contract = self._contract(
            family="topn",
            metric="amount",
            dimension="city",
            verification_rules={
                "expected_result": None,
                "operation": "filtered_metric_ranking",
                "capability_family": "ranking_followup",
            },
        )
        result = build_oracle_result(
            contract,
            ExecutionResult(
                backend="unit-test",
                success=True,
                columns=["city", "amount"],
                rows=[
                    {"city": "上海", "amount": 325},
                    {"city": "北京", "amount": 310},
                ],
            ),
        )

        self.assertNotIn("oracle_expected_result_missing", result.issue_codes)
        self.assertIsNotNone(result.expected_result)
        self.assertEqual("ranking_followup_gap", (result.expected_result or {}).get("task_family"))
        self.assertTrue((result.expected_result or {}).get("comparison_possible"))


    def test_topn_without_top_rows_records_missing_expected_with_metadata(self) -> None:
        contract = self._contract(
            family="topn",
            metric="metric_value",
            dimension="value",
            verification_rules={"expected_result": None},
        )
        result = build_oracle_result(
            contract,
            ExecutionResult(
                backend="unit-test",
                success=True,
                columns=["value", "metric_value"],
                rows=[],
            ),
        )

        self.assertIn("oracle_expected_result_missing", result.issue_codes)
        self.assertIsNone(result.expected_result)
        self._assert_issue_metadata(
            result,
            family="topn",
            capability="ranking",
            operation="ranking",
            reason_prefix="missing_expected_result_for_ranking_top_rows",
        )

    def test_gap_followup_with_gap_payload_reports_non_empty_expected_result(self) -> None:
        contract = self._contract(
            family="gap",
            metric="metric_value",
            dimension="value",
            verification_rules={"expected_result": None},
        )
        result = build_oracle_result(
            contract,
            ExecutionResult(
                backend="unit-test",
                success=True,
                value={
                    "top_objects": [
                        {"value": "A", "metric_value": 200},
                        {"value": "B", "metric_value": 100},
                    ],
                    "adjacent_gaps": [100],
                    "gap_to_leader": [0, 100],
                },
            ),
        )

        self.assertIn("oracle_expected_result_missing", result.issue_codes)
        self.assertIsNotNone(result.expected_result)
        self.assertIsNotNone(result.issue_metadata)
        self._assert_issue_metadata(
            result,
            family="gap",
            capability="ranking_followup",
            operation="ranking",
            reason_prefix="missing_expected_result_for_ranking_gap_followup",
        )

    def test_trend_followup_with_time_series_reports_non_empty_expected_result(self) -> None:
        contract = self._contract(
            family="trend",
            metric="sales",
            dimension="month",
            verification_rules={"expected_result": None},
        )
        result = build_oracle_result(
            contract,
            ExecutionResult(
                backend="unit-test",
                success=True,
                value=[
                    {"month": "2026-01", "sales": 101},
                    {"month": "2026-02", "sales": 203},
                    {"month": "2026-03", "sales": 180},
                ],
            ),
        )

        self.assertNotIn("oracle_expected_result_missing", result.issue_codes)
        self.assertTrue(result.oracle_available)
        self.assertTrue(result.passed)
        self.assertIsNotNone(result.expected_result)
        self.assertEqual("trend_followup", result.expected_result.get("task_family"))
        self.assertEqual("month", result.expected_result.get("time_dimension"))
        self.assertEqual("sales", result.expected_result.get("metric"))
        self.assertEqual(3, result.expected_result.get("expected_point_count"))
        self.assertIsNotNone(result.issue_metadata)
        self._assert_issue_metadata(
            result,
            family="trend",
            capability="trend_followup",
            operation="aggregation",
            reason_prefix="missing_expected_result_for_time_series_trend",
        )

    def test_trend_followup_without_actual_structure_keeps_missing_expected_result(self) -> None:
        contract = self._contract(
            family="trend",
            metric="sales",
            dimension="month",
            verification_rules={"expected_result": None},
        )
        result = build_oracle_result(
            contract,
            ExecutionResult(
                backend="unit-test",
                success=True,
                value={"answer": "趋势需要更多数据。"},
            ),
        )

        self.assertIn("oracle_expected_result_missing", result.issue_codes)
        self.assertFalse(result.oracle_available)
        self.assertIsNone(result.expected_result)
        self._assert_issue_metadata(
            result,
            family="trend",
            capability="trend_followup",
            operation="aggregation",
            reason_prefix="missing_expected_result_for_time_series_trend",
        )

    def test_overview_reports_non_empty_expected_result(self) -> None:
        contract = self._contract(
            family="overview",
            verification_rules={"expected_result": None},
        )
        result = build_oracle_result(
            contract,
            ExecutionResult(
                backend="unit-test",
                success=True,
                value={
                    "tables": [
                        {"name": "orders", "fields": [
                            {"name": "month"},
                            {"name": "city"},
                            {"name": "sales"},
                        ]},
                    ]
                },
            ),
        )

        self.assertIn("oracle_expected_result_missing", result.issue_codes)
        self.assertIsNotNone(result.expected_result)
        self._assert_issue_metadata(
            result,
            family="overview",
            capability="overview",
            operation="dataset_overview",
            reason_prefix="missing_expected_result_for_overview_schema",
        )

    def test_multi_file_overview_reports_non_empty_expected_result(self) -> None:
        contract = self._contract(
            family="multi_file_overview",
            verification_rules={"expected_result": None},
        )
        result = build_oracle_result(
            contract,
            ExecutionResult(
                backend="unit-test",
                success=True,
                value={
                    "tables": [
                        {"name": "orders", "fields": [{"name": "order_id"}, {"name": "customer_id"}]},
                        {"name": "customers", "fields": [{"name": "customer_id"}, {"name": "city"}]},
                    ]
                },
            ),
        )

        self.assertIn("oracle_expected_result_missing", result.issue_codes)
        self.assertIsNotNone(result.expected_result)
        self.assertIsNotNone(result.issue_metadata)
        self._assert_issue_metadata(
            result,
            family="multi_file_overview",
            capability="multi_file_overview",
            operation="multi_table_dataset_overview",
            reason_prefix="missing_expected_result_for_multi_file_overview_schema",
        )


if __name__ == "__main__":
    unittest.main()
