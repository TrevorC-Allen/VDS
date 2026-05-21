"""Tests for benchmark metric and error-analysis aggregation."""

from __future__ import annotations

import unittest

from data_agent_core.benchmark.error_analysis import summarize_failures
from data_agent_core.benchmark.metrics import summarize_details


class BenchmarkMetricsTest(unittest.TestCase):
    def test_metrics_group_by_operation_and_error_type(self) -> None:
        details = [
            {"operation": "ranking", "success": True, "correct": True, "error_type": None},
            {"operation": "ranking", "success": True, "correct": False, "error_type": "BENCHMARK_EVALUATION_ERROR"},
            {"operation": "aggregation", "success": False, "correct": None, "error_type": "VERIFICATION_FAILED"},
        ]

        metrics = summarize_details(details)
        errors = summarize_failures(details)

        self.assertEqual(metrics["total"], 3)
        self.assertEqual(metrics["scored"], 2)
        self.assertEqual(metrics["correct"], 1)
        self.assertEqual(metrics["operation_metrics"]["ranking"]["scored"], 2)
        self.assertEqual(errors["failure_count"], 2)
        self.assertEqual(errors["by_error_type"]["BENCHMARK_EVALUATION_ERROR"], 1)


if __name__ == "__main__":
    unittest.main()
