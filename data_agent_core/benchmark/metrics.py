"""Benchmark metric aggregation focused on general capability gaps."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def summarize_details(details: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate benchmark rows without creating task-specific optimization hints."""

    scored = [row for row in details if row.get("correct") is not None]
    correct = [row for row in scored if row.get("correct") is True]
    by_operation = _summarize_by_key(details, "operation")
    by_error_type = _count_key(details, "error_type")
    not_applicable_counts = _count_key([row for row in details if row.get("not_applicable_category")], "not_applicable_category")
    return {
        "total": len(details),
        "scored": len(scored),
        "correct": len(correct),
        "accuracy": None if not scored else len(correct) / len(scored),
        "success_count": sum(1 for row in details if row.get("success")),
        "unexpected_not_applicable": not_applicable_counts.get("capability_gap", 0),
        "true_unsupported": not_applicable_counts.get("true_unsupported", 0),
        "not_applicable_counts": not_applicable_counts,
        "operation_metrics": by_operation,
        "error_type_counts": by_error_type,
    }


def _summarize_by_key(details: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in details:
        groups[str(row.get(key) or "unknown")].append(row)
    return {name: summarize_details(rows) for name, rows in groups.items() if len(rows) != len(details)}


def _count_key(details: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts = Counter(str(row.get(key) or "none") for row in details)
    return dict(sorted(counts.items()))
