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
from data_agent_core.core.capability_registry import SQL_NATIVE_OPERATIONS
from data_agent_core.errors.error_result import ErrorResult
from data_agent_core.errors.error_types import SQL_EXECUTION_ERROR


NO_MATCHING_RECORDS = "没有匹配记录"


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
    if op not in SQL_NATIVE_OPERATIONS:
        raise ValueError(f"Operation {op} is not SQL-compatible in the MVP.")
    if op == "not_applicable":
        return "Not Applicable"

    df = context["payments"] if "payments" in context else _analysis_dataframe(context, plan.logic_form.parameters)
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
        if op == "row_count":
            return _row_count_sql(conn, plan)
        if op == "distinct_count":
            return _distinct_count_sql(conn, plan)
        if op == "metric_per_distinct_entity":
            return _metric_per_distinct_entity_sql(conn, plan)
        if op == "repeat_entity_percentage":
            return _repeat_entity_percentage_sql(conn, plan)
        if op == "repeat_entity_count":
            return _repeat_entity_count_sql(conn, plan)
        if op == "top_k_share":
            return _top_k_share_sql(conn, plan)
        if op == "null_check":
            return _null_check_sql(conn, plan)
        if op == "filtered_metric_ranking":
            return _filtered_metric_ranking_sql(conn, plan)
        if op == "rank_by_metric":
            return _rank_by_metric_sql(conn, plan)
        if op == "field_values":
            return _field_values_sql(conn, plan)
        if op == "boolean_percentage":
            return _boolean_percentage_sql(conn, plan)
        if op == "boolean_count_ratio":
            return _boolean_count_ratio_sql(conn, plan)
        if op == "fraud_rate_filtered":
            return _fraud_rate_filtered_sql(conn, plan)
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


def _analysis_dataframe(context: dict[str, Any], params: dict[str, Any]) -> Any:
    tables = context["tables"]
    same_schema_union = params.get("same_schema_union")
    if isinstance(same_schema_union, dict) and same_schema_union:
        return _materialize_same_schema_union(tables, same_schema_union)
    return _table(tables, params.get("table"))


def _materialize_same_schema_union(tables: dict[str, Any], union_plan: dict[str, Any]) -> Any:
    source_tables = [str(table_name) for table_name in union_plan.get("source_tables") or [] if str(table_name)]
    if not source_tables:
        raise ValueError("Same-schema union requires source_tables.")
    missing = [table_name for table_name in source_tables if table_name not in tables]
    if missing:
        raise ValueError("Same-schema union references unavailable table(s): " + ", ".join(missing))
    first_columns = [str(column) for column in tables[source_tables[0]].columns]
    first_signature = set(first_columns)
    frames = []
    for table_name in source_tables:
        df = tables[table_name]
        if {str(column) for column in df.columns} != first_signature:
            raise ValueError("Same-schema union requires matching columns across source tables.")
        frames.append(df)
    import pandas as pd

    return pd.concat(frames, ignore_index=True, sort=False)


