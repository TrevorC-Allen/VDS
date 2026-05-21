"""Benchmark error analysis focused on reusable capability gaps."""

from __future__ import annotations

from collections import Counter
from typing import Any


def summarize_failures(details: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize failed rows by operation/error type without per-task fixes."""

    failures = [row for row in details if row.get("correct") is False or row.get("success") is False]
    operation_counts = Counter(str(row.get("operation") or "unknown") for row in failures)
    error_type_counts = Counter(str(row.get("error_type") or "none") for row in failures)
    return {
        "failure_count": len(failures),
        "by_operation": dict(sorted(operation_counts.items())),
        "by_error_type": dict(sorted(error_type_counts.items())),
        "general_gap_notes": _general_gap_notes(operation_counts, error_type_counts),
    }


def _general_gap_notes(operation_counts: Counter[str], error_type_counts: Counter[str]) -> list[str]:
    notes: list[str] = []
    for operation, count in operation_counts.most_common():
        notes.append(f"Review general {operation} handling across parser, planner, executors, and verifier. failures={count}")
    for error_type, count in error_type_counts.most_common():
        if error_type != "none":
            notes.append(f"Review modules producing {error_type}. failures={count}")
    return notes
