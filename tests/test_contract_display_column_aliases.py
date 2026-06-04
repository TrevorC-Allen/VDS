from __future__ import annotations

import unittest

from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.task_execution_contracts import TaskExecutionContract, verify_task_execution_contract


class ContractDisplayColumnAliasesTest(unittest.TestCase):
    def _assert_no_missing_columns(self, contract: TaskExecutionContract, execution_result: ExecutionResult) -> None:
        report = verify_task_execution_contract(contract, execution_result)
        self.assertTrue(report.passed)
        self.assertNotIn(
            "required_output_column_missing",
            [violation.code for violation in report.violations],
        )

    def _assert_missing_columns(self, contract: TaskExecutionContract, execution_result: ExecutionResult, expected: list[str]) -> None:
        report = verify_task_execution_contract(contract, execution_result)
        self.assertFalse(report.passed)
        missing_codes = [violation.code for violation in report.violations]
        self.assertIn("required_output_column_missing", missing_codes)
        self.assertIn(
            expected,
            [violation.metadata.get("missing_columns") for violation in report.violations if violation.code == "required_output_column_missing"],
        )

    def test_required_output_columns_aliases_pass(self) -> None:
        contract = TaskExecutionContract(
            contract_id="contract_required_output_alias_pass",
            task_family="topn",
            required_output_columns=["cust_name", "sign_amt", "sku_name"],
        )
        execution_result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["客户", "分销金额", "SKU"],
            rows=[{"客户": "广东", "分销金额": 12, "SKU": "sku-1"}],
            value=[{"客户": "广东", "分销金额": 12, "SKU": "sku-1"}],
        )
        self._assert_no_missing_columns(contract, execution_result)

    def test_retail_metric_alias_passes(self) -> None:
        contract = TaskExecutionContract(contract_id="contract_retail_metric_alias_pass", task_family="topn", required_output_columns=["sign_box_cnt"])
        execution_result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["业代", "签收箱数"],
            rows=[{"业代": "Alice", "签收箱数": 4}],
            value=[{"业代": "Alice", "签收箱数": 4}],
        )
        self._assert_no_missing_columns(contract, execution_result)

    def test_real_missing_columns_still_fail(self) -> None:
        contract = TaskExecutionContract(
            contract_id="contract_real_missing_column_fails",
            task_family="topn",
            required_output_columns=["sign_amt", "sku_name"],
        )
        execution_result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["客户", "分销金额"],
            rows=[{"客户": "广东", "分销金额": 12}],
            value=[{"客户": "广东", "分销金额": 12}],
        )
        self._assert_missing_columns(contract, execution_result, ["sku_name"])

    def test_display_alias_case_space_compat(self) -> None:
        contract = TaskExecutionContract(contract_id="contract_display_alias_case_space", task_family="topn", required_output_columns=["sku_name"])
        execution_result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=[" SKU "],
            rows=[{" SKU ": "sku-1"}],
            value=[{" SKU ": "sku-1"}],
        )
        self._assert_no_missing_columns(contract, execution_result)


if __name__ == "__main__":
    unittest.main()
