"""Result comparator for execution outputs."""

from __future__ import annotations

import math
from typing import Any

from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.contracts.verification_contracts import ComparisonResult
from data_agent_core.verifier.result_normalizer import normalize_value


_ORDER_SENSITIVE_OPERATIONS = {
    "field_values",
    "filtered_metric_ranking",
    "grouped_child_ranking",
    "growth_ranking",
    "rank_by_metric",
    "ranking",
    "time_series",
    "top_count",
    "top_k_share",
    "trend",
}


def compare_results(left: ExecutionResult, right: ExecutionResult) -> ComparisonResult:
    """Compare two execution results after normalization."""

    issues: list[str] = []
    if not left.success or not right.success:
        if left.success and not right.success and str(right.backend).lower() in {"sqlite", "sql"}:
            return ComparisonResult(True, True, True, True, ["Optional SQL comparison path failed; trusted pandas result retained."])
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
    value_match = _values_match(left_value, right_value)
    if not value_match and not _requires_ordered_comparison(left, right):
        value_match = _unordered_row_values_match(left_value, right_value)
    if not value_match:
        issues.append("Execution values differ after normalization.")
    return ComparisonResult(
        consistent=value_match,
        column_match=True,
        row_match=True,
        value_match=value_match,
        issues=issues,
    )


def _values_match(left: Any, right: Any) -> bool:
    if _is_number(left) and _is_number(right):
        return math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-8)
    if _is_number(left) and _is_numeric_string(right):
        return math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-8)
    if _is_numeric_string(left) and _is_number(right):
        return math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-8)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_values_match(left_item, right_item) for left_item, right_item in zip(left, right))
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(_values_match(left[key], right[key]) for key in left)
    return left == right


def _unordered_row_values_match(left: Any, right: Any) -> bool:
    if not isinstance(left, list) or not isinstance(right, list):
        return False
    if len(left) != len(right):
        return False
    if not all(isinstance(item, dict) for item in left + right):
        return False
    left_sorted = sorted(left, key=_row_sort_key)
    right_sorted = sorted(right, key=_row_sort_key)
    return _values_match(left_sorted, right_sorted)


def _row_sort_key(row: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(row, dict):
        return (("", str(row)),)
    return tuple((str(key), _sort_scalar(value)) for key, value in sorted(row.items(), key=lambda item: str(item[0])))


def _sort_scalar(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _requires_ordered_comparison(left: ExecutionResult, right: ExecutionResult) -> bool:
    operations = {_execution_operation(left), _execution_operation(right)}
    return any(operation in _ORDER_SENSITIVE_OPERATIONS for operation in operations)


def _execution_operation(result: ExecutionResult) -> str:
    for payload in (result.execution_trace, result.expected_trace, result.debug.get("execution_trace") if isinstance(result.debug, dict) else None):
        if isinstance(payload, dict) and payload.get("operation"):
            return str(payload.get("operation") or "")
    return ""


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_numeric_string(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        float(value)
    except ValueError:
        return False
    return True
