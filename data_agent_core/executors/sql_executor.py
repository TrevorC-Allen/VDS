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
        if op == "growth_ranking":
            return _growth_ranking_sql(conn, plan)
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
        if op == "grouped_child_ranking":
            return _grouped_child_ranking_sql(conn, plan)
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
    derived_metric = params.get("derived_metric")
    metric = params.get("metric")
    dimension = params.get("dimension")
    aggregation = str(params.get("aggregation") or "sum")
    where_sql, values = _where_from_filters(plan.logic_form.filters)
    where_sql, values = _with_candidate_topn_filter_sql(where_sql, values, params)
    metric_specs = _metric_specs(params.get("metric_specs"))
    if isinstance(derived_metric, dict) and derived_metric:
        if metric_specs:
            return _attach_group_share_if_requested_sql(
                _metric_spec_aggregation_with_derived_sql(conn, metric_specs, derived_metric, dimension=dimension, where_sql=where_sql, values=values),
                params,
            )
        if dimension:
            return _attach_group_share_if_requested_sql(
                _grouped_derived_ratio_sql(conn, str(dimension), derived_metric, where_sql=where_sql, values=values),
                params,
            )
        return _derived_ratio_sql(conn, derived_metric, where_sql=where_sql, values=values)
    if metric_specs:
        return _attach_group_share_if_requested_sql(
            _metric_spec_aggregation_sql(conn, metric_specs, dimension=dimension, where_sql=where_sql, values=values),
            params,
        )
    metrics = _metric_list(params.get("metrics"))
    if len(metrics) > 1:
        return _attach_group_share_if_requested_sql(
            _multi_metric_aggregation_sql(conn, metrics, aggregation, dimension=dimension, where_sql=where_sql, values=values),
            params,
        )
    if dimension:
        return _attach_group_share_if_requested_sql(
            _grouped_aggregation_sql(conn, str(dimension), None if metric is None else str(metric), aggregation, where_sql=where_sql, values=values),
            params,
        )
    if aggregation == "count" or metric is None:
        return int(conn.execute(f"SELECT COUNT(*) FROM analysis_table{where_sql}", values).fetchone()[0])
    if aggregation in {"nunique", "distinct_count"}:
        value = conn.execute(f"SELECT COUNT(DISTINCT {_quote_identifier(str(metric))}) FROM analysis_table{where_sql}", values).fetchone()[0]
        return int(value or 0)
    sql_func = _sql_agg_func(aggregation)
    value = conn.execute(f"SELECT {sql_func}({_quote_identifier(str(metric))}) FROM analysis_table{where_sql}", values).fetchone()[0]
    return 0.0 if value is None else value


def _metric_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    metrics: list[str] = []
    for item in value:
        metric = str(item or "").strip()
        if metric and metric not in metrics:
            metrics.append(metric)
    return metrics


def _metric_specs(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    specs: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("field") or "").strip()
        field = str(item.get("field") or "").strip()
        aggregation = str(item.get("aggregation") or "sum").strip()
        if name and field:
            specs.append({"name": name, "field": field, "aggregation": aggregation})
    return specs


def _metric_spec_aggregation_sql(
    conn: sqlite3.Connection,
    specs: list[dict[str, str]],
    *,
    dimension: Any = None,
    where_sql: str = "",
    values: list[Any] | None = None,
) -> dict[str, Any] | list[dict[str, Any]]:
    values = list(values or [])
    expressions = [_metric_spec_sql_expression(spec) for spec in specs]
    if dimension:
        dimension_name = str(dimension)
        q_dimension = _quote_identifier(dimension_name)
        rows = conn.execute(
            f"SELECT {q_dimension}, {', '.join(expressions)} FROM analysis_table{where_sql} GROUP BY {q_dimension}",
            values,
        ).fetchall()
        return [
            {dimension_name: row[0], **{spec["name"]: row[index + 1] for index, spec in enumerate(specs)}}
            for row in rows
        ]
    row = conn.execute(f"SELECT {', '.join(expressions)} FROM analysis_table{where_sql}", values).fetchone()
    if row is None:
        return {spec["name"]: 0 for spec in specs}
    return {spec["name"]: 0 if row[index] is None else row[index] for index, spec in enumerate(specs)}


