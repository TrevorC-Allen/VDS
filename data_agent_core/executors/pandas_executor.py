"""Pandas and rule-engine executor for framework-neutral analysis plans."""

from __future__ import annotations

import time
from typing import Any

import pandas as pd

from data_agent_core.contracts.analysis_contracts import AnalysisPlan
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.core.dabstep_fee_engine import DabstepFeeEngine
from data_agent_core.errors.error_result import ErrorResult
from data_agent_core.errors.error_types import PANDAS_EXECUTION_ERROR


def execute_plan(plan: AnalysisPlan, context: dict[str, Any]) -> ExecutionResult:
    """Execute an AnalysisPlan without reinterpreting the original question."""

    start = time.perf_counter()
    try:
        value = _execute_value(plan, context)
        columns, rows = _result_rows(value)
        return ExecutionResult(
            backend="pandas",
            success=True,
            columns=columns,
            rows=rows,
            value=value,
            summary=f"Executed operation {plan.logic_form.operation}.",
            latency_ms=(time.perf_counter() - start) * 1000,
        )
    except Exception as exc:  # noqa: BLE001 - keep failures structured
        return ExecutionResult(
            backend="pandas",
            success=False,
            latency_ms=(time.perf_counter() - start) * 1000,
            errors=[
                ErrorResult(
                    error_type=PANDAS_EXECUTION_ERROR,
                    error_message=str(exc),
                    failed_step=plan.logic_form.operation,
                    recoverable=True,
                    suggested_fix="Inspect the logic form, context files, and field mappings.",
                )
            ],
        )


def _execute_value(plan: AnalysisPlan, context: dict[str, Any]) -> Any:
    logic = plan.logic_form
    op = logic.operation
    filters = logic.filters
    params = logic.parameters

    if op == "not_applicable":
        return "Not Applicable"
    if op == "detail_lookup":
        return _detail_lookup(context["tables"], params)
    if op == "filtering":
        return _filtering(context["tables"], params)
    if op == "aggregation":
        return _aggregation(context["tables"], params)
    if op == "ranking":
        return _ranking(context["tables"], params)
    if op == "rank_by_metric":
        return _rank_by_metric(context["payments"] if "payments" in context else _table(context["tables"], params.get("table")), logic)
    if op == "top_count":
        return _top_count(context["payments"], filters, params)
    if op == "group_average":
        return _group_average(context["payments"], filters, params)
    if op == "fraud_rate_comparison":
        return _fraud_rate_comparison(context["payments"], filters, params)

    engine = _fee_engine(context)
    if op == "average_fee_for_filters":
        mcc = _mcc_from_filter(engine, filters)
        return engine.average_fee_for_rule_filters(
            transaction_value=float(params["transaction_value"]),
            card_scheme=str(filters["card_scheme"]),
            account_type=filters.get("account_type"),
            is_credit=filters.get("is_credit"),
            merchant_category_code=mcc,
        )
    if op == "fee_ids_for_filters":
        return engine.fee_ids_for_filters(
            account_type=filters.get("account_type"),
            aci=filters.get("aci"),
        )
    if op == "applicable_fee_ids":
        return engine.applicable_fee_ids_for_merchant_period(
            str(filters["merchant"]),
            year=int(filters.get("year") or 2023),
            month=filters.get("month"),
            day_of_year=filters.get("day_of_year"),
        )
    if op == "total_fees":
        return engine.total_fees(
            str(filters["merchant"]),
            year=int(filters.get("year") or 2023),
            month=filters.get("month"),
            day_of_year=filters.get("day_of_year"),
        )
    if op == "fee_rate_delta":
        return engine.fee_rate_delta(
            str(filters["merchant"]),
            year=int(filters.get("year") or 2023),
            month=filters.get("month"),
            fee_id=int(params["fee_id"]),
            new_rate=int(params["new_rate"]),
        )
    if op == "card_scheme_steering":
        scheme, total, candidates = engine.card_scheme_steering(
            str(filters["merchant"]),
            year=int(filters.get("year") or 2023),
            month=filters.get("month"),
            objective=str(params["objective"]),
        )
        return {"card_scheme": scheme, "fee": total, "candidates": candidates}
    if op == "cheapest_card_scheme_for_transaction":
        scheme, fee, candidates = engine.cheapest_card_scheme_for_transaction_value(
            transaction_value=float(params["transaction_value"]),
            objective=str(params.get("objective") or "minimum"),
        )
        return {"card_scheme": scheme, "fee": fee, "candidates": candidates}
    if op == "fee_restriction_affected_merchants":
        return engine.fee_restriction_affected_merchants(
            fee_id=int(params["fee_id"]),
            new_account_type=filters.get("new_account_type"),
            year=int(filters.get("year") or 2023),
        )
    if op == "mcc_change_delta":
        return engine.mcc_change_delta(
            str(filters["merchant"]),
            year=int(filters.get("year") or 2023),
            month=filters.get("month"),
            new_mcc=int(params["new_mcc"]),
        )
    if op == "best_fraud_aci_choice":
        aci, delta, candidates = engine.best_fraud_aci_choice(
            str(filters["merchant"]),
            year=int(filters.get("year") or 2023),
            month=filters.get("month"),
        )
        return {"card_scheme": aci, "fee": delta, "candidates": candidates}
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