def _top_count_sql(conn: sqlite3.Connection, plan: AnalysisPlan) -> Any:
    params = plan.logic_form.parameters
    where_sql, values = _where_from_filters(plan.logic_form.filters)
    group_by = params["group_by"]
    q_group_by = _quote_identifier(group_by)
    sql = f"SELECT {q_group_by}, COUNT(*) AS n FROM analysis_table{where_sql} GROUP BY {q_group_by} ORDER BY n DESC LIMIT 1"
    row = conn.execute(sql, values).fetchone()
    if row is None:
        return NO_MATCHING_RECORDS
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
    if filters.get("month") is not None:
        where.append("CAST(strftime('%m', date(year || '-01-01', '+' || (day_of_year - 1) || ' days')) AS INTEGER) = ?")
        values.append(int(filters["month"]))
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
    value = conn.execute(f"SELECT {sql_func}({_quote_identifier(str(metric))}) FROM analysis_table").fetchone()[0]
    return 0.0 if value is None else value


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
    if metric not in {"fraud_volume_rate", "fraud_transaction_rate"}:
        raise ValueError(f"Metric {metric} is not SQL-compatible in the MVP.")
    objective = logic.objective or params.get("objective") or "maximum"
    order = "ASC" if objective == "minimum" else "DESC"
    where_sql, values = _where_from_filters(logic.filters)
    if options:
        placeholders = ", ".join("?" for _ in options)
        option_clause = f"{_quote_identifier(group_by)} IN ({placeholders})"
        where_sql = f"{where_sql} AND {option_clause}" if where_sql else f" WHERE {option_clause}"
        values.extend(str(value) for value in options.values())
    q_group_by = _quote_identifier(group_by)
    if metric == "fraud_volume_rate":
        metric_column = "fraud_volume_rate"
        rows = conn.execute(
            f"SELECT {q_group_by}, "
            "SUM(CASE WHEN LOWER(CAST(has_fraudulent_dispute AS TEXT)) IN ('true', '1', 'yes', 'y') THEN eur_amount ELSE 0 END) AS fraudulent_volume, "
            "SUM(eur_amount) AS total_volume, "
            "CASE WHEN SUM(eur_amount) = 0 THEN 0 ELSE SUM(CASE WHEN LOWER(CAST(has_fraudulent_dispute AS TEXT)) IN ('true', '1', 'yes', 'y') THEN eur_amount ELSE 0 END) / SUM(eur_amount) END AS fraud_volume_rate "
            f"FROM analysis_table{where_sql} GROUP BY {q_group_by} ORDER BY fraud_volume_rate {order}",
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
    else:
        metric_column = "fraud_transaction_rate"
        rows = conn.execute(
            f"SELECT {q_group_by}, "
            "SUM(CASE WHEN LOWER(CAST(has_fraudulent_dispute AS TEXT)) IN ('true', '1', 'yes', 'y') THEN 1 ELSE 0 END) AS fraudulent_transactions, "
            "COUNT(*) AS transaction_count, "
            "CASE WHEN COUNT(*) = 0 THEN 0 ELSE CAST(SUM(CASE WHEN LOWER(CAST(has_fraudulent_dispute AS TEXT)) IN ('true', '1', 'yes', 'y') THEN 1 ELSE 0 END) AS REAL) / COUNT(*) END AS fraud_transaction_rate "
            f"FROM analysis_table{where_sql} GROUP BY {q_group_by} ORDER BY fraud_transaction_rate {order}",
            values,
        ).fetchall()
        candidate_table = [
            {
                group_by: str(row[0]),
                "fraudulent_transactions": row[1],
                "transaction_count": row[2],
                "fraud_transaction_rate": row[3],
            }
            for row in rows
        ]
    if not candidate_table:
        return {"answer": NO_MATCHING_RECORDS, "candidate_table": [], "metric": metric}
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
        "selected_metric": float(selected[metric_column]) * 100.0,
        "metric": metric,
        "metric_definition": logic.metric_definition,
        "group_by": group_by,
        "objective": objective,
        "candidate_table": candidate_table,
    }


def _field_values_sql(conn: sqlite3.Connection, plan: AnalysisPlan) -> list[str]:
    field = str(plan.logic_form.parameters["field"])
    rows = conn.execute(
        f"SELECT DISTINCT {_quote_identifier(field)} FROM analysis_table WHERE {_quote_identifier(field)} IS NOT NULL ORDER BY {_quote_identifier(field)}"
    ).fetchall()
    return [str(row[0]) for row in rows]


def _row_count_sql(conn: sqlite3.Connection, plan: AnalysisPlan) -> int:
    where_sql, values = _where_from_filters(plan.logic_form.filters)
    return int(conn.execute(f"SELECT COUNT(*) FROM analysis_table{where_sql}", values).fetchone()[0] or 0)


