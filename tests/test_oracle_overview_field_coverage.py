from __future__ import annotations

import unittest

from data_agent_core.oracle_results import (
    oracle_multi_file_dataset_overview,
    oracle_overview_schema_field_coverage,
)


class OracleOverviewFieldCoverageTest(unittest.TestCase):
    def test_single_table_overview_oracle_covers_required_fields(self) -> None:
        expected = {
            "tables": [
                {
                    "name": "service_metrics",
                    "fields": [
                        {"name": "month", "role": "time"},
                        {"name": "city", "role": "dimension"},
                        {"name": "service_line", "role": "dimension"},
                        {"name": "sales", "role": "metric"},
                        {"name": "profit", "role": "metric"},
                        {"name": "tickets", "role": "metric"},
                    ],
                    "required_fields": ["month", "city", "service_line", "sales", "profit", "tickets"],
                }
            ],
            "required_fields": ["month", "city", "service_line", "sales", "profit", "tickets"],
            "metric_candidates": ["sales", "profit", "tickets"],
            "dimension_candidates": ["city", "service_line"],
            "time_columns": ["month"],
            "analysis_directions": ["month, city, service_line, sales, profit, tickets"],
        }
        actual = {
            "tables": [
                {
                    "name": "service_metrics",
                    "fields": [
                        {"name": "month", "role": "time", "type": "datetime"},
                        {"name": "city", "role": "dimension", "type": "string"},
                        {"name": "service_line", "role": "dimension", "type": "string"},
                        {"name": "sales", "role": "metric", "type": "float"},
                        {"name": "profit", "role": "metric", "type": "float"},
                        {"name": "tickets", "role": "metric", "type": "int"},
                    ],
                }
            ],
            "metric_candidates": ["sales", "profit", "tickets"],
            "dimension_candidates": ["city", "service_line"],
            "time_columns": ["month"],
            "analysis_directions": ["可按month看趋势，city和service_line用于维度切片，销售看sales/profit/tickets。"],
        }
        result = oracle_overview_schema_field_coverage(expected, actual)

        self.assertTrue(result.passed)
        self.assertEqual([], result.issue_codes)
        self.assertEqual(expected["tables"][0]["name"], result.expected_result["tables"][0]["name"])

    def test_multi_table_overview_oracle_checks_join_keys_and_required_fields(self) -> None:
        expected = {
            "tables": [
                {
                    "name": "orders",
                    "fields": [
                        {"name": "month", "role": "time"},
                        {"name": "amount", "role": "metric"},
                        {"name": "profit", "role": "metric"},
                        {"name": "customer_id", "role": "dimension"},
                    ],
                    "required_fields": ["month", "amount", "profit", "customer_id"],
                },
                {
                    "name": "customers",
                    "fields": [
                        {"name": "city", "role": "dimension"},
                        {"name": "segment", "role": "dimension"},
                        {"name": "customer_id", "role": "dimension"},
                    ],
                    "required_fields": ["city", "segment", "customer_id"],
                },
            ],
            "join_keys": [
                {"left": "orders.customer_id", "right": "customers.customer_id"},
            ],
            "metric_candidates": ["amount", "profit"],
            "dimension_candidates": ["city", "segment"],
            "time_columns": ["month"],
            "analysis_directions": [
                "按month查看趋势，customer_id关联orders和customers后可比较city与segment下的amount/profit。",
            ],
        }
        actual = {
            "tables": [
                {
                    "name": "orders",
                    "fields": [
                        {"name": "month", "role": "time", "type": "string"},
                        {"name": "amount", "role": "metric", "type": "float"},
                        {"name": "profit", "role": "metric", "type": "float"},
                        {"name": "customer_id", "role": "dimension", "type": "string"},
                    ],
                },
                {
                    "name": "customers",
                    "fields": [
                        {"name": "city", "role": "dimension", "type": "string"},
                        {"name": "segment", "role": "dimension", "type": "string"},
                        {"name": "customer_id", "role": "dimension", "type": "string"},
                    ],
                },
            ],
            "join_keys": [{"left": "orders.customer_id", "right": "customers.customer_id"}],
            "metric_candidates": ["amount", "profit"],
            "dimension_candidates": ["city", "segment"],
            "time_columns": ["month"],
            "analysis_directions": ["按month看订单金额和利润，结合城市和客群分层。"],
        }
        result = oracle_multi_file_dataset_overview(expected, actual)

        self.assertTrue(result.passed)
        self.assertEqual([], result.issue_codes)

    def test_missing_field_returns_required_field_missing_code(self) -> None:
        expected = {
            "tables": [
                {
                    "name": "service_metrics",
                    "fields": [
                        {"name": "month", "role": "time"},
                        {"name": "city", "role": "dimension"},
                        {"name": "service_line", "role": "dimension"},
                        {"name": "sales", "role": "metric"},
                        {"name": "profit", "role": "metric"},
                        {"name": "tickets", "role": "metric"},
                    ],
                    "required_fields": ["month", "city", "service_line", "sales", "profit", "tickets"],
                }
            ],
            "required_fields": ["month", "city", "service_line", "sales", "profit", "tickets"],
            "metric_candidates": ["sales", "profit", "tickets"],
            "dimension_candidates": ["city", "service_line"],
            "time_columns": ["month"],
            "analysis_directions": ["month, city, service_line, sales, profit, tickets"],
        }
        actual = {
            "tables": [
                {
                    "name": "service_metrics",
                    "fields": [
                        {"name": "month", "role": "time", "type": "datetime"},
                        {"name": "city", "role": "dimension", "type": "string"},
                        {"name": "service_line", "role": "dimension", "type": "string"},
                        {"name": "sales", "role": "metric", "type": "float"},
                        {"name": "tickets", "role": "metric", "type": "int"},
                    ],
                }
            ],
            "metric_candidates": ["sales", "tickets"],
            "dimension_candidates": ["city", "service_line"],
            "time_columns": ["month"],
            "analysis_directions": ["month, city, service_line, sales, tickets"],
        }
        result = oracle_overview_schema_field_coverage(expected, actual)

        self.assertFalse(result.passed)
        self.assertTrue(any(code.startswith("overview_required_field_missing") for code in result.issue_codes))


if __name__ == "__main__":
    unittest.main()
