"""Execution contracts for Pandas, NumPy, SQL, and DuckDB paths."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecutionResult:
    """Standard output contract for every execution backend."""

    backend: str
    success: bool
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    value: Any = None
    summary: str = ""
    latency_ms: float | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[Any] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)
