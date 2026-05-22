"""Tests for benchmark metric and error-analysis aggregation."""

from __future__ import annotations

import unittest

from data_agent_core.benchmark.error_analysis import summarize_failures
from data_agent_core.benchmark.metrics import summarize_details


class BenchmarkMetricsTest(unittest.TestCase):
    def test_metrics_group_by_operation_and_error_type(self) -> None:
        details = [
            {
                "operation": "ranking",
                "capability_family": "ranking",
                "success": True,
                "correct": True,
                "error_type": None,
                "sql_support": "native_sql",
                "sql_skipped": False,
                "sql_success": True,
                "pandas_sql_consistent": True,
            },
            {
                "operation": "ranking",
                "capability_family": "ranking",
                "success": True,
                "correct": False,
                "error_type": "BENCHMARK_EVALUATION_ERROR",
                "sql_support": "native_sql",
                "sql_skipped": False,
                "sql_success": True,
                "pandas_sql_consistent": False,
                "executor_mismatch": True,
            },
            {
                "operation": "aggregation",
                "capability_family": "metric_aggregation",
                "success": False,
                "correct": None,
                "error_type": "VERIFICATION_FAILED",
                "sql_support": "unsupported",
                "sql_skipped": True,
                "coverage_gap": True,
            },
        ]

        metrics = summarize_details(details)
        errors = summarize_failures(details)

        self.assertEqual(metrics["total"], 3)
        self.assertEqual(metrics["scored"], 2)
        self.assertEqual(metrics["correct"], 1)
        self.assertEqual(metrics["operation_metrics"]["ranking"]["scored"], 2)
        self.assertEqual(metrics["capability_family_metrics"]["ranking"]["total"], 2)
        self.assertEqual(metrics["sql_coverage"]["covered"], 2)
        self.assertEqual(metrics["sql_coverage"]["skipped"], 1)
        self.assertEqual(metrics["pandas_sql_consistency"]["both_available"], 2)
        self.assertEqual(metrics["pandas_sql_consistency"]["consistent"], 1)
        self.assertEqual(metrics["gap_counts"]["coverage_gap"], 1)
        self.assertEqual(metrics["gap_counts"]["executor_mismatch"], 1)
        self.assertEqual(errors["failure_count"], 2)
        self.assertEqual(errors["by_error_type"]["BENCHMARK_EVALUATION_ERROR"], 1)

    def test_metrics_keep_sql_subset_accuracy_separate_from_final_answer_accuracy(self) -> None:
        details = [
            {
                "operation": "row_count",
                "capability_family": "counting",
                "success": True,
                "correct": True,
                "sql_support": "native_sql",
                "sql_skipped": False,
                "sql_success": True,
                "sql_correct": True,
                "pandas_sql_consistent": True,
            },
            {
                "operation": "best_fraud_aci_choice",
                "capability_family": "business_rule_what_if",
                "success": True,
                "correct": True,
                "sql_support": "shared_rule_engine",
                "sql_skipped": True,
                "coverage_gap": True,
            },
            {
                "operation": "rank_by_metric",
                "capability_family": "metric_definition",
                "success": True,
                "correct": False,
                "sql_support": "native_sql",
                "sql_skipped": False,
                "sql_success": True,
                "sql_correct": False,
                "pandas_sql_consistent": True,
                "semantic_mismatch": True,
            },
        ]

        metrics = summarize_details(details)

        self.assertEqual(metrics["scored"], 3)
        self.assertEqual(metrics["correct"], 2)
        self.assertEqual(metrics["sql_covered_subset_accuracy"]["scored"], 2)
        self.assertEqual(metrics["sql_covered_subset_accuracy"]["correct"], 1)
        self.assertEqual(metrics["gap_counts"]["coverage_gap"], 1)
        self.assertEqual(metrics["gap_counts"]["semantic_mismatch"], 1)

    def test_risk_taxonomy_separates_format_semantic_capability_and_submission_risks(self) -> None:
        details = [
            {
                "task_id": "format",
                "agent_answer": "[{'amount': 1}]",
                "success": False,
                "correct": False,
                "format_mismatch": True,
                "output_contract_passed": False,
                "output_risk_flags": {"object_or_list_leak": True},
            },
            {
                "task_id": "semantic",
                "agent_answer": "42",
                "success": True,
                "correct": False,
                "semantic_mismatch": True,
            },
            {
                "task_id": "capability",
                "agent_answer": "Not Applicable",
                "success": False,
                "correct": None,
                "expected_available": False,
                "coverage_gap": True,
                "not_applicable_category": "capability_gap",
            },
            {
                "task_id": "trace",
                "agent_answer": "debug: trace: tool_call",
                "success": False,
                "correct": None,
                "expected_available": False,
                "output_risk_flags": {"debug_or_trace_leak": True},
            },
        ]

        risks = summarize_details(details)["risk_taxonomy"]

        self.assertEqual(1, risks["format_risk"]["count"])
        self.assertEqual(1, risks["semantic_risk"]["count"])
        self.assertEqual(1, risks["capability_risk"]["count"])
        self.assertEqual(2, risks["submission_risk"]["count"])
        self.assertEqual(1, risks["trace_redaction_risk"]["count"])
        self.assertFalse(risks["official_hidden_unknown"]["applies"])
        self.assertFalse(risks["public_proxy_observation"]["used_in_core_chain"])


if __name__ == "__main__":
    unittest.main()
