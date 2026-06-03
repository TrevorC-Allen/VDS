from __future__ import annotations

import unittest

from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.task_execution_contracts import TaskExecutionContract, verify_task_execution_contract


class TrendEmptyResultDiagnosticsTest(unittest.TestCase):
    def _contract(self) -> TaskExecutionContract:
        return TaskExecutionContract(
            contract_id="contract_trend_diagnostics",
            task_family="trend",
            metric="销售额",
            dimension="月份",
            time_dimension="月份",
            required_output_columns=["月份", "销售额"],
            verification_rules={"trend_time_series_required": True},
        )

    def _codes(self, result_report) -> set[str]:
        return {violation.code for violation in result_report.violations}

    def test_rows_empty_reports_empty_result_code(self) -> None:
        result = ExecutionResult(backend="pandas", success=True, columns=["月份", "销售额"], rows=[], value={})
        report = verify_task_execution_contract(self._contract(), result)
        self.assertIn("TREND_EMPTY_RESULT", self._codes(report))

    def test_missing_time_column_reports_time_dimension_code(self) -> None:
        result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["销售额"],
            rows=[{"销售额": 100}],
            value=[{"销售额": 100}],
        )
        report = verify_task_execution_contract(self._contract(), result)
        self.assertIn("TREND_TIME_COLUMN_MISSING", self._codes(report))

    def test_missing_metric_column_reports_metric_code(self) -> None:
        result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["月份"],
            rows=[{"月份": "2026-01"}],
            value=[{"月份": "2026-01"}],
        )
        report = verify_task_execution_contract(self._contract(), result)
        self.assertIn("TREND_METRIC_COLUMN_MISSING", self._codes(report))

    def test_rows_without_time_series_artifact_reports_time_series_code(self) -> None:
        rows = [
            {"月份": "2026-01", "销售额": 100},
            {"月份": "2026-02", "销售额": 200},
        ]
        result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["月份", "销售额"],
            rows=rows,
            value={"answer": "已生成趋势"},
        )
        report = verify_task_execution_contract(self._contract(), result)
        self.assertIn("TREND_TIME_SERIES_MISSING", self._codes(report))


if __name__ == "__main__":
    unittest.main()
