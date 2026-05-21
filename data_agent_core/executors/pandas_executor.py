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
        rows = [{"answer": value}]
        return ExecutionResult(
            backend="pandas",
            success=True,
            columns=["answer"],
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
    if op == "top_count":
        return _top_count(context["payments"], filters, params)
    if op == "group_average":
        return _group_average(context["payments"], filters, params)

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
            month=int(filters["month"]),
        )
        return {"card_scheme": aci, "fee": delta, "candidates": candidates}
    raise ValueError(f"Unsupported operation: {op}")


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
