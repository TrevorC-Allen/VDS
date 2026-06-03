"""Unit tests for quality field-level deterministic oracle fixture payload."""

from __future__ import annotations

import unittest

from data_agent_core.oracle_results import oracle_quality_field_counts


def _expected_clean_payload() -> dict:
    return {
        "fields": [
            {"name": "month", "missing_count": 0, "missing_rate": 0.0, "type_issue_count": 0, "outlier_count": 0},
            {"name": "city", "missing_count": 0, "missing_rate": 0.0, "type_issue_count": 0, "outlier_count": 0},
            {"name": "service_line", "missing_count": 0, "missing_rate": 0.0, "type_issue_count": 0, "outlier_count": 0},
            {"name": "sales", "missing_count": 0, "missing_rate": 0.0, "type_issue_count": 0, "outlier_count": 0},
            {"name": "profit", "missing_count": 0, "missing_rate": 0.0, "type_issue_count": 0, "outlier_count": 0},
            {"name": "tickets", "missing_count": 0, "missing_rate": 0.0, "type_issue_count": 0, "outlier_count": 0},
        ],
        "duplicate_checks": {"full_row_duplicate_count": 0},
        "outlier_rules": ["numeric IQR rule"],
    }


def _actual_payload_for_fields(fields: list[dict]) -> dict:
    return {
        "field_level_table": fields,
        "duplicate_rules": [{"rule": "full_row_duplicate_count", "full_row_duplicate_count": 0}],
        "outlier_rules": [{"rule": "numeric IQR rule", "table": "service_metrics"}],
    }


class OracleQualityFieldCountsTest(unittest.TestCase):
    def test_clean_dataset_quality_matches_zero_field_issues(self) -> None:
        expected = _expected_clean_payload()
        actual = _actual_payload_for_fields(
            [
                {"name": "month", "missing_count": 0, "missing_rate": "0.00%", "type_issue_count": 0, "outlier_count": 0},
                {"name": "city", "missing_count": 0, "missing_rate": "0.00%", "type_issue_count": 0, "outlier_count": 0},
                {"name": "service_line", "missing_count": 0, "missing_rate": "0%", "type_issue_count": 0, "outlier_count": 0},
                {"name": "sales", "missing_count": 0, "missing_rate": 0.0, "type_issue_count": 0, "outlier_count": 0},
                {"name": "profit", "missing_count": 0, "missing_rate": 0.0, "type_issue_count": 0, "outlier_count": 0},
                {"name": "tickets", "missing_count": 0, "missing_rate": 0.0, "type_issue_count": 0, "outlier_count": 0},
            ]
        )

        result = oracle_quality_field_counts(expected, actual)

        self.assertTrue(result.passed, result.diff_summary)
        self.assertEqual([], result.issue_codes)

    def test_missing_quality_field_table_fails_with_field_level_missing(self) -> None:
        expected = _expected_clean_payload()
        actual = {
            "summary": "当前扫描结果：无字段级明细，建议查看quality_report。",
            "duplicate_rules": [{"rule": "full_row_duplicate_count", "full_row_duplicate_count": 0}],
            "outlier_rules": [{"rule": "numeric IQR rule", "table": "service_metrics"}],
        }

        result = oracle_quality_field_counts(expected, actual)

        self.assertFalse(result.passed)
        self.assertIn("quality_field_level_missing", result.issue_codes)
        self.assertEqual("Invalid actual_result payload for quality field-level oracle.", result.diff_summary)

    def test_missing_count_mismatch_is_detected(self) -> None:
        expected = _expected_clean_payload()
        expected["fields"][0]["missing_count"] = 1
        expected["fields"][0]["missing_rate"] = 0.05
        actual = _actual_payload_for_fields(
            [
                {"name": "month", "missing_count": 2, "missing_rate": "0.20", "type_issue_count": 0, "outlier_count": 0},
                {"name": "city", "missing_count": 0, "missing_rate": 0.0, "type_issue_count": 0, "outlier_count": 0},
                {"name": "service_line", "missing_count": 0, "missing_rate": 0.0, "type_issue_count": 0, "outlier_count": 0},
                {"name": "sales", "missing_count": 0, "missing_rate": 0.0, "type_issue_count": 0, "outlier_count": 0},
                {"name": "profit", "missing_count": 0, "missing_rate": 0.0, "type_issue_count": 0, "outlier_count": 0},
                {"name": "tickets", "missing_count": 0, "missing_rate": 0.0, "type_issue_count": 0, "outlier_count": 0},
            ]
        )

        result = oracle_quality_field_counts(expected, actual)

        self.assertFalse(result.passed)
        self.assertTrue(any(code == "quality_field_count_mismatch:month:missing_count" for code in result.issue_codes))


if __name__ == "__main__":
    unittest.main()
