"""SQL executor for backend-neutral plans.

DuckDB is the preferred future runtime. The current MVP uses the Python
standard-library sqlite3 fallback when DuckDB is unavailable.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any

from data_agent_core.contracts.analysis_contracts import AnalysisPlan
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.errors.error_result import ErrorResult
from data_agent_core.errors.error_types import SQL_EXECUTION_ERROR


def execute_plan(plan: AnalysisPlan, context: dict[str, Any]) -> ExecutionResult:
    """Execute SQL-compatible operations using sqlite fallback."""

    start = time.perf_counter()
    try:
        value = _execute_value(plan, context)
        return ExecutionResult(
            backend="sqlite",
            success=True,
            columns=["answer"],
            rows=[{"answer": value}],
            value=value,
            summary=f"Executed SQL-compatible operation {plan.logic_form.operation}.",
            latency_ms=(time.perf_counter() - start) * 1000,
        )
    except Exception as exc:  # noqa: BLE001
        return ExecutionResult(
            backend="sqlite",
            success=False,
            latency_ms=(time.perf_counter() - start) * 1000,
            errors=[
                ErrorResult(
                    error_type=SQL_EXECUTION_ERROR,
                    error_message=str(exc),
                    failed_step=plan.logic_form.operation,
                    recoverable=True,
                    suggested_fix="Use the Pandas path for non-SQL rule-engine operations or inspect SQL translation.",
                )
            ],
        )


def _execute_value(plan: AnalysisPlan, context: dict[str, Any]) -> Any:
    op = plan.logic_form.operation
    if op not in {"top_count", "group_average", "not_applicable"}:
        raise ValueError(f"Operation {op} is not SQL-compatible in the MVP.")
    if op == "not_applicable":
        return "Not Applicable"

    df = context["payments"]
    conn = sqlite3.connect(":memory:")
    try:
        df.to_sql("payments", conn, index=False)
        if op == "top_count":
            return _top_count_sql(conn, plan)
        if op == "group_average":
            return _group_average_sql(conn, plan)
    finally:
        conn.close()
    raise ValueError(f"Unsupported operation: {op}")


def _top_count_sql(conn: sqlite3.Connection, plan: AnalysisPlan) -> Any:
    params = plan.logic_form.parameters
    filters = plan.logic_form.filters
    where = []
    values: list[Any] = []
    for column, expected in filters.items():
        if expected is not None:
            where.append(f"{column} = ?")
            values.append(expected)
    where_sql = " WHERE " + " AND ".join(where) if where else ""
    group_by = params["group_by"]
    sql = f"SELECT {group_by}, COUNT(*) AS n FROM payments{where_sql} GROUP BY {group_by} ORDER BY n DESC LIMIT 1"
    row = conn.execute(sql, values).fetchone()
    if row is None:
        return "Not Applicable"
    top_value = str(row[0])
    options = params.get("options") or {}
    for letter, option_value in options.items():
        if option_value == top_value:
            return f"{letter}. {top_value}"
    return top_value


def _group_average_sql(conn: sqlite3.Connection, plan: AnalysisPlan) -> list[dict[str, Any]]:
    filters = plan.logic_form.filters
    params = plan.logic_form.parameters
    where = []
    values: list[Any] = []
    if filters.get("merchant"):
        where.append("merchant = ?")
        values.append(filters["merchant"])
    if filters.get("card_scheme"):
        where.append("card_scheme = ?")
        values.append(filters["card_scheme"])
    if filters.get("year"):
        where.append("year = ?")
        values.append(int(filters["year"]))
    if filters.get("month_range"):
        start, end = filters["month_range"]
        where.append("CAST(strftime('%m', date(year || '-01-01', '+' || (day_of_year - 1) || ' days')) AS INTEGER) BETWEEN ? AND ?")
        values.extend([start, end])
    where_sql = " WHERE " + " AND ".join(where) if where else ""
    group_by = params["group_by"]
    metric = params["metric"]
    rows = conn.execute(
        f"SELECT {group_by}, AVG({metric}) AS {metric} FROM payments{where_sql} GROUP BY {group_by} ORDER BY {metric} ASC",
        values,
    ).fetchall()
    return [{group_by: row[0], metric: row[1]} for row in rows]