def _distinct_count_sql(conn: sqlite3.Connection, plan: AnalysisPlan) -> int:
    field = str(plan.logic_form.parameters["field"])
    where_sql, values = _where_from_filters(plan.logic_form.filters)
    return int(
        conn.execute(
            f"SELECT COUNT(DISTINCT {_quote_identifier(field)}) FROM analysis_table{where_sql}",
            values,
        ).fetchone()[0]
        or 0
    )


def _metric_per_distinct_entity_sql(conn: sqlite3.Connection, plan: AnalysisPlan) -> float | str:
    metric = str(plan.logic_form.parameters.get("metric") or "")
    entity_field = str(plan.logic_form.parameters.get("entity_field") or plan.logic_form.parameters.get("field") or "")
    aggregation = str(plan.logic_form.parameters.get("aggregation") or "sum")
    if not metric or not entity_field:
        raise ValueError("metric_per_distinct_entity requires metric and entity_field.")
    where_sql, values = _where_from_filters(plan.logic_form.filters)
    q_entity = _quote_identifier(entity_field)
    not_null_entity = f"({q_entity} IS NOT NULL AND TRIM(LOWER(CAST({q_entity} AS TEXT))) NOT IN ('', 'nan', 'none', 'null'))"
    filtered_sql = f"{where_sql} AND {not_null_entity}" if where_sql else f" WHERE {not_null_entity}"
    if aggregation == "mean" and metric not in {"__row_count__", "row_count", "transaction_count"}:
        q_metric = _quote_identifier(metric)
        row = conn.execute(
            f"SELECT AVG(entity_mean) FROM (SELECT {q_entity}, AVG(CAST({q_metric} AS REAL)) AS entity_mean "
            f"FROM analysis_table{filtered_sql} GROUP BY {q_entity})",
            values,
        ).fetchone()
        return 0.0 if row[0] is None else float(row[0])
    numerator_sql = "COUNT(*)" if metric in {"__row_count__", "row_count", "transaction_count"} or aggregation == "count" else f"SUM(CAST({_quote_identifier(metric)} AS REAL))"
    row = conn.execute(
        f"SELECT {numerator_sql}, "
        f"COUNT(DISTINCT {q_entity}) FROM analysis_table{filtered_sql}",
        values,
    ).fetchone()
    entity_count = int(row[1] or 0)
    if entity_count == 0:
        return 0.0
    return float(row[0] or 0.0) / entity_count


def _repeat_entity_percentage_sql(conn: sqlite3.Connection, plan: AnalysisPlan) -> float:
    field = str(plan.logic_form.parameters["field"])
    where_sql, values = _where_from_filters(plan.logic_form.filters)
    null_clause = f"{_quote_identifier(field)} IS NOT NULL"
    filtered_sql = f"{where_sql} AND {null_clause}" if where_sql else f" WHERE {null_clause}"
    rows = conn.execute(
        f"SELECT COUNT(*) AS entity_count, SUM(CASE WHEN n > 1 THEN 1 ELSE 0 END) AS repeat_count "
        f"FROM (SELECT {_quote_identifier(field)}, COUNT(*) AS n FROM analysis_table{filtered_sql} "
        f"GROUP BY {_quote_identifier(field)})",
        values,
    ).fetchone()
    entity_count = int(rows[0] or 0)
    if entity_count == 0:
        return 0.0
    return float(rows[1] or 0) / entity_count * 100


def _repeat_entity_count_sql(conn: sqlite3.Connection, plan: AnalysisPlan) -> int:
    field = str(plan.logic_form.parameters["field"])
    min_count = int(plan.logic_form.parameters.get("min_count") or 2)
    where_sql, values = _where_from_filters(plan.logic_form.filters)
    q_field = _quote_identifier(field)
    null_clause = f"({q_field} IS NOT NULL AND TRIM(LOWER(CAST({q_field} AS TEXT))) NOT IN ('', 'nan', 'none', 'null'))"
    filtered_sql = f"{where_sql} AND {null_clause}" if where_sql else f" WHERE {null_clause}"
    row = conn.execute(
        f"SELECT COUNT(*) FROM (SELECT {q_field}, COUNT(*) AS n FROM analysis_table{filtered_sql} "
        f"GROUP BY {q_field} HAVING n >= ?)",
        values + [min_count],
    ).fetchone()
    return int(row[0] or 0)


