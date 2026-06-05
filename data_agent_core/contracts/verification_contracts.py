"""Verification contracts for result comparison and correction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ComparisonResult:
    """Comparison output for two normalized execution results."""

    consistent: bool
    column_match: bool = True
    row_match: bool = True
    value_match: bool = True
    issues: list[str] = field(default_factory=list)


@dataclass
class VerificationResult:
    """Verifier output used before building a final response."""

    passed: bool
    confidence: float = 0.0
    pandas_sql_consistent: bool | None = None
    semantic_passed: bool | None = None
    issues: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    semantic_verification_notes: list[str] = field(default_factory=list)
    semantic_issues: list[dict[str, Any]] = field(default_factory=list)
    correction_action: dict[str, Any] | None = None
    task_contract: dict[str, Any] | None = None
    contract_report: dict[str, Any] | None = None
    oracle_result: dict[str, Any] | None = None
    semantic_status: str = "legacy_unverified"


@dataclass
class CorrectionResult:
    """Correction-loop summary with bounded attempts."""

    attempted: bool = False
    attempt_count: int = 0
    success: bool = False
    fixed_issues: list[str] = field(default_factory=list)
    errors: list[Any] = field(default_factory=list)
