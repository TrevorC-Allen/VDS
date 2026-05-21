"""Rule checker for verified final responses."""

from __future__ import annotations

from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.contracts.verification_contracts import ComparisonResult, VerificationResult


def verify_execution(
    primary: ExecutionResult,
    comparison: ComparisonResult | None = None,
) -> VerificationResult:
    """Verify that the primary path succeeded and optional comparison agrees."""

    issues: list[str] = []
    if not primary.success:
        issues.append("Primary execution path failed.")
    if primary.value is None:
        issues.append("Primary execution returned no value.")
    if comparison is not None and not comparison.consistent:
        issues.extend(comparison.issues)
    passed = not issues
    return VerificationResult(
        passed=passed,
        confidence=0.9 if passed else 0.0,
        pandas_sql_consistent=None if comparison is None else comparison.consistent,
        issues=issues,
        notes=["Verifier checked execution success and optional backend consistency."],
    )
