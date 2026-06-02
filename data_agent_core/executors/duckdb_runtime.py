"""Read-only DuckDB runtime boundary for temporary analytical SQL execution."""

from __future__ import annotations

import importlib.util
import re
import time
from typing import Any


class DuckDBRuntimeUnavailable(RuntimeError):
    """Raised when DuckDB is not installed in the active runtime."""


class DuckDBReadOnlyViolation(ValueError):
    """Raised when a query violates the read-only SQL boundary."""


_TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FORBIDDEN_SQL_PATTERN = re.compile(
    r"\b("
    r"attach|call|copy|create|delete|detach|drop|export|import|insert|install|load|merge|pragma|replace|"
    r"set|truncate|update|vacuum|read_csv|read_json|read_parquet|read_text"
    r")\b",
    re.IGNORECASE,
)


def is_duckdb_available() -> bool:
    """Return whether the optional DuckDB package can be imported."""

    return importlib.util.find_spec("duckdb") is not None


def validate_readonly_query(sql: str) -> str:
    """Validate one read-only SELECT / CTE statement and return normalized SQL."""

    query = sql.strip()
    if not query:
        raise DuckDBReadOnlyViolation("DuckDB query must not be empty.")
    query = query[:-1].strip() if query.endswith(";") else query
    if ";" in query:
        raise DuckDBReadOnlyViolation("DuckDB runtime accepts exactly one SQL statement.")
    lowered = query.lower()
    if not (lowered.startswith("select ") or lowered.startswith("with ")):
        raise DuckDBReadOnlyViolation("DuckDB runtime only accepts SELECT or WITH queries.")
    if _FORBIDDEN_SQL_PATTERN.search(query):
        raise DuckDBReadOnlyViolation("DuckDB runtime rejected a non-read-only keyword or external read function.")
    if "://" in query:
        raise DuckDBReadOnlyViolation("DuckDB runtime does not allow external URLs.")
    return query


def execute_readonly_query(tables: dict[str, Any], sql: str, *, row_limit: int | None = 1000) -> dict[str, Any]:
    """Execute a validated read-only query against registered in-memory tables."""

    query = validate_readonly_query(sql)
    if not is_duckdb_available():
        raise DuckDBRuntimeUnavailable("DuckDB is not installed in this runtime; keep sqlite fallback active.")
    if not tables:
        raise ValueError("At least one DataFrame table is required for DuckDB execution.")

    import duckdb  # type: ignore[import-not-found]

    start = time.perf_counter()
    conn = duckdb.connect(database=":memory:")
    try:
        for table_name, frame in tables.items():
            _validate_table_name(str(table_name))
            conn.register(str(table_name), frame)
        limited_query = _limit_query(query, row_limit)
        result_frame = conn.execute(limited_query).fetchdf()
        rows = result_frame.to_dict(orient="records")
        return {
            "backend": "duckdb",
            "success": True,
            "columns": [str(column) for column in result_frame.columns],
            "rows": rows,
            "value": rows,
            "row_count": len(rows),
            "read_only": True,
            "latency_ms": (time.perf_counter() - start) * 1000,
        }
    finally:
        conn.close()


def _validate_table_name(name: str) -> None:
    if not _TABLE_NAME_PATTERN.match(name):
        raise ValueError(f"Unsafe DuckDB table name: {name}")


def _limit_query(query: str, row_limit: int | None) -> str:
    if row_limit is None:
        return query
    if row_limit <= 0:
        raise ValueError("row_limit must be positive when provided.")
    return f"SELECT * FROM ({query}) AS readonly_result LIMIT {int(row_limit)}"
