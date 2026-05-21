"""Dataset contracts for file, table, and column profiles."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ColumnProfile:
    """Stable column profile exchanged by parser and profiler modules."""

    name: str
    inferred_type: str
    missing_rate: float = 0.0
    unique_count: int = 0
    sample_values: list[Any] = field(default_factory=list)
    semantic_hints: list[str] = field(default_factory=list)


@dataclass
class TableProfile:
    """Stable table profile for one CSV file or Excel sheet."""

    table_name: str
    row_count: int
    column_count: int
    columns: list[ColumnProfile] = field(default_factory=list)


@dataclass
class DatasetProfile:
    """Stable dataset profile returned by file parsing and profiling."""

    dataset_id: str
    file_name: str
    status: str
    tables: list[TableProfile] = field(default_factory=list)
    created_at: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[Any] = field(default_factory=list)