def _metric_spec_aggregation_with_derived_sql(
    conn: sqlite3.Connection,
    specs: list[dict[str, str]],
    derived_metric: dict[str, Any],
    *,
    dimension: Any = None,
    where_sql: str = "",
    values: list[Any] | None = None,
) -> dict[str, Any] | list[dict[str, Any]]:
    values = list(values or [])
    expressions = [_metric_spec_sql_expression(spec) for spec in specs]
    derived_name = str(derived_metric.get("name") or "ratio")
    expressions.append(f"{_derived_ratio_sql_expression(derived_metric)} AS {_quote_identifier(derived_name)}")
    if dimension:
        dimension_name = str(dimension)
        q_dimension = _quote_identifier(dimension_name)
        rows = conn.execute(
            f"SELECT {q_dimension}, {', '.join(expressions)} FROM analysis_table{where_sql} GROUP BY {q_dimension}",
            values,
        ).fetchall()
        names = [spec["name"] for spec in specs] + [derived_name]
        return [{dimension_name: row[0], **{name: row[index + 1] for index, name in enumerate(names)}} for row in rows]
    row = conn.execute(f"SELECT {', '.join(expressions)} FROM analysis_table{where_sql}", values).fetchone()
    names = [spec["name"] for spec in specs] + [derived_name]
    if row is None:
        return {name: 0 for name in names}
    return {name: 0 if row[index] is None else row[index] for index, name in enumerate(names)}


def _metric_spec_sql_expression(spec: dict[str, str]) -> str:
    aggregation = str(spec.get("aggregation") or "sum")
    field = str(spec.get("field") or "")
    name = str(spec.get("name") or field)
    if field == "__row_count__":
        expression = "COUNT(*)"
    elif aggregation in {"nunique", "distinct_count"}:
        q_field = _quote_identifier(field)
        expression = f"COUNT(DISTINCT {q_field})"
    elif aggregation == "count":
        q_field = _quote_identifier(field)
        expression = f"COUNT({q_field})"
    else:
        q_field = _quote_identifier(field)
        expression = f"{_sql_agg_func(aggregation)}({q_field})"
    return f"{expression} AS {_quote_identifier(name)}"


def _attach_group_share_if_requested_sql(result: Any, params: dict[str, Any]) -> Any:
    if not params.get("share_of_total") or not isinstance(result, list) or not result:
        return result
    dimension = str(params.get("dimension") or "")
    value_column = _share_value_column_sql(result, params, dimension)
    if not value_column:
        return result
    total = sum(_numeric_result_value(row.get(value_column)) for row in result)
    share_column = str(params.get("share_column") or f"{value_column}_share")
    total_column = str(params.get("total_metric_column") or f"total_{value_column}")
    rows: list[dict[str, Any]] = []
    for row in result:
        enriched = dict(row)
        value = _numeric_result_value(row.get(value_column))
        enriched[total_column] = total
        enriched[share_column] = 0.0 if total == 0.0 else value / total * 100
        rows.append(enriched)
    return rows


def _share_value_column_sql(rows: list[dict[str, Any]], params: dict[str, Any], dimension: str) -> str:
    aggregation = str(params.get("aggregation") or "")
    metric = params.get("share_metric") or params.get("metric")
    if aggregation == "count" or metric in {None, "__row_count__", "row_count", "transaction_count"}:
        if "count" in rows[0]:
            return "count"
    metric_name = str(metric or "").strip()
    if metric_name and metric_name in rows[0]:
        return metric_name
    for key, value in rows[0].items():
        if key == dimension or str(key).endswith("_share"):
            continue
        if _numeric_result_value(value) != 0.0 or value in (0, 0.0):
            return str(key)
    return ""


