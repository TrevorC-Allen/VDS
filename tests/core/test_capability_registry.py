"""Tests for operation-level capability metadata and SQL coverage boundaries."""

from __future__ import annotations

import unittest

from data_agent_core.contracts.analysis_contracts import LogicForm
from data_agent_core.core.capability_registry import (
    SQL_SUPPORT_NATIVE,
    SQL_SUPPORT_SHARED_RULE_ENGINE,
    SQL_SUPPORT_UNSUPPORTED,
    capability_for_operation,
    coverage_summary_for_logic_form,
    is_native_sql_operation,
)


class CapabilityRegistryTest(unittest.TestCase):
    def test_native_sql_operation_has_capability_family(self) -> None:
        metadata = capability_for_operation("row_count")

        self.assertEqual("counting", metadata.capability_family)
        self.assertTrue(metadata.supports_pandas)
        self.assertEqual(SQL_SUPPORT_NATIVE, metadata.sql_support)
        self.assertTrue(metadata.supports_chinese)
        self.assertTrue(is_native_sql_operation("row_count"))

    def test_fee_rule_operations_are_shared_rule_engine_not_native_sql(self) -> None:
        metadata = capability_for_operation("best_fraud_aci_choice")

        self.assertEqual("business_rule_what_if", metadata.capability_family)
        self.assertEqual(SQL_SUPPORT_SHARED_RULE_ENGINE, metadata.sql_support)
        self.assertTrue(metadata.requires_rule_context)
        self.assertFalse(is_native_sql_operation("best_fraud_aci_choice"))

    def test_unknown_operation_is_unsupported(self) -> None:
        metadata = capability_for_operation("new_future_operation")

        self.assertEqual("unknown", metadata.capability_family)
        self.assertEqual(SQL_SUPPORT_UNSUPPORTED, metadata.sql_support)
        self.assertFalse(metadata.supports_pandas)

    def test_field_values_native_sql_boundary_requires_table_column(self) -> None:
        logic = LogicForm(
            task_type="schema_query",
            operation="field_values",
            parameters={"table": "payments", "field": "merchant"},
        )

        covered = coverage_summary_for_logic_form(logic, available_columns=["merchant", "amount"])
        gap = coverage_summary_for_logic_form(logic, available_columns=["amount"])

        self.assertTrue(covered["native_sql_supported"])
        self.assertFalse(covered["coverage_gap"])
        self.assertFalse(gap["native_sql_supported"])
        self.assertTrue(gap["coverage_gap"])


if __name__ == "__main__":
    unittest.main()