def _top_k_share_sql(conn: sqlite3.Connection, plan: AnalysisPlan) -> float:
    params = plan.logic_form.parameters
    dimension = str(params["dimension"])
    ranking_metric = params.get("ranking_metric", params.get("metric"))
    share_metric = params.get("share_metric", params.get("metric"))
    aggregation = str(params.get("aggregation") or "sum")
    limit = int(params.get("limit") or 3)
    where_sql, values = _where_from_filters(plan.logic_form.filters)
    q_dimension = _quote_identifier(dimension)
    if aggregation == "count" or not ranking_metric or ranking_metric in {"__row_count__", "row_count", "transaction_count"}:
        rows = conn.execute(
            f"SELECT {q_dimension} FROM analysis_table{where_sql} GROUP BY {q_dimension} ORDER BY COUNT(*) DESC LIMIT ?",
            values + [limit],
        ).fetchall()
    else:
        ranking_metric_name = str(ranking_metric)
        rows = conn.execute(
            f"SELECT {q_dimension} FROM analysis_table{where_sql} "
            f"GROUP BY {q_dimension} ORDER BY SUM({_quote_identifier(ranking_metric_name)}) DESC LIMIT ?",
            values + [limit],
        ).fetchall()
    selected_values = [row[0] for row in rows]
    if not selected_values:
        return 0.0
    placeholders = ", ".join("?" for _ in selected_values)
    selected_clause = f"{q_dimension} IN ({placeholders})"
    selected_where = f"{where_sql} AND {selected_clause}" if where_sql else f" WHERE {selected_clause}"
    if share_metric in {None, "__row_count__", "row_count", "transaction_count"}:
        denominator = float(conn.execute(f"SELECT COUNT(*) FROM analysis_table{where_sql}", values).fetchone()[0] or 0)
        numerator = float(conn.execute(f"SELECT COUNT(*) FROM analysis_table{selected_where}", values + selected_values).fetchone()[0] or 0)
    else:
        share_metric_name = str(share_metric)
        q_share_metric = _quote_identifier(share_metric_name)
        denominator = float(conn.execute(f"SELECT SUM({q_share_metric}) FROM analysis_table{where_sql}", values).fetchone()[0] or 0)
        numerator = float(conn.execute(f"SELECT SUM({q_share_metric}) FROM analysis_table{selected_where}", values + selected_values).fetchone()[0] or 0)
    if denominator == 0.0:
        return 0.0
    return numerator / denominator * 100


