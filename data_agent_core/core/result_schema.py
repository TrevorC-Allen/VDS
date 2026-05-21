"""Result schema helpers for normalized outputs."""

from __future__ import annotations

from typing import Any


def scalar_result(value: Any, column_name: str = "answer") -> dict[str, Any]:
    """Return a stable scalar result shape."""

    return {"columns": [column_name], "rows": [{column_name: value}], "value": value}


def table_result(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a stable table result shape."""

    columns = list(rows[0].keys()) if rows else []
    return {"columns": columns, "rows": rows, "value": rows}
