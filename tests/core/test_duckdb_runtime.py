"""Tests for the Phase 7.7 DuckDB read-only runtime boundary."""

from __future__ import annotations

import unittest

import pandas as pd

from data_agent_core.executors.duckdb_runtime import (
    DuckDBReadOnlyViolation,
    DuckDBRuntimeUnavailable,
    execute_readonly_query,
    is_duckdb_available,
    validate_readonly_query,
)


class DuckDBRuntimeTest(unittest.TestCase):
    def test_validate_readonly_query_accepts_select_and_cte(self) -> None:
        self.assertEqual("SELECT city, SUM(sales) FROM sales GROUP BY city", validate_readonly_query("SELECT city, SUM(sales) FROM sales GROUP BY city;"))
        self.assertEqual(
            "WITH ranked AS (SELECT * FROM sales) SELECT * FROM ranked",
            validate_readonly_query("WITH ranked AS (SELECT * FROM sales) SELECT * FROM ranked"),
        )

    def test_validate_readonly_query_rejects_mutation_and_external_reads(self) -> None:
        for sql in (
            "SELECT * FROM sales; DROP TABLE sales",
            "DELETE FROM sales",
            "COPY sales TO '/tmp/out.csv'",
            "SELECT * FROM read_csv('file.csv')",
            "SELECT * FROM 'https://example.test/data.parquet'",
        ):
            with self.subTest(sql=sql):
                with self.assertRaises(DuckDBReadOnlyViolation):
                    validate_readonly_query(sql)

    def test_execute_readonly_query_runs_or_reports_unavailable(self) -> None:
        tables = {"sales": pd.DataFrame([{"city": "上海", "sales": 100}, {"city": "北京", "sales": 80}])}
        if not is_duckdb_available():
            with self.assertRaises(DuckDBRuntimeUnavailable):
                execute_readonly_query(tables, "SELECT city, sales FROM sales ORDER BY sales DESC")
            return

        result = execute_readonly_query(tables, "SELECT city, sales FROM sales ORDER BY sales DESC")
        self.assertTrue(result["success"])
        self.assertEqual("duckdb", result["backend"])
        self.assertEqual("上海", result["rows"][0]["city"])

    def test_execute_readonly_query_rejects_unsafe_table_names_before_registration(self) -> None:
        if not is_duckdb_available():
            self.skipTest("DuckDB package is not installed in this runtime.")
        with self.assertRaises(ValueError):
            execute_readonly_query({"sales;drop": pd.DataFrame([{"x": 1}])}, "SELECT * FROM sales")


if __name__ == "__main__":
    unittest.main()