def _table(tables: dict[str, pd.DataFrame], name: str | None = None) -> pd.DataFrame:
    if name and name in tables:
        return tables[name]
    if not tables:
        raise ValueError("No tables available for execution.")
    return max(tables.values(), key=lambda df: (len(df), len(df.columns)))


def _detail_lookup(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> list[dict[str, Any]]:
    data = _table(tables, params.get("table"))
    return data.head(int(params.get("limit") or 20)).to_dict(orient="records")


def _filtering(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> list[dict[str, Any]]:
    data = _table(tables, params.get("table"))
    for condition in params.get("conditions") or []:
        column = condition.get("column")
        if column not in data.columns:
            continue
        data = _apply_condition(data, str(column), str(condition.get("operator") or "="), condition.get("value"))
    return data.head(int(params.get("limit") or 20)).to_dict(orient="records")


def _aggregation(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> Any:
    data = _table(tables, params.get("table"))
    metric = params.get("metric")
    dimension = params.get("dimension")
    aggregation = str(params.get("aggregation") or "sum")
    if dimension:
        return _aggregate_grouped(data, str(dimension), None if metric is None else str(metric), aggregation)
    return _aggregate_series(data, None if metric is None else str(metric), aggregation)


def _ranking(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> list[dict[str, Any]]:
    data = _table(tables, params.get("table"))
    dimension = params.get("dimension")
    if not dimension:
        raise ValueError("Ranking requires a dimension column.")
    rows = _aggregate_grouped(
        data,
        str(dimension),
        None if params.get("metric") is None else str(params.get("metric")),
        str(params.get("aggregation") or "sum"),
    )
    metric_column = next((key for key in rows[0] if key != str(dimension)), "value") if rows else "value"
    reverse = str(params.get("sort_order") or "desc") == "desc"
    rows.sort(key=lambda row: row.get(metric_column), reverse=reverse)
    return rows[: int(params.get("limit") or 1)]


def _aggregate_grouped(data: pd.DataFrame, dimension: str, metric: str | None, aggregation: str) -> list[dict[str, Any]]:
    if dimension not in data.columns:
        raise ValueError(f"Unknown dimension column: {dimension}")
    if aggregation == "count" or metric is None:
        result = data.groupby(dimension, dropna=True).size().reset_index(name="count")
        return result.to_dict(orient="records")
    if metric not in data.columns:
        raise ValueError(f"Unknown metric column: {metric}")
    result = data.groupby(dimension, dropna=True)[metric].agg(aggregation).reset_index()
    return result.to_dict(orient="records")


def _aggregate_series(data: pd.DataFrame, metric: str | None, aggregation: str) -> Any:
    if aggregation == "count" or metric is None:
        return int(len(data))
    if metric not in data.columns:
        raise ValueError(f"Unknown metric column: {metric}")
    series = data[metric]
    if aggregation == "mean":
        return float(series.mean())
    if aggregation == "max":
        return float(series.max())
    if aggregation == "min":
        return float(series.min())
    return float(series.sum())


def _apply_condition(data: pd.DataFrame, column: str, operator: str, raw_value: Any) -> pd.DataFrame:
    series = data[column]
    value = _coerce_filter_value(raw_value, series)
    if operator == ">":
        return data[series > value]
    if operator == "<":
        return data[series < value]
    if operator == ">=":
        return data[series >= value]
    if operator == "<=":
        return data[series <= value]
    return data[series.astype(str) == str(value)]


def _coerce_filter_value(value: Any, series: pd.Series) -> Any:
    if pd.api.types.is_numeric_dtype(series):
        return float(value)
    return value


def _top_count(df: pd.DataFrame, filters: dict[str, Any], params: dict[str, Any]) -> Any:
    data = df
    for column, expected in filters.items():
        if expected is not None:
            data = data[data[column] == expected]
    group_by = str(params["group_by"])
    counts = data[group_by].value_counts(dropna=True)
    if counts.empty:
        return "Not Applicable"
    top_value = str(counts.index[0])
    options = params.get("options") or {}
    if options:
        for letter, option_value in options.items():
            if option_value == top_value:
                return f"{letter}. {top_value}"
    return top_value


def _rank_by_metric(df: pd.DataFrame, logic: Any) -> dict[str, Any]:
    params = logic.parameters
    group_by = str(logic.group_by or params["group_by"])
    metric = str(logic.metric or params.get("metric") or "count")
    objective = str(logic.objective or params.get("objective") or "maximum")
    options = dict(logic.options or params.get("options") or {})
    sort_desc = objective != "minimum"
    if metric == "fraud_volume_rate":
        candidate_table = _fraud_volume_rate_by_dimension(df, group_by, options)
        metric_column = "fraud_volume_rate"
    elif metric == "fraud_transaction_rate":
        candidate_table = _fraud_transaction_rate_by_dimension(df, group_by, options)
        metric_column = "fraud_transaction_rate"
    else:
        return {"answer": _top_count(df, logic.filters, {"group_by": group_by, "options": options}), "candidate_table": []}
    if not candidate_table:
        return {"answer": "Not Applicable", "candidate_table": [], "metric": metric}
    candidate_table.sort(key=lambda row: row[metric_column], reverse=sort_desc)
    selected = candidate_table[0]
    selected_value = str(selected[group_by])
    answer = selected_value
    selected_option = None
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
        "objective": objective,
        "candidate_table": candidate_table,
    }


def _fraud_volume_rate_by_dimension(df: pd.DataFrame, group_by: str, options: dict[str, Any]) -> list[dict[str, Any]]:
    data = _limit_to_option_values(df, group_by, options)
    grouped = data.groupby(group_by, dropna=True)
    rows: list[dict[str, Any]] = []
    for value, group in grouped:
        total_volume = float(group["eur_amount"].sum())
        fraudulent_volume = float(group.loc[group["has_fraudulent_dispute"].astype(bool), "eur_amount"].sum())
        fraud_volume_rate = 0.0 if total_volume == 0 else fraudulent_volume / total_volume
        rows.append(
            {
                group_by: str(value),
                "fraudulent_volume": fraudulent_volume,
                "total_volume": total_volume,
                "fraud_volume_rate": fraud_volume_rate,
            }
        )
    return rows


def _fraud_transaction_rate_by_dimension(df: pd.DataFrame, group_by: str, options: dict[str, Any]) -> list[dict[str, Any]]:
    data = _limit_to_option_values(df, group_by, options)
    grouped = data.groupby(group_by, dropna=True)
    rows: list[dict[str, Any]] = []
    for value, group in grouped:
        transaction_count = int(len(group))
        fraudulent_count = int(group["has_fraudulent_dispute"].astype(bool).sum())
        fraud_transaction_rate = 0.0 if transaction_count == 0 else fraudulent_count / transaction_count
        rows.append(
            {
                group_by: str(value),
                "fraudulent_transactions": fraudulent_count,
                "transaction_count": transaction_count,
                "fraud_transaction_rate": fraud_transaction_rate,
            }
        )
    return rows


def _limit_to_option_values(df: pd.DataFrame, group_by: str, options: dict[str, Any]) -> pd.DataFrame:
    if not options:
        return df
    option_values = {str(value) for value in options.values()}
    return df[df[group_by].astype(str).isin(option_values)]


def _group_average(df: pd.DataFrame, filters: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    data = df
    if filters.get("merchant"):
        data = data[data["merchant"] == filters["merchant"]]
    if filters.get("card_scheme"):
        data = data[data["card_scheme"] == filters["card_scheme"]]
    if filters.get("year"):
        data = data[data["year"] == int(filters["year"])]
    if filters.get("month_range"):
        start_month, end_month = filters["month_range"]
        months = pd.to_datetime(data["day_of_year"].astype(int) - 1, unit="D", origin=f"{int(filters.get('year') or 2023)}-01-01").dt.month
        data = data[(months >= start_month) & (months <= end_month)]
    group_by = str(params["group_by"])
    metric = str(params["metric"])
    result = data.groupby(group_by, dropna=True)[metric].mean().reset_index()
    result = result.sort_values(metric, ascending=True)
    return result.to_dict(orient="records")


def _fraud_rate_comparison(df: pd.DataFrame, filters: dict[str, Any], params: dict[str, Any]) -> str:
    data = df
    if filters.get("year"):
        data = data[data["year"] == int(filters["year"])]
    dimension = str(params["dimension"])
    left_value = params["left_value"]
    right_value = params["right_value"]
    operator = str(params.get("operator") or "higher_than")
    left_rate = _fraud_rate(data[data[dimension] == left_value])
    right_rate = _fraud_rate(data[data[dimension] == right_value])
    if left_rate is None or right_rate is None:
        return "Not Applicable"
    result = left_rate > right_rate if operator == "higher_than" else left_rate < right_rate
    return "yes" if result else "no"


def _fraud_rate(data: pd.DataFrame) -> float | None:
    if data.empty:
        return None
    return float(data["has_fraudulent_dispute"].astype(bool).mean())


def _fee_engine(context: dict[str, Any]) -> DabstepFeeEngine:
    if "_fee_engine" not in context:
        context["_fee_engine"] = DabstepFeeEngine(context["context_dir"])
    return context["_fee_engine"]


def _mcc_from_filter(engine: DabstepFeeEngine, filters: dict[str, Any]) -> int | None:
    if filters.get("merchant_category_code") is not None:
        return int(filters["merchant_category_code"])
    if filters.get("mcc_description"):
        return engine.mcc_for_description(str(filters["mcc_description"]))
    return None
