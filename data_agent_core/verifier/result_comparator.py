"""Result comparator for execution outputs."""

from __future__ import annotations

from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.contracts.verification_contracts import ComparisonResult
from data_agent_core.verifier.result_normalizer import normalize_value


def compare_results(left: ExecutionResult, right: ExecutionResult) -> ComparisonResult:
    """Compare two execution results after normalization."""

    issues: list[str] = []
    if not left.success or not right.success:
        issues.append("One or both execution paths failed.")
        return ComparisonResult(False, False, False, False, issues)

    left_value = normalize_value(left.value)
    right_value = normalize_value(right.value)
    if isinstance(left_value, dict) and isinstance(right_value, dict):
        if left_value.get("answer") is not None and left_value.get("answer") == right_value.get("answer"):
            return ComparisonResult(
                consistent=True,
                column_match=True,
                row_match=True,
                value_match=True,
                issues=[],
            )
    value_match = left_value == right_value
    if not value_match:
        issues.append("Execution values differ after normalization.")
    return ComparisonResult(
        consistent=value_match,
        column_match=True,
        row_match=True,
        value_match=value_match,
        issues=issues,
    )
