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
        columns, rows = _result_rows(value)
        return ExecutionResult(
            backend="sqlite",
            success=True,
            columns=columns,
            rows=rows,
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
    if op not in {"top_count", "group_average", "not_applicable", "aggregation", "ranking", "rank_by_metric"}:
        raise ValueError(f"Operation {op} is not SQL-compatible in the MVP.")
    if op == "not_applicable":
        return "Not Applicable"

    df = context["payments"] if "payments" in context else _table(context["tables"], plan.logic_form.parameters.get("table"))
    conn = sqlite3.connect(":memory:")
    try:
        df.to_sql("analysis_table", conn, index=False)
        if op == "top_count":
            return _top_count_sql(conn, plan)
        if op == "group_average":
            return _group_average_sql(conn, plan)
        if op == "aggregation":
            return _aggregation_sql(conn, plan)
        if op == "ranking":
            return _ranking_sql(conn, plan)
        if op == "rank_by_metric":
            return _rank_by_metric_sql(conn, plan)
    finally:
        conn.close()
    raise ValueError(f"Unsupported operation: {op}")


def _result_rows(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    if isinstance(value, list) and all(isinstance(row, dict) for row in value):
        columns: list[str] = []
        for row in value:
            for key in row:
                if key not in columns:
                    columns.append(str(key))
        return columns, value
    if isinstance(value, dict):
        return list(value.keys()), [value]
    return ["answer"], [{"answer": value}]


def _table(tables: dict[str, Any], name: str | None = None) -> Any:
    if name and name in tables:
        return tables[name]
    if not tables:
        raise ValueError("No tables available for SQL execution.")
    return max(tables.values(), key=lambda df: (len(df), len(df.columns)))


def _top_count_sql(conn: sqlite3.Connection, plan: AnalysisPlan) -> Any:
    params = plan.logic_form.parameters
    filters = plan.logic_form.filters
    where = []
    values: list[Any] = []
    for column, expected in filters.items():
        if expected is not None:
            where.append(f"{_quote_identifier(str(column))} = ?")
            values.append(expected)
    where_sql = " WHERE " + " AND ".join(where) if where else ""
    group_by = params["group_by"]
    q_group_by = _quote_identifier(group_by)
    sql = f"SELECT {q_group_by}, COUNT(*) AS n FROM analysis_table{where_sql} GROUP BY {q_group_by} ORDER BY n DESC LIMIT 1"
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
        where.append(f"{_quote_identifier('merchant')} = ?")
        values.append(filters["merchant"])
    if filters.get("card_scheme"):
        where.append(f"{_quote_identifier('card_scheme')} = ?")
        values.append(filters["card_scheme"])
    if filters.get("year"):
        where.append(f"{_quote_identifier('year')} = ?")
        values.append(int(filters["year"]))
    if filters.get("month_range"):
        start, end = filters["month_range"]
        where.append("CAST(strftime('%m', date(year || '-01-01', '+' || (day_of_year - 1) || ' days')) AS INTEGER) BETWEEN ? AND ?")
        values.extend([start, end])
    where_sql = " WHERE " + " AND ".join(where) if where else ""
    group_by = params["group_by"]
    metric = params["metric"]
    rows = conn.execute(
        f"SELECT {_quote_identifier(group_by)}, AVG({_quote_identifier(metric)}) AS {_quote_identifier(metric)} "
        f"FROM analysis_table{where_sql} GROUP BY {_quote_identifier(group_by)} ORDER BY {_quote_identifier(metric)} ASC",
        values,
    ).fetchall()
    return [{group_by: row[0], metric: row[1]} for row in rows]


def _aggregation_sql(conn: sqlite3.Connection, plan: AnalysisPlan) -> Any:
    params = plan.logic_form.parameters
    metric = params.get("metric")
    dimension = params.get("dimension")
    aggregation = str(params.get("aggregation") or "sum")
    if dimension:
        return _grouped_aggregation_sql(conn, str(dimension), None if metric is None else str(metric), aggregation)
    if aggregation == "count" or metric is None:
        return int(conn.execute("SELECT COUNT(*) FROM analysis_table").fetchone()[0])
    sql_func = _sql_agg_func(aggregation)
    return conn.execute(f"SELECT {sql_func}({_quote_identifier(str(metric))}) FROM analysis_table").fetchone()[0]


def _ranking_sql(conn: sqlite3.Connection, plan: AnalysisPlan) -> list[dict[str, Any]]:
    params = plan.logic_form.parameters
    dimension = str(params["dimension"])
    metric = None if params.get("metric") is None else str(params.get("metric"))
    aggregation = str(params.get("aggregation") or "sum")
    rows = _grouped_aggregation_sql(conn, dimension, metric, aggregation)
    if not rows:
        return rows
    metric_column = next(key for key in rows[0] if key != dimension)
    reverse = str(params.get("sort_order") or "desc") == "desc"
    rows.sort(key=lambda row: row.get(metric_column), reverse=reverse)
    return rows[: int(params.get("limit") or 1)]


def _rank_by_metric_sql(conn: sqlite3.Connection, plan: AnalysisPlan) -> dict[str, Any]:
    logic = plan.logic_form
    params = logic.parameters
    group_by = str(logic.group_by or params["group_by"])
    metric = str(logic.metric or params.get("metric") or "count")
    options = dict(logic.options or params.get("options") or {})
    if metric != "fraud_volume_rate":
        raise ValueError(f"Metric {metric} is not SQL-compatible in the MVP.")
    values: list[Any] = []
    where_sql = ""
    if options:
        placeholders = ", ".join("?" for _ in options)
        where_sql = f" WHERE {_quote_identifier(group_by)} IN ({placeholders})"
        values.extend(str(value) for value in options.values())
    q_group_by = _quote_identifier(group_by)
    rows = conn.execute(
        f"SELECT {q_group_by}, "
        "SUM(CASE WHEN has_fraudulent_dispute THEN eur_amount ELSE 0 END) AS fraudulent_volume, "
        "SUM(eur_amount) AS total_volume, "
        "CASE WHEN SUM(eur_amount) = 0 THEN 0 ELSE SUM(CASE WHEN has_fraudulent_dispute THEN eur_amount ELSE 0 END) / SUM(eur_amount) END AS fraud_volume_rate "
        f"FROM analysis_table{where_sql} GROUP BY {q_group_by} ORDER BY fraud_volume_rate DESC",
        values,
    ).fetchall()
    candidate_table = [
        {
            group_by: str(row[0]),
            "fraudulent_volume": row[1],
            "total_volume": row[2],
            "fraud_volume_rate": row[3],
        }
        for row in rows
    ]
    if not candidate_table:
        return {"answer": "Not Applicable", "candidate_table": [], "metric": metric}
    selected = candidate_table[0]
    selected_value = str(selected[group_by])
    selected_option = None
    answer = selected_value
    for letter, option_value in options.items():
        if str(option_value) == selected_value:
            selected_option = letter
            answer = f"{letter}. {selected_value}"
            break
    return {
        "answer": answer,
        "selected": selected_value,
        "selected_option": selected_option,
        "metric": metric,
        "metric_definition": logic.metric_definition,
        "group_by": group_by,
        "objective": logic.objective or params.get("objective") or "maximum",
        "candidate_table": candidate_table,
    }


def _grouped_aggregation_sql(conn: sqlite3.Connection, dimension: str, metric: str | None, aggregation: str) -> list[dict[str, Any]]:
    if aggregation == "count" or metric is None:
        rows = conn.execute(
            f"SELECT {_quote_identifier(dimension)}, COUNT(*) AS count FROM analysis_table GROUP BY {_quote_identifier(dimension)}"
        ).fetchall()
        return [{dimension: row[0], "count": row[1]} for row in rows]
    sql_func = _sql_agg_func(aggregation)
    q_dimension = _quote_identifier(dimension)
    q_metric = _quote_identifier(str(metric))
    rows = conn.execute(
        f"SELECT {q_dimension}, {sql_func}({q_metric}) AS {q_metric} FROM analysis_table GROUP BY {q_dimension}"
    ).fetchall()
    return [{dimension: row[0], metric: row[1]} for row in rows]


def _sql_agg_func(aggregation: str) -> str:
    return {
        "mean": "AVG",
        "max": "MAX",
        "min": "MIN",
        "count": "COUNT",
    }.get(aggregation, "SUM")


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
