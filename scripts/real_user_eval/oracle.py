"""Independent oracle execution for real-user VDS evaluation."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

try:
    import duckdb
except ImportError as exc:  # pragma: no cover - environment dependent.
    raise SystemExit("duckdb is required. Use the Codex bundled Python or install duckdb.") from exc

from scripts.run_generic_dataset_eval import TableRef, load_tables


def evaluate_oracle(
    *,
    oracle_type: str,
    oracle_query_or_formula: Any,
    file_paths: list[Path],
    table_names: list[str] | None = None,
) -> dict[str, Any]:
    normalized = str(oracle_type or "").strip().lower()
    if normalized == "none":
        return {"oracle_type": "none", "answer": "", "rows": [], "columns": []}
    if normalized == "literal":
        return {
            "oracle_type": "literal",
            "answer": _json_text(oracle_query_or_formula),
            "rows": [],
            "columns": [],
            "value": oracle_query_or_formula,
        }
    if normalized != "duckdb_sql":
        raise ValueError(f"unsupported oracle_type: {oracle_type}")
    if not file_paths:
        raise ValueError("duckdb_sql oracle requires dataset files")
    con = duckdb.connect(database=":memory:")
    try:
        tables = load_tables(con, file_paths, table_names or [])
        sql = render_oracle_sql(str(oracle_query_or_formula or ""), tables)
        if not sql.strip():
            raise ValueError("duckdb_sql oracle query must not be empty")
        result = con.execute(sql)
        columns = [item[0] for item in result.description or []]
        rows = [_row_to_dict(columns, row) for row in result.fetchall()]
        return {
            "oracle_type": "duckdb_sql",
            "query": sql,
            "answer": oracle_answer_text(rows, columns),
            "rows": rows,
            "columns": columns,
            "table_views": {table.table_name: table.view_name for table in tables},
        }
    finally:
        con.close()


def render_oracle_sql(sql: str, tables: list[TableRef]) -> str:
    by_name = {table.table_name: table.view_name for table in tables}

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key.startswith("table_"):
            index = int(key.removeprefix("table_"))
            if 0 <= index < len(tables):
                return tables[index].view_name
        if key.startswith("table:"):
            table_name = key.split(":", 1)[1]
            if table_name in by_name:
                return by_name[table_name]
        raise ValueError(f"unknown oracle table placeholder {{{key}}}")

    return re.sub(r"\{([^{}]+)\}", replace, sql)


def oracle_answer_text(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return "direct_computation_result: no rows"
    if len(rows) == 1 and len(columns) == 1:
        return f"direct_computation_result: {columns[0]}={rows[0].get(columns[0])}"
    return "direct_computation_result: " + json.dumps(rows[:20], ensure_ascii=False, default=str)


def _row_to_dict(columns: list[str], row: tuple[Any, ...]) -> dict[str, Any]:
    return {column: _json_ready(value) for column, value in zip(columns, row, strict=False)}


def _json_ready(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)