def _null_check_sql(conn: sqlite3.Connection, plan: AnalysisPlan) -> int | float | dict[str, Any]:
    params = plan.logic_form.parameters
    field = params.get("field")
    mode = str(params.get("mode") or "count")
    target_field = params.get("target_field")
    target_value = bool(params.get("target_value", True))
    where_sql, values = _where_from_filters(plan.logic_form.filters)
    if field:
        field_name = str(field)
        null_expr = f"({_quote_identifier(field_name)} IS NULL OR TRIM(LOWER(CAST({_quote_identifier(field_name)} AS TEXT))) IN ('', 'nan', 'none', 'null'))"
        if target_field:
            target_expr = f"LOWER(CAST({_quote_identifier(str(target_field))} AS TEXT)) IN ({_bool_literals_sql(target_value)})"
            null_expr = f"({null_expr} AND {target_expr})"
        row = conn.execute(
            f"SELECT COUNT(*) AS total_rows, SUM(CASE WHEN {null_expr} THEN 1 ELSE 0 END) AS null_count FROM analysis_table{where_sql}",
            values,
        ).fetchone()
        denominator = int(row[0] or 0)
        null_count = int(row[1] or 0)
        checked_field = field_name
    else:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(analysis_table)").fetchall()]
        total_rows = int(conn.execute(f"SELECT COUNT(*) FROM analysis_table{where_sql}", values).fetchone()[0] or 0)
        denominator = total_rows * len(columns)
        null_count = 0
        for column in columns:
            null_expr = f"({_quote_identifier(column)} IS NULL OR TRIM(LOWER(CAST({_quote_identifier(column)} AS TEXT))) IN ('', 'nan', 'none', 'null'))"
            null_count += int(
                conn.execute(
                    f"SELECT SUM(CASE WHEN {null_expr} THEN 1 ELSE 0 END) FROM analysis_table{where_sql}",
                    values,
                ).fetchone()[0]
                or 0
            )
        checked_field = None
    if mode == "exists":
        return {"answer": "yes" if null_count else "no", "null_count": null_count, "checked_field": checked_field}
    if mode == "max_field":
        columns = [row[1] for row in conn.execute("PRAGMA table_info(analysis_table)").fetchall()]
        if not columns:
            return NO_MATCHING_RECORDS
        counts: list[tuple[str, int]] = []
        for column in columns:
            null_expr = f"({_quote_identifier(column)} IS NULL OR TRIM(LOWER(CAST({_quote_identifier(column)} AS TEXT))) IN ('', 'nan', 'none', 'null'))"
            count = int(conn.execute(f"SELECT SUM(CASE WHEN {null_expr} THEN 1 ELSE 0 END) FROM analysis_table").fetchone()[0] or 0)
            counts.append((column, count))
        counts.sort(key=lambda item: (-item[1], item[0]))
        return counts[0][0]
    if mode == "rate":
        return 0.0 if denominator == 0 else null_count / denominator * 100
    if mode == "present_rate":
        return 0.0 if denominator == 0 else (denominator - null_count) / denominator * 100
    return null_count


def _filtered_metric_ranking_sql(conn: sqlite3.Connection, plan: AnalysisPlan) -> list[dict[str, Any]]:
    params = plan.logic_form.parameters
    dimension = str(params["dimension"])
    metric = params.get("metric")
    aggregation = str(params.get("aggregation") or "sum")
    sort_order = "ASC" if str(params.get("sort_order") or "desc") == "asc" else "DESC"
    limit = int(params.get("limit") or 1)
    where_sql, values = _where_from_filters(plan.logic_form.filters)
    if aggregation == "count" or metric is None:
        rows = conn.execute(
            f"SELECT {_quote_identifier(dimension)}, COUNT(*) AS count FROM analysis_table{where_sql} "
            f"GROUP BY {_quote_identifier(dimension)} ORDER BY count {sort_order} LIMIT ?",
            values + [limit],
        ).fetchall()
        return [{dimension: row[0], "count": row[1]} for row in rows]
    metric_name = str(metric)
    sql_func = _sql_agg_func(aggregation)
    rows = conn.execute(
        f"SELECT {_quote_identifier(dimension)}, {sql_func}({_quote_identifier(metric_name)}) AS value FROM analysis_table{where_sql} "
        f"GROUP BY {_quote_identifier(dimension)} ORDER BY value {sort_order} LIMIT ?",
        values + [limit],
    ).fetchall()
    return [{dimension: row[0], metric_name: row[1]} for row in rows]


def _boolean_percentage_sql(conn: sqlite3.Connection, plan: AnalysisPlan) -> float:
    params = plan.logic_form.parameters
    filters = plan.logic_form.filters
    field = str(params["field"])
    expected = bool(params.get("value", True))
    where_sql, values = _where_from_filters(filters)
    rows = conn.execute(
        f"SELECT COUNT(*) AS total_rows, "
        f"SUM(CASE WHEN LOWER(CAST({_quote_identifier(field)} AS TEXT)) IN ({_bool_literals_sql(expected)}) THEN 1 ELSE 0 END) AS matching_rows "
        f"FROM analysis_table{where_sql}",
        values,
    ).fetchone()
    total_rows = int(rows[0] or 0)
    if total_rows == 0:
        return 0.0
    return float(rows[1] or 0) / total_rows * 100


