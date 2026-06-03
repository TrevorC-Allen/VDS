"""Deterministic oracle result contracts for eval instrumentation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.task_execution_contracts import TaskExecutionContract


@dataclass
class OracleResult:
    """Deterministic expected-vs-actual result for contract-aware eval."""

    oracle_available: bool
    expected_result: dict[str, Any] | list[Any] | None = None
    actual_result: dict[str, Any] | list[Any] | None = None
    passed: bool | None = None
    diff_summary: str | None = None
    issue_codes: list[str] = field(default_factory=list)


def build_oracle_result(
    contract: TaskExecutionContract | None,
    execution_result: ExecutionResult,
) -> OracleResult:
    """Build an oracle result when deterministic expected_result is available."""

    actual = _actual_payload(execution_result)
    if contract is None:
        return OracleResult(
            oracle_available=False,
            actual_result=actual,
            passed=None,
            diff_summary="No task contract is available for deterministic oracle evaluation.",
            issue_codes=["oracle_contract_missing"],
        )
    expected = contract.verification_rules.get("expected_result")
    if expected is None:
        return OracleResult(
            oracle_available=False,
            actual_result=actual,
            passed=None,
            diff_summary="No deterministic expected_result is defined for this contract.",
            issue_codes=["oracle_expected_result_missing"],
        )
    passed = expected == actual
    return OracleResult(
        oracle_available=True,
        expected_result=expected,
        actual_result=actual,
        passed=passed,
        diff_summary=None if passed else "Deterministic actual_result differs from expected_result.",
        issue_codes=[] if passed else ["oracle_result_mismatch"],
    )


def _actual_payload(execution_result: ExecutionResult) -> dict[str, Any] | list[Any] | None:
    if execution_result.rows:
        return execution_result.rows
    if isinstance(execution_result.value, (dict, list)):
        return execution_result.value
    if execution_result.value is None:
        return None
    return {"value": execution_result.value}