def _numeric_result_value(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _multi_metric_aggregation_sql(
    conn: sqlite3.Connection,
    metrics: list[str],
    aggregation: str,
    *,
    dimension: Any = None,
    where_sql: str = "",
    values: list[Any] | None = None,
) -> dict[str, Any] | list[dict[str, Any]]:
    values = list(values or [])
    sql_func = _sql_agg_func(aggregation)
    metric_exprs = [
        f"{sql_func}({_quote_identifier(metric)}) AS {_quote_identifier(metric)}"
        for metric in metrics
    ]
    if dimension:
        dimension_name = str(dimension)
        q_dimension = _quote_identifier(dimension_name)
        rows = conn.execute(
            f"SELECT {q_dimension}, {', '.join(metric_exprs)} FROM analysis_table{where_sql} GROUP BY {q_dimension}",
            values,
        ).fetchall()
        return [
            {dimension_name: row[0], **{metric: row[index + 1] for index, metric in enumerate(metrics)}}
            for row in rows
        ]
    row = conn.execute(f"SELECT {', '.join(metric_exprs)} FROM analysis_table{where_sql}", values).fetchone()
    if row is None:
        return {metric: 0.0 for metric in metrics}
    return {metric: 0.0 if row[index] is None else row[index] for index, metric in enumerate(metrics)}


def _ranking_sql(conn: sqlite3.Connection, plan: AnalysisPlan) -> list[dict[str, Any]]:
    params = plan.logic_form.parameters
    dimension = str(params["dimension"])
    metric = None if params.get("metric") is None else str(params.get("metric"))
    aggregation = str(params.get("aggregation") or "sum")
    where_sql, values = _where_from_filters(plan.logic_form.filters)
    where_sql, values = _with_candidate_topn_filter_sql(where_sql, values, params)
    derived_metric = params.get("derived_metric")
    if isinstance(derived_metric, dict) and derived_metric:
        rows = _grouped_derived_ratio_sql(conn, dimension, derived_metric, where_sql=where_sql, values=values)
    else:
        rows = _grouped_aggregation_sql(conn, dimension, metric, aggregation, where_sql=where_sql, values=values)
        rows = _attach_metric_spec_columns_sql(conn, rows, dimension, _metric_specs(params.get("metric_specs")), where_sql=where_sql, values=values)
    if not rows:
        return rows
    metric_column = next(key for key in rows[0] if key != dimension)
    reverse = str(params.get("sort_order") or "desc") == "desc"
    rows.sort(key=lambda row: row.get(metric_column), reverse=reverse)
    return _slice_ranked_rows(rows, params)


def _growth_ranking_sql(conn: sqlite3.Connection, plan: AnalysisPlan) -> list[dict[str, Any]]:
    params = plan.logic_form.parameters
    dimension = str(params.get("dimension") or "")
    metric = str(params.get("metric") or "")
    time_column = str(params.get("time_column") or "")
    if not dimension or not metric or not time_column:
        raise ValueError("growth_ranking requires dimension, metric, and time_column.")
    aggregation = str(params.get("aggregation") or "sum")
    growth_mode = str(params.get("growth_mode") or "rate")
    metric_name = f"{metric}_growth_rate" if growth_mode == "rate" else f"{metric}_growth_delta"
    sort_order = "ASC" if str(params.get("sort_order") or "desc") == "asc" else "DESC"
    limit = 1000000 if isinstance(params.get("rank_target"), dict) else int(params.get("rank_position") or params.get("limit") or 1)
    where_sql, values = _where_from_filters(plan.logic_form.filters)
    period_expr = _sql_period_expr(time_column)
    metric_expr = _sql_metric_agg_expr(metric, aggregation)
    growth_sort_expr = "growth_rate" if growth_mode == "rate" else "ABS(growth_delta)" if growth_mode == "abs_delta" else "growth_delta"
    sql = f"""
WITH period_values AS (
  SELECT
    {_quote_identifier(dimension)} AS dimension_value,
    {period_expr} AS period_value,
    {metric_expr} AS metric_value
  FROM analysis_table{where_sql}
  GROUP BY dimension_value, period_value
),
ranked AS (
  SELECT
    dimension_value,
    period_value,
    metric_value,
    ROW_NUMBER() OVER (PARTITION BY dimension_value ORDER BY period_value ASC) AS rn_asc,
    ROW_NUMBER() OVER (PARTITION BY dimension_value ORDER BY period_value DESC) AS rn_desc,
    COUNT(*) OVER (PARTITION BY dimension_value) AS period_count
  FROM period_values
  WHERE dimension_value IS NOT NULL AND period_value IS NOT NULL
),
start_rows AS (
  SELECT dimension_value, period_value AS start_period, metric_value AS start_value
  FROM ranked
  WHERE rn_asc = 1 AND period_count >= 2
),
end_rows AS (
  SELECT dimension_value, period_value AS end_period, metric_value AS end_value
  FROM ranked
  WHERE rn_desc = 1 AND period_count >= 2
),
growth_rows AS (
  SELECT
    s.dimension_value,
    s.start_period,
    e.end_period,
    s.start_value,
    e.end_value,
    (e.end_value - s.start_value) AS growth_delta,
    CASE
      WHEN ABS(s.start_value) < 0.000000000001 THEN 0.0
      ELSE (e.end_value - s.start_value) / ABS(s.start_value)
    END AS growth_rate
  FROM start_rows s
  JOIN end_rows e ON s.dimension_value = e.dimension_value
)
SELECT dimension_value, {growth_sort_expr}, start_period, end_period, start_value, end_value, growth_delta, growth_rate
FROM growth_rows
ORDER BY {growth_sort_expr} {sort_order}
LIMIT ?
"""
    rows = conn.execute(sql, values + [limit]).fetchall()
    payload = [
        {
            dimension: row[0],
            metric_name: row[1],
            "start_period": row[2],
            "end_period": row[3],
            "start_value": row[4],
            "end_value": row[5],
            "growth_delta": row[6],
            "growth_rate": row[7],
        }
        for row in rows
    ]
    return _slice_ranked_rows(payload, params)


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


def _top_k_share_sql(conn: sqlite3.Connection, plan: AnalysisPlan) -> float | list[dict[str, Any]]:
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
        return [] if params.get("requires_previous_artifact") or params.get("referent_values") else 0.0
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
        return [] if params.get("requires_previous_artifact") or params.get("referent_values") else 0.0
    if params.get("requires_previous_artifact") or params.get("referent_values"):
        metric_column = str(params.get("metric") or params.get("share_metric") or "metric_value")
        total_column = str(params.get("total_metric_column") or f"total_{metric_column}")
        share_column = str(params.get("share_column") or f"{metric_column}_share")
        result_rows: list[dict[str, Any]] = []
        for selected_value in selected_values:
            value_where = f"{where_sql} AND {q_dimension} = ?" if where_sql else f" WHERE {q_dimension} = ?"
            value_params = values + [selected_value]
            if share_metric in {None, "__row_count__", "row_count", "transaction_count"}:
                group_numerator = float(conn.execute(f"SELECT COUNT(*) FROM analysis_table{value_where}", value_params).fetchone()[0] or 0)
            else:
                group_numerator = float(conn.execute(f"SELECT SUM({q_share_metric}) FROM analysis_table{value_where}", value_params).fetchone()[0] or 0)
            result_rows.append(
                {
                    dimension: selected_value,
                    metric_column: group_numerator,
                    total_column: denominator,
                    share_column: group_numerator / denominator * 100,
                }
            )
        return result_rows
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
    derived_metric = params.get("derived_metric")
    metric = params.get("metric")
    aggregation = str(params.get("aggregation") or "sum")
    sort_order = "ASC" if str(params.get("sort_order") or "desc") == "asc" else "DESC"
    limit = 1000000 if isinstance(params.get("rank_target"), dict) else int(params.get("rank_position") or params.get("limit") or 1)
    where_sql, values = _where_from_filters(plan.logic_form.filters)
    where_sql, values = _with_candidate_topn_filter_sql(where_sql, values, params)
    if isinstance(derived_metric, dict) and derived_metric:
        metric_name = str(derived_metric.get("name") or "ratio")
        rows = conn.execute(
            f"SELECT {_quote_identifier(dimension)}, {_derived_ratio_sql_expression(derived_metric)} AS value "
            f"FROM analysis_table{where_sql} GROUP BY {_quote_identifier(dimension)} ORDER BY value {sort_order} LIMIT ?",
            values + [limit],
        ).fetchall()
        return _slice_ranked_rows([{dimension: row[0], metric_name: row[1]} for row in rows], params)
    if aggregation == "count" or metric is None:
        rows = conn.execute(
            f"SELECT {_quote_identifier(dimension)}, COUNT(*) AS count FROM analysis_table{where_sql} "
            f"GROUP BY {_quote_identifier(dimension)} ORDER BY count {sort_order} LIMIT ?",
            values + [limit],
        ).fetchall()
        return _slice_ranked_rows([{dimension: row[0], "count": row[1]} for row in rows], params)
    if aggregation in {"nunique", "distinct_count"}:
        rows = conn.execute(
            f"SELECT {_quote_identifier(dimension)}, COUNT(DISTINCT {_quote_identifier(str(metric))}) AS count "
            f"FROM analysis_table{where_sql} GROUP BY {_quote_identifier(dimension)} ORDER BY count {sort_order} LIMIT ?",
            values + [limit],
        ).fetchall()
        return _slice_ranked_rows([{dimension: row[0], "count": row[1]} for row in rows], params)
    metric_name = str(metric)
    sql_func = _sql_agg_func(aggregation)
    rows = conn.execute(
        f"SELECT {_quote_identifier(dimension)}, {sql_func}({_quote_identifier(metric_name)}) AS value FROM analysis_table{where_sql} "
        f"GROUP BY {_quote_identifier(dimension)} ORDER BY value {sort_order} LIMIT ?",
        values + [limit],
    ).fetchall()
    result_rows = [{dimension: row[0], metric_name: row[1]} for row in rows]
    result_rows = _attach_metric_spec_columns_sql(conn, result_rows, dimension, _metric_specs(params.get("metric_specs")), where_sql=where_sql, values=values)
    return _slice_ranked_rows(result_rows, params)


def _grouped_child_ranking_sql(conn: sqlite3.Connection, plan: AnalysisPlan) -> list[dict[str, Any]]:
    params = plan.logic_form.parameters
    parent_dimension = str(params.get("parent_dimension") or "")
    child_dimension = str(params.get("child_dimension") or params.get("dimension") or "")
    if not parent_dimension or not child_dimension:
        raise ValueError("grouped_child_ranking requires parent and child dimensions.")
    aggregation = str(params.get("aggregation") or "sum")
    metric = params.get("metric")
    derived_metric = params.get("derived_metric")
    sort_order = "ASC" if str(params.get("sort_order") or "desc") == "asc" else "DESC"
    child_limit = int(params.get("child_limit") or params.get("limit") or 1)
    where_sql, values = _where_from_filters(plan.logic_form.filters)
    where_sql, values = _with_candidate_topn_filter_sql(where_sql, values, params)
    if isinstance(derived_metric, dict) and derived_metric:
        metric_name = str(derived_metric.get("name") or "ratio")
        metric_expr = _derived_ratio_sql_expression(derived_metric)
    elif aggregation == "count" or metric is None:
        metric_name = "count"
        metric_expr = "COUNT(*)"
    elif aggregation in {"nunique", "distinct_count"}:
        metric_name = "count"
        metric_expr = f"COUNT(DISTINCT {_quote_identifier(str(metric))})"
    else:
        metric_name = str(metric)
        metric_expr = f"{_sql_agg_func(aggregation)}({_quote_identifier(metric_name)})"
    q_parent = _quote_identifier(parent_dimension)
    q_child = _quote_identifier(child_dimension)
    rows = conn.execute(
        f"""
WITH grouped AS (
  SELECT {q_parent} AS parent_value, {q_child} AS child_value, {metric_expr} AS metric_value
  FROM analysis_table{where_sql}
  GROUP BY {q_parent}, {q_child}
),
ranked AS (
  SELECT
    parent_value,
    child_value,
    metric_value,
    ROW_NUMBER() OVER (PARTITION BY parent_value ORDER BY metric_value {sort_order}) AS child_rank
  FROM grouped
  WHERE parent_value IS NOT NULL AND child_value IS NOT NULL
)
SELECT parent_value, child_value, metric_value
FROM ranked
WHERE child_rank <= ?
ORDER BY parent_value, child_rank
""",
        values + [child_limit],
    ).fetchall()
    return [{parent_dimension: row[0], child_dimension: row[1], metric_name: row[2]} for row in rows]


def _slice_ranked_rows(rows: list[dict[str, Any]], params: dict[str, Any]) -> list[dict[str, Any]]:
    target = params.get("rank_target")
    if isinstance(target, dict) and target.get("value") not in (None, "", [], {}):
        dimension = str(target.get("dimension") or params.get("dimension") or "")
        target_value = str(target.get("value"))
        for rank, row in enumerate(rows, start=1):
            if dimension in row and str(row.get(dimension)) == target_value:
                ranked = dict(row)
                ranked["rank"] = rank
                return [ranked]
        return []
    rank_position = int(params.get("rank_position") or 0)
    if rank_position > 0:
        return rows[rank_position - 1 : rank_position]
    return rows[: int(params.get("limit") or 1)]


def _attach_metric_spec_columns_sql(
    conn: sqlite3.Connection,
    rows: list[dict[str, Any]],
    dimension: str,
    specs: list[dict[str, str]],
    *,
    where_sql: str = "",
    values: list[Any] | None = None,
) -> list[dict[str, Any]]:
    if not rows or not specs:
        return rows
    supplemental = _metric_spec_aggregation_sql(conn, specs, dimension=dimension, where_sql=where_sql, values=values)
    if not isinstance(supplemental, list):
        return rows
    by_dimension = {row.get(dimension): row for row in supplemental if isinstance(row, dict)}
    merged: list[dict[str, Any]] = []
    for row in rows:
        enriched = dict(row)
        extra = by_dimension.get(row.get(dimension), {})
        for spec in specs:
            name = str(spec.get("name") or "").strip()
            if name and name not in enriched and name in extra:
                enriched[name] = extra[name]
        merged.append(enriched)
    return merged


def _with_candidate_topn_filter_sql(where_sql: str, values: list[Any], params: dict[str, Any]) -> tuple[str, list[Any]]:
    candidate_filter = params.get("candidate_filter")
    if not isinstance(candidate_filter, dict) or not candidate_filter:
        return where_sql, values
    dimension = str(candidate_filter.get("dimension") or "")
    if not dimension:
        return where_sql, values
    if str(candidate_filter.get("operation") or "") == "growth_ranking":
        time_column = str(candidate_filter.get("time_column") or "")
        metric = str(candidate_filter.get("metric") or "")
        if not time_column or not metric:
            return where_sql, values
        aggregation = str(candidate_filter.get("aggregation") or "sum")
        growth_mode = str(candidate_filter.get("growth_mode") or "rate")
        growth_sort_expr = "growth_rate" if growth_mode == "rate" else "growth_delta"
        sort_order = "ASC" if str(candidate_filter.get("sort_order") or "desc") == "asc" else "DESC"
        limit = int(candidate_filter.get("limit") or 1)
        candidate_filters = candidate_filter.get("filters")
        if isinstance(candidate_filters, dict) and candidate_filters:
            candidate_where_sql, candidate_values = _where_from_filters(candidate_filters)
        else:
            candidate_where_sql, candidate_values = where_sql, values
        period_expr = _sql_period_expr(time_column)
        metric_expr = _sql_metric_agg_expr(metric, aggregation)
        subquery = f"""
WITH period_values AS (
  SELECT
    {_quote_identifier(dimension)} AS dimension_value,
    {period_expr} AS period_value,
    {metric_expr} AS metric_value
  FROM analysis_table{candidate_where_sql}
  GROUP BY dimension_value, period_value
),
ranked AS (
  SELECT
    dimension_value,
    period_value,
    metric_value,
    ROW_NUMBER() OVER (PARTITION BY dimension_value ORDER BY period_value ASC) AS rn_asc,
    ROW_NUMBER() OVER (PARTITION BY dimension_value ORDER BY period_value DESC) AS rn_desc,
    COUNT(*) OVER (PARTITION BY dimension_value) AS period_count
  FROM period_values
  WHERE dimension_value IS NOT NULL AND period_value IS NOT NULL
),
start_rows AS (
  SELECT dimension_value, metric_value AS start_value
  FROM ranked
  WHERE rn_asc = 1 AND period_count >= 2
),
end_rows AS (
  SELECT dimension_value, metric_value AS end_value
  FROM ranked
  WHERE rn_desc = 1 AND period_count >= 2
),
growth_rows AS (
  SELECT
    s.dimension_value,
    (e.end_value - s.start_value) AS growth_delta,
    CASE
      WHEN ABS(s.start_value) < 0.000000000001 THEN 0.0
      ELSE (e.end_value - s.start_value) / ABS(s.start_value)
    END AS growth_rate
  FROM start_rows s
  JOIN end_rows e ON s.dimension_value = e.dimension_value
)
SELECT dimension_value FROM growth_rows
ORDER BY {growth_sort_expr} {sort_order}
LIMIT ?
"""
        candidate_clause = f"{_quote_identifier(dimension)} IN ({subquery})"
        if where_sql:
            return f"{where_sql} AND {candidate_clause}", values + candidate_values + [limit]
        return f" WHERE {candidate_clause}", candidate_values + [limit]
    derived_metric = candidate_filter.get("derived_metric")
    metric = candidate_filter.get("metric")
    aggregation = str(candidate_filter.get("aggregation") or "sum")
    sort_order = "ASC" if str(candidate_filter.get("sort_order") or "desc") == "asc" else "DESC"
    limit = int(candidate_filter.get("limit") or 1)
    if isinstance(derived_metric, dict) and derived_metric:
        candidate_expr = _derived_ratio_sql_expression(derived_metric)
    elif aggregation == "count" or metric is None:
        candidate_expr = "COUNT(*)"
    elif aggregation in {"nunique", "distinct_count"}:
        candidate_expr = f"COUNT(DISTINCT {_quote_identifier(str(metric))})"
    else:
        candidate_expr = f"{_sql_agg_func(aggregation)}({_quote_identifier(str(metric))})"
    candidate_filters = candidate_filter.get("filters")
    if isinstance(candidate_filters, dict) and candidate_filters:
        candidate_where_sql, candidate_values = _where_from_filters(candidate_filters)
    else:
        candidate_where_sql, candidate_values = where_sql, values
    subquery = (
        f"SELECT {_quote_identifier(dimension)} FROM analysis_table{candidate_where_sql} "
        f"GROUP BY {_quote_identifier(dimension)} ORDER BY candidate_value {sort_order} LIMIT ?"
    )
    subquery = subquery.replace("ORDER BY candidate_value", f"ORDER BY {candidate_expr}")
    candidate_clause = f"{_quote_identifier(dimension)} IN ({subquery})"
    if where_sql:
        return f"{where_sql} AND {candidate_clause}", values + candidate_values + [limit]
    return f" WHERE {candidate_clause}", candidate_values + [limit]


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


def _grouped_aggregation_sql(
    conn: sqlite3.Connection,
    dimension: str,
    metric: str | None,
    aggregation: str,
    *,
    where_sql: str = "",
    values: list[Any] | None = None,
) -> list[dict[str, Any]]:
    values = values or []
    if aggregation == "count" or metric is None:
        rows = conn.execute(
            f"SELECT {_quote_identifier(dimension)}, COUNT(*) AS count FROM analysis_table{where_sql} GROUP BY {_quote_identifier(dimension)}",
            values,
        ).fetchall()
        return [{dimension: row[0], "count": row[1]} for row in rows]
    if aggregation in {"nunique", "distinct_count"}:
        rows = conn.execute(
            f"SELECT {_quote_identifier(dimension)}, COUNT(DISTINCT {_quote_identifier(str(metric))}) AS count "
            f"FROM analysis_table{where_sql} GROUP BY {_quote_identifier(dimension)}",
            values,
        ).fetchall()
        return [{dimension: row[0], "count": row[1]} for row in rows]
    sql_func = _sql_agg_func(aggregation)
    q_dimension = _quote_identifier(dimension)
    q_metric = _quote_identifier(str(metric))
    rows = conn.execute(
        f"SELECT {q_dimension}, {sql_func}({q_metric}) AS {q_metric} FROM analysis_table{where_sql} GROUP BY {q_dimension}",
        values,
    ).fetchall()
    return [{dimension: row[0], metric: row[1]} for row in rows]


def _grouped_derived_ratio_sql(
    conn: sqlite3.Connection,
    dimension: str,
    derived_metric: dict[str, Any],
    *,
    where_sql: str = "",
    values: list[Any] | None = None,
) -> list[dict[str, Any]]:
    values = values or []
    metric_name = str(derived_metric.get("name") or "ratio")
    q_dimension = _quote_identifier(dimension)
    rows = conn.execute(
        f"SELECT {q_dimension}, {_derived_ratio_sql_expression(derived_metric)} AS value "
        f"FROM analysis_table{where_sql} GROUP BY {q_dimension}",
        values,
    ).fetchall()
    return [{dimension: row[0], metric_name: row[1]} for row in rows]


def _derived_ratio_sql(
    conn: sqlite3.Connection,
    derived_metric: dict[str, Any],
    *,
    where_sql: str = "",
    values: list[Any] | None = None,
) -> dict[str, float]:
    values = values or []
    metric_name = str(derived_metric.get("name") or "ratio")
    value = conn.execute(
        f"SELECT {_derived_ratio_sql_expression(derived_metric)} FROM analysis_table{where_sql}",
        values,
    ).fetchone()[0]
    return {metric_name: float(value or 0.0)}


def _derived_ratio_sql_expression(derived_metric: dict[str, Any]) -> str:
    numerator = str(derived_metric.get("numerator") or "")
    denominator = str(derived_metric.get("denominator") or "")
    if not numerator or not denominator:
        raise ValueError("Derived ratio metric requires numerator and denominator columns.")
    q_numerator = _quote_identifier(numerator)
    q_denominator = _quote_identifier(denominator)
    denominator_sum = f"COALESCE(SUM(CAST({q_denominator} AS REAL)), 0)"
    numerator_sum = f"COALESCE(SUM(CAST({q_numerator} AS REAL)), 0)"
    return f"CASE WHEN {denominator_sum} = 0 THEN 0.0 ELSE {numerator_sum} / {denominator_sum} END"


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
        if isinstance(expected, dict) and ("year" in expected or "month" in expected or "month_range" in expected):
            clause, clause_values = _date_part_filter_sql(str(column), expected)
            if clause:
                where.append(clause)
                values.extend(clause_values)
            continue
        if isinstance(expected, dict) and "operator" in expected:
            operator = str(expected.get("operator") or "=").strip()
            if operator not in {">", "<", ">=", "<=", "="}:
                operator = "="
            q_column = _quote_identifier(str(column))
            where.append(f"CAST({q_column} AS REAL) {operator} ?")
            values.append(float(expected.get("value") or 0))
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
        if isinstance(expected, (list, tuple, set)):
            items = [item for item in expected if item not in (None, "")]
            if not items:
                where.append("1 = 0")
                continue
            placeholders = ", ".join("?" for _ in items)
            where.append(f"{_quote_identifier(str(column))} IN ({placeholders})")
            values.extend(items)
            continue
        where.append(f"{_quote_identifier(str(column))} = ?")
        values.append(expected)
    return (" WHERE " + " AND ".join(where) if where else ""), values


def _date_part_filter_sql(column: str, expected: dict[str, Any]) -> tuple[str, list[Any]]:
    q_column = _sql_date_expr(column)
    clauses: list[str] = []
    values: list[Any] = []
    if expected.get("year") is not None:
        clauses.append(f"CAST(strftime('%Y', {q_column}) AS INTEGER) = ?")
        values.append(int(expected["year"]))
    if expected.get("month") is not None:
        clauses.append(f"CAST(strftime('%m', {q_column}) AS INTEGER) = ?")
        values.append(int(expected["month"]))
    if expected.get("month_range"):
        start, end = expected["month_range"]
        clauses.append(f"CAST(strftime('%m', {q_column}) AS INTEGER) BETWEEN ? AND ?")
        values.extend([int(start), int(end)])
    return " AND ".join(clauses), values


def _sql_date_expr(column: str) -> str:
    q_column = _quote_identifier(column)
    return f"date(CASE WHEN {q_column} GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]' THEN {q_column} || '-01' ELSE {q_column} END)"


def _sql_period_expr(column: str) -> str:
    return f"strftime('%Y-%m', {_sql_date_expr(column)})"


def _sql_metric_agg_expr(metric: str, aggregation: str) -> str:
    q_metric = _quote_identifier(metric)
    if aggregation in {"nunique", "distinct_count"}:
        return f"COUNT(DISTINCT {q_metric})"
    if aggregation == "count":
        return f"COUNT({q_metric})"
    return f"{_sql_agg_func(aggregation)}(CAST({q_metric} AS REAL))"


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