def _boolean_count_ratio_sql(conn: sqlite3.Connection, plan: AnalysisPlan) -> float | str:
    params = plan.logic_form.parameters
    field = str(params["field"])
    left_value = bool(params.get("left_value", True))
    right_value = bool(params.get("right_value", False))
    where_sql, values = _where_from_filters(plan.logic_form.filters)
    rows = conn.execute(
        f"SELECT "
        f"SUM(CASE WHEN LOWER(CAST({_quote_identifier(field)} AS TEXT)) IN ({_bool_literals_sql(left_value)}) THEN 1 ELSE 0 END), "
        f"SUM(CASE WHEN LOWER(CAST({_quote_identifier(field)} AS TEXT)) IN ({_bool_literals_sql(right_value)}) THEN 1 ELSE 0 END) "
        f"FROM analysis_table{where_sql}",
        values,
    ).fetchone()
    right_count = int(rows[1] or 0)
    if right_count == 0:
        return 0.0
    return float(rows[0] or 0) / right_count


def _fraud_rate_filtered_sql(conn: sqlite3.Connection, plan: AnalysisPlan) -> float | str:
    where_sql, values = _where_from_filters(plan.logic_form.filters)
    rows = conn.execute(
        "SELECT SUM(eur_amount) AS total_volume, "
        "SUM(CASE WHEN LOWER(CAST(has_fraudulent_dispute AS TEXT)) IN ('true', '1', 'yes', 'y') THEN eur_amount ELSE 0 END) AS fraud_volume "
        f"FROM analysis_table{where_sql}",
        values,
    ).fetchone()
    total_volume = float(rows[0] or 0)
    if total_volume == 0:
        return 0.0
    return float(rows[1] or 0) / total_volume * 100


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


def _where_from_filters(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    where = []
    values: list[Any] = []
    for column, expected in filters.items():
        if expected is None:
            continue
        if expected == "__NULL__":
            q_column = _quote_identifier(str(column))
            where.append(f"({q_column} IS NULL OR TRIM(LOWER(CAST({q_column} AS TEXT))) IN ('', 'nan', 'none', 'null'))")
            continue
        if expected == "__NOT_NULL__":
            q_column = _quote_identifier(str(column))
            where.append(f"({q_column} IS NOT NULL AND TRIM(LOWER(CAST({q_column} AS TEXT))) NOT IN ('', 'nan', 'none', 'null'))")
            continue
        if column == "month_range":
            start, end = expected
            where.append("CAST(strftime('%m', date(year || '-01-01', '+' || (day_of_year - 1) || ' days')) AS INTEGER) BETWEEN ? AND ?")
            values.extend([int(start), int(end)])
            continue
        if _is_day_of_year_range_filter(column, expected):
            start, end = expected
            q_column = _quote_identifier(str(column))
            where.append(f"CAST({q_column} AS REAL) BETWEEN ? AND ?")
            values.extend([float(start), float(end)])
            continue
        if isinstance(expected, dict) and ("min" in expected or "max" in expected):
            q_column = _quote_identifier(str(column))
            if expected.get("min") is not None:
                where.append(f"CAST({q_column} AS REAL) >= ?")
                values.append(float(expected["min"]))
            if expected.get("max") is not None:
                where.append(f"CAST({q_column} AS REAL) <= ?")
                values.append(float(expected["max"]))
            continue
        where.append(f"{_quote_identifier(str(column))} = ?")
        values.append(expected)
    return (" WHERE " + " AND ".join(where) if where else ""), values


def _is_day_of_year_range_filter(column: Any, expected: Any) -> bool:
    if str(column) != "day_of_year" or not isinstance(expected, (list, tuple)) or len(expected) != 2:
        return False
    try:
        start = float(expected[0])
        end = float(expected[1])
    except (TypeError, ValueError):
        return False
    return start <= end


def _bool_literals_sql(expected: bool) -> str:
    return "'true', '1', 'yes', 'y'" if expected else "'false', '0', 'no', 'n'"
