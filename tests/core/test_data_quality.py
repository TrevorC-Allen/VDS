"""Tests for trace-safe data quality scanning."""

from __future__ import annotations

import unittest

import pandas as pd

from data_agent_core.core.data_quality import build_data_quality_report


class DataQualityTest(unittest.TestCase):
    def test_boolean_columns_do_not_enter_numeric_outlier_scan(self) -> None:
        report = build_data_quality_report(
            {
                "payments": pd.DataFrame(
                    {
                        "has_fraudulent_dispute": [True, False, True, False, True, False, True, False],
                        "is_credit": ["true", "false", "true", "false", "true", "false", "true", "false"],
                    }
                )
            }
        )

        self.assertEqual("scanned", report.status)
        self.assertFalse(any(issue.issue_type == "numeric_outliers" for issue in report.issues))

    def test_negative_numeric_samples_align_after_missing_values(self) -> None:
        report = build_data_quality_report(
            {
                "orders": pd.DataFrame(
                    {
                        "sales_amount": [10, None, 20, "", 30, -5, 40, 50, 60, 70, 80, 90],
                    }
                )
            }
        )

        negative_issues = [issue for issue in report.issues if issue.issue_type == "suspicious_negative_values"]
        self.assertEqual(1, len(negative_issues))
        self.assertEqual([-5], negative_issues[0].sample_values)


if __name__ == "__main__":
    unittest.main()
