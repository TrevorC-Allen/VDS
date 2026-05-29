"""Pandas and rule-engine executor for framework-neutral analysis plans."""

from __future__ import annotations

import time
from typing import Any

import pandas as pd

from data_agent_core.contracts.analysis_contracts import AnalysisPlan
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.core.dabstep_fee_engine import DabstepFeeEngine
from data_agent_core.core.data_quality import build_data_quality_report, report_to_dict
from data_agent_core.errors.error_result import ErrorResult
from data_agent_core.errors.error_types import PANDAS_EXECUTION_ERROR
from data_agent_core.executors.chinese_retail_executor import execute_chinese_retail_operation, is_chinese_retail_operation
from data_agent_core.executors.vds_bi_executor import execute_vds_bi_operation, is_vds_bi_operation


NO_MATCHING_RECORDS = "没有匹配记录"


def execute_plan(plan: AnalysisPlan, context: dict[str, Any]) -> ExecutionResult:
    """Execute an AnalysisPlan without reinterpreting the original question."""

    start = time.perf_counter()
    try:
        value = _execute_value(plan, context)
        columns, rows = _result_rows(value)
        warnings = _join_warnings(plan.logic_form.parameters)
        debug = _join_debug(plan.logic_form.parameters)
        return ExecutionResult(
            backend="pandas",
            success=True,
            columns=columns,
            rows=rows,
            value=value,
            summary=_execution_summary(plan.logic_form.operation, debug),
            latency_ms=(time.perf_counter() - start) * 1000,
            warnings=warnings,
            debug=debug,
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

    if is_chinese_retail_operation(op):
        return execute_chinese_retail_operation(logic, context)
    if is_vds_bi_operation(op):
        return execute_vds_bi_operation(logic, context)
    if op == "not_applicable":
        return "Not Applicable"
    if op == "data_quality_report":
        report = report_to_dict(build_data_quality_report(_tables_for_quality(context), generated_from="analysis_request")) or {}
        report["answer"] = report.get("summary") or "数据质量扫描完成。"
        return report
    if op == "schema_field_lookup":
        return _schema_field_lookup(_analysis_dataframe(context, params), params)
    if op == "detail_lookup":
        return _detail_lookup(_analysis_dataframe(context, params), params)
    if op == "filtering":
        return _filtering(_analysis_dataframe(context, params), params)
    if op == "aggregation":
        return _aggregation_dataframe(_analysis_dataframe(context, params), filters, params)
    if op == "ranking":
        return _ranking_dataframe(_analysis_dataframe(context, params), params)
    if op == "row_count":
        return _row_count(_analysis_dataframe(context, params), filters)
    if op == "distinct_count":
        return _distinct_count(_analysis_dataframe(context, params), filters, params)
    if op == "metric_per_distinct_entity":
        return _metric_per_distinct_entity(_analysis_dataframe(context, params), filters, params)
    if op == "repeat_entity_percentage":
        return _repeat_entity_percentage(_analysis_dataframe(context, params), filters, params)
    if op == "repeat_entity_count":
        return _repeat_entity_count(_analysis_dataframe(context, params), filters, params)
    if op == "outlier_count":
        return _outlier_count(_analysis_dataframe(context, params), filters, params)
    if op == "top_outlier_group":
        return _top_outlier_group(_analysis_dataframe(context, params), filters, params)
    if op == "null_check":
        return _null_check(_analysis_dataframe(context, params), filters, params)
    if op == "missing_columns_choice":
        return _missing_columns_choice(_analysis_dataframe(context, params), params)
    if op == "top_k_share":
        return _top_k_share(_analysis_dataframe(context, params), filters, params)
    if op == "quantile_percentage":
        return _quantile_percentage(_analysis_dataframe(context, params), filters, params)
    if op == "outlier_target_percentage":
        return _outlier_target_percentage(_analysis_dataframe(context, params), filters, params)
    if op == "outlier_rate_comparison":
        return _outlier_rate_comparison(_analysis_dataframe(context, params), filters, params)
    if op == "correlation_threshold":
        return _correlation_threshold(_analysis_dataframe(context, params), filters, params)
    if op == "worst_fraud_segment":
        return _worst_fraud_segment(_analysis_dataframe(context, params), filters, params)
    if op == "filtered_metric_ranking":
        return _filtered_metric_ranking(_analysis_dataframe(context, params), filters, params)
    if op == "rank_by_metric":
        return _rank_by_metric(context["payments"] if "payments" in context else _table(context["tables"], params.get("table")), logic)
    if op == "field_values":
        df = _analysis_dataframe(context, params)
        field = str(params.get("field") or "")
        if field in df.columns:
            return _field_values(df, params)
        if "context_dir" in context:
            return _fee_engine(context).field_values(field)
        return _field_values(df, params)
    if op == "boolean_percentage":
        return _boolean_percentage(_analysis_dataframe(context, params), filters, params)
    if op == "boolean_count_ratio":
        return _boolean_count_ratio(_analysis_dataframe(context, params), filters, params)
    if op == "duplicate_check":
        return _duplicate_check(_analysis_dataframe(context, params), params)
    if op == "top_count":
        return _top_count(_analysis_dataframe(context, params), filters, params)
    if op == "group_average":
        return _group_average(context["payments"], filters, params)
    if op == "fraud_rate_comparison":
        return _fraud_rate_comparison(context["payments"], filters, params)
    if op == "fraud_rate_filtered":
        return _fraud_rate_filtered(context["payments"], filters)
    if op == "fraud_rate_fluctuation":
        return _fraud_rate_fluctuation(context["payments"], filters, params)

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
            _merchant_filter_or_default(engine, filters),
            year=int(filters.get("year") or 2023),
            month=filters.get("month"),
            day_of_year=filters.get("day_of_year"),
        )
    if op == "total_fees":
        return engine.total_fees(
            _merchant_filter_or_default(engine, filters),
            year=int(filters.get("year") or 2023),
            month=filters.get("month"),
            day_of_year=filters.get("day_of_year"),
        )
    if op == "fee_rate_delta":
        return engine.fee_rate_delta(
            _merchant_filter_or_default(engine, filters),
            year=int(filters.get("year") or 2023),
            month=filters.get("month"),
            fee_id=int(params["fee_id"]),
            new_rate=int(params["new_rate"]),
        )
    if op == "card_scheme_steering":
        scheme, total, candidates = engine.card_scheme_steering(
            _merchant_filter_or_default(engine, filters),
            year=int(filters.get("year") or 2023),
            month=filters.get("month"),
            objective=str(params["objective"]),
        )
        return {
            "card_scheme": scheme,
            "fee": total,
            "selected": scheme,
            "candidate_table": _fee_candidate_table("card_scheme", candidates),
            "candidates": candidates,
        }
    if op == "cheapest_card_scheme_for_transaction":
        scheme, fee, candidates = engine.cheapest_card_scheme_for_transaction_value(
            transaction_value=float(params["transaction_value"]),
            objective=str(params.get("objective") or "minimum"),
        )
        return {
            "card_scheme": scheme,
            "fee": fee,
            "selected": scheme,
            "candidate_table": _fee_candidate_table("card_scheme", candidates),
            "candidates": candidates,
        }
    if op == "fee_restriction_affected_merchants":
        return engine.fee_restriction_affected_merchants(
            fee_id=int(params["fee_id"]),
            new_account_type=filters.get("new_account_type"),
            year=int(filters.get("year") or 2023),
        )
    if op == "mcc_change_delta":
        return engine.mcc_change_delta(
            _merchant_filter_or_default(engine, filters),
            year=int(filters.get("year") or 2023),
            month=filters.get("month"),
            new_mcc=int(params["new_mcc"]),
        )
    if op == "best_fraud_aci_choice":
        aci, delta, candidates = engine.best_fraud_aci_choice(
            _merchant_filter_or_default(engine, filters),
            year=int(filters.get("year") or 2023),
            month=filters.get("month"),
        )
        return {
            "aci": aci,
            "fee": delta,
            "selected": aci,
            "candidate_table": _fee_candidate_table("aci", candidates),
            "candidates": candidates,
        }
    if op == "aci_fee_extreme":
        aci, fee, candidates = engine.aci_fee_extreme_for_transaction_value(
            transaction_value=float(params["transaction_value"]),
            card_scheme=filters.get("card_scheme"),
            is_credit=filters.get("is_credit"),
            objective=str(params.get("objective") or logic.objective or "maximum"),
        )
        return {
            "aci": aci,
            "fee": fee,
            "selected": aci,
            "candidate_table": _fee_candidate_table("aci", candidates),
            "candidates": candidates,
        }
    if op == "fee_extreme_by_dimension":
        selected, fee, candidates = engine.fee_extreme_by_dimension(
            transaction_value=float(params["transaction_value"]),
            dimension=str(params.get("dimension") or logic.group_by or "merchant_category_code"),
            objective=str(params.get("objective") or logic.objective or "maximum"),
        )
        return {
            "answer": selected,
            "selected": selected,
            "fee": fee,
            "dimension": str(params.get("dimension") or logic.group_by or "merchant_category_code"),
            "objective": str(params.get("objective") or logic.objective or "maximum"),
            "candidate_table": candidates,
        }
    if op == "fee_factor_direction":
        return engine.fee_factor_direction(objective=str(params.get("objective") or "cheaper_when_increased"))
    if op == "fee_volume_threshold":
        return engine.fee_volume_threshold()
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
        candidate_table = value.get("candidate_table")
        if isinstance(candidate_table, list) and all(isinstance(row, dict) for row in candidate_table):
            columns: list[str] = []
            for row in candidate_table:
                for key in row:
                    if key not in columns:
                        columns.append(str(key))
            return columns, candidate_table
        return list(value.keys()), [value]
    return ["answer"], [{"answer": value}]


def _table(tables: dict[str, pd.DataFrame], name: str | None = None) -> pd.DataFrame:
    if name and name in tables:
        return tables[name]
    if not tables:
        raise ValueError("No tables available for execution.")
    return max(tables.values(), key=lambda df: (len(df), len(df.columns)))


def _tables_for_quality(context: dict[str, Any]) -> dict[str, pd.DataFrame]:
    if "tables" in context:
        return context["tables"]
    if "payments" in context:
        return {"payments": context["payments"]}
    raise ValueError("No tables available for data quality scan.")


def _analysis_dataframe(context: dict[str, Any], params: dict[str, Any]) -> pd.DataFrame:
    if "payments" in context:
        return context["payments"]
    tables = context["tables"]
    same_schema_union = params.get("same_schema_union")
    if isinstance(same_schema_union, dict) and same_schema_union:
        return _materialize_same_schema_union(tables, params, same_schema_union)
    join_plan = params.get("join_plan")
    if isinstance(join_plan, dict) and join_plan:
        return _materialize_join(tables, params, join_plan)
    return _table(tables, params.get("table"))


def _materialize_same_schema_union(tables: dict[str, pd.DataFrame], params: dict[str, Any], union_plan: dict[str, Any]) -> pd.DataFrame:
    """Concatenate same-schema source tables without inventing a join."""

    source_tables = [str(table_name) for table_name in union_plan.get("source_tables") or [] if str(table_name)]
    if not source_tables:
        raise ValueError("Same-schema union requires source_tables.")
    missing = [table_name for table_name in source_tables if table_name not in tables]
    if missing:
        raise ValueError("Same-schema union references unavailable table(s): " + ", ".join(missing))

    first_columns = [str(column) for column in tables[source_tables[0]].columns]
    first_signature = set(first_columns)
    frames: list[pd.DataFrame] = []
    row_counts: dict[str, int] = {}
    source_files: dict[str, str] = {}
    for table_name in source_tables:
        df = tables[table_name]
        columns = [str(column) for column in df.columns]
        if set(columns) != first_signature:
            raise ValueError("Same-schema union requires matching columns across source tables.")
        frame = df.copy()
        source_column = "__source_table"
        if source_column not in frame.columns:
            frame[source_column] = table_name
        file_column = "__source_file"
        source_file = str(df.attrs.get("source_file") or table_name)
        if file_column not in frame.columns:
            frame[file_column] = source_file
        frames.append(frame)
        row_counts[table_name] = int(len(df))
        source_files[table_name] = source_file

    union_df = pd.concat(frames, ignore_index=True, sort=False)
    summary = {
        "trusted": True,
        "source_tables": source_tables,
        "source_files": source_files,
        "row_counts": row_counts,
        "total_rows": int(len(union_df)),
        "columns": first_columns,
    }
    params["_same_schema_union_summary"] = summary
    return union_df


def _materialize_join(tables: dict[str, pd.DataFrame], params: dict[str, Any], join_plan: dict[str, Any]) -> pd.DataFrame:
    """Materialize trusted uploaded-table joins for analysis."""

    if not join_plan.get("trusted"):
        reason = str(join_plan.get("reason") or "Join plan is not trusted.")
        raise ValueError(f"Join required but not trusted: {reason}")
    if join_plan.get("many_to_many_risk"):
        raise ValueError("Join required but many-to-many risk is present; ask for join-key clarification.")

    steps = join_plan.get("steps")
    if isinstance(steps, list) and steps:
        return _materialize_join_steps(tables, params, steps)

    left_table = str(join_plan.get("left_table") or params.get("table") or "")
    right_table = str(join_plan.get("right_table") or "")
    left_key = str(join_plan.get("left_key") or "")
    right_key = str(join_plan.get("right_key") or "")
    if left_table not in tables or right_table not in tables:
        raise ValueError("Join plan references a table that is not available.")
    left = tables[left_table]
    right = tables[right_table]
    if left_key not in left.columns or right_key not in right.columns:
        raise ValueError("Join plan references a key column that is not available.")

    relationship = str(join_plan.get("relationship") or "many_to_one")
    validate = {"one_to_one": "1:1", "many_to_one": "m:1"}.get(relationship)
    if validate is None:
        raise ValueError(f"Unsupported join relationship for controlled executor: {relationship}")

    right_keys = set(right[right_key].dropna().astype(str))
    left_key_series = left[left_key].dropna().astype(str)
    unmatched_keys = sorted(set(left_key_series) - right_keys)
    joined = left.merge(
        right,
        how=str(join_plan.get("join_type") or "left"),
        left_on=left_key,
        right_on=right_key,
        suffixes=("", f"__{right_table}"),
        validate=validate,
    )
    summary = {
        "trusted": True,
        "left_table": left_table,
        "right_table": right_table,
        "left_key": left_key,
        "right_key": right_key,
        "join_type": str(join_plan.get("join_type") or "left"),
        "relationship": relationship,
        "left_rows": int(len(left)),
        "right_rows": int(len(right)),
        "joined_rows": int(len(joined)),
        "unmatched_left_key_count": int(len(unmatched_keys)),
        "unmatched_left_keys_sample": unmatched_keys[:10],
    }
    params["_join_execution_summary"] = summary
    return joined


def _materialize_join_steps(tables: dict[str, pd.DataFrame], params: dict[str, Any], steps: list[Any]) -> pd.DataFrame:
    normalized_steps = [step for step in steps if isinstance(step, dict)]
    if not normalized_steps:
        raise ValueError("Join steps are empty.")
    first_left = str(normalized_steps[0].get("left_table") or params.get("table") or "")
    if first_left not in tables:
        raise ValueError("Join steps reference a base table that is not available.")

    joined = tables[first_left].copy()
    summaries: list[dict[str, Any]] = []
    for step in normalized_steps:
        if not step.get("trusted"):
            reason = str(step.get("reason") or "Join step is not trusted.")
            raise ValueError(f"Join required but not trusted: {reason}")
        if step.get("many_to_many_risk"):
            raise ValueError("Join required but a join step has many-to-many risk; ask for join-key clarification.")
        right_table = str(step.get("right_table") or "")
        left_key = str(step.get("left_key") or "")
        right_key = str(step.get("right_key") or "")
        if right_table not in tables:
            raise ValueError("Join step references a right table that is not available.")
        if left_key not in joined.columns or right_key not in tables[right_table].columns:
            raise ValueError("Join step references a key column that is not available.")

        right = tables[right_table]
        relationship = str(step.get("relationship") or "many_to_one")
        validate = {"one_to_one": "1:1", "many_to_one": "m:1"}.get(relationship)
        if validate is None:
            raise ValueError(f"Unsupported join relationship for controlled executor: {relationship}")

        right_keys = set(right[right_key].dropna().astype(str))
        left_key_series = joined[left_key].dropna().astype(str)
        unmatched_keys = sorted(set(left_key_series) - right_keys)
        before_rows = int(len(joined))
        joined = joined.merge(
            right,
            how=str(step.get("join_type") or "left"),
            left_on=left_key,
            right_on=right_key,
            suffixes=("", f"__{right_table}"),
            validate=validate,
        )
        summaries.append(
            {
                "trusted": True,
                "left_table": str(step.get("left_table") or first_left),
                "right_table": right_table,
                "left_key": left_key,
                "right_key": right_key,
                "join_type": str(step.get("join_type") or "left"),
                "relationship": relationship,
                "left_rows": before_rows,
                "right_rows": int(len(right)),
                "joined_rows": int(len(joined)),
                "unmatched_left_key_count": int(len(unmatched_keys)),
                "unmatched_left_keys_sample": unmatched_keys[:10],
            }
        )

    params["_join_execution_summary"] = {
        "trusted": True,
        "left_table": summaries[0]["left_table"],
        "right_table": summaries[-1]["right_table"],
        "left_key": summaries[0]["left_key"],
        "right_key": summaries[0]["right_key"],
        "join_type": "left",
        "relationship": "multi_step",
        "left_rows": summaries[0]["left_rows"],
        "right_rows": summaries[-1]["right_rows"],
        "joined_rows": int(len(joined)),
        "unmatched_left_key_count": int(sum(step["unmatched_left_key_count"] for step in summaries)),
        "unmatched_left_keys_sample": [key for step in summaries for key in step["unmatched_left_keys_sample"]][:10],
        "steps": summaries,
    }
    return joined


def _join_debug(params: dict[str, Any]) -> dict[str, Any]:
    join_plan = params.get("join_plan")
    debug: dict[str, Any] = {}
    if isinstance(join_plan, dict) and join_plan:
        debug["join_plan"] = {
            key: join_plan.get(key)
            for key in (
                "trusted",
                "join_type",
                "left_table",
                "right_table",
                "left_key",
                "right_key",
                "relationship",
                "confidence",
                "overlap_rate",
                "many_to_many_risk",
                "reason",
                "steps",
            )
            if key in join_plan
        }
    if isinstance(params.get("_same_schema_union_summary"), dict):
        debug["same_schema_union_summary"] = params["_same_schema_union_summary"]
    if isinstance(params.get("_join_execution_summary"), dict):
        debug["join_execution_summary"] = params["_join_execution_summary"]
    return debug


def _join_warnings(params: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    summary = params.get("_join_execution_summary")
    if isinstance(summary, dict) and summary.get("unmatched_left_key_count"):
        warnings.append(
            "Join left some primary rows unmatched: "
            f"{summary['unmatched_left_key_count']} distinct key(s)."
        )
    join_plan = params.get("join_plan")
    if isinstance(join_plan, dict) and join_plan.get("many_to_many_risk"):
        warnings.append("Join plan has many-to-many risk and was not materialized.")
    return warnings


def _execution_summary(operation: str, debug: dict[str, Any]) -> str:
    if "same_schema_union_summary" in debug:
        summary = debug["same_schema_union_summary"]
        return (
            f"Executed operation {operation} after concatenating "
            f"{len(summary.get('source_tables') or [])} same-schema source tables."
        )
    if "join_execution_summary" in debug:
        summary = debug["join_execution_summary"]
        if isinstance(summary.get("steps"), list) and summary.get("steps"):
            return (
                f"Executed operation {operation} after materializing "
                f"{len(summary.get('steps') or [])} trusted join step(s)."
            )
        return (
            f"Executed operation {operation} after joining "
            f"{summary.get('left_table')} to {summary.get('right_table')}."
        )
    return f"Executed operation {operation}."


def _detail_lookup(data: pd.DataFrame, params: dict[str, Any]) -> list[dict[str, Any]]:
    return data.head(int(params.get("limit") or 20)).to_dict(orient="records")


def _filtering(data: pd.DataFrame, params: dict[str, Any]) -> list[dict[str, Any]]:
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


def _aggregation_dataframe(data: pd.DataFrame, filters: dict[str, Any], params: dict[str, Any]) -> Any:
    data = _apply_dataframe_filters(data, filters)
    derived_metric = params.get("derived_metric")
    if isinstance(derived_metric, dict) and derived_metric:
        dimension = params.get("dimension")
        if dimension:
            return _aggregate_derived_ratio_grouped(data, str(dimension), derived_metric)
        return _aggregate_derived_ratio(data, derived_metric)
    metric = params.get("metric")
    dimension = params.get("dimension")
    aggregation = str(params.get("aggregation") or "sum")
    if dimension:
        return _aggregate_grouped(data, str(dimension), None if metric is None else str(metric), aggregation)
    return _aggregate_series(data, None if metric is None else str(metric), aggregation)


def _ranking(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> list[dict[str, Any]]:
    data = _table(tables, params.get("table"))
    return _ranking_dataframe(data, params)


def _ranking_dataframe(data: pd.DataFrame, params: dict[str, Any]) -> list[dict[str, Any]]:
    dimension = params.get("dimension")
    if not dimension:
        raise ValueError("Ranking requires a dimension column.")
    derived_metric = params.get("derived_metric")
    if isinstance(derived_metric, dict) and derived_metric:
        rows = _aggregate_derived_ratio_grouped(data, str(dimension), derived_metric)
    else:
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


def _aggregate_derived_ratio_grouped(data: pd.DataFrame, dimension: str, derived_metric: dict[str, Any]) -> list[dict[str, Any]]:
    numerator = str(derived_metric.get("numerator") or "")
    denominator = str(derived_metric.get("denominator") or "")
    metric_name = str(derived_metric.get("name") or "ratio")
    if dimension not in data.columns:
        raise ValueError(f"Unknown dimension column: {dimension}")
    if numerator not in data.columns or denominator not in data.columns:
        raise ValueError("Derived ratio metric requires numerator and denominator columns.")
    working = data[[dimension, numerator, denominator]].copy()
    working[numerator] = pd.to_numeric(working[numerator], errors="coerce")
    working[denominator] = pd.to_numeric(working[denominator], errors="coerce")
    grouped = working.groupby(dimension, dropna=True)[[numerator, denominator]].sum().reset_index()
    grouped[metric_name] = grouped.apply(
        lambda row: 0.0 if float(row[denominator] or 0) == 0 else float(row[numerator]) / float(row[denominator]),
        axis=1,
    )
    return grouped[[dimension, metric_name]].to_dict(orient="records")


def _aggregate_derived_ratio(data: pd.DataFrame, derived_metric: dict[str, Any]) -> float:
    numerator = str(derived_metric.get("numerator") or "")
    denominator = str(derived_metric.get("denominator") or "")
    if numerator not in data.columns or denominator not in data.columns:
        raise ValueError("Derived ratio metric requires numerator and denominator columns.")
    numerator_sum = float(pd.to_numeric(data[numerator], errors="coerce").sum())
    denominator_sum = float(pd.to_numeric(data[denominator], errors="coerce").sum())
    return 0.0 if denominator_sum == 0 else numerator_sum / denominator_sum


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
    series = pd.to_numeric(data[metric], errors="coerce")
    if series.dropna().empty:
        return 0.0
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
    data = _apply_dataframe_filters(df, filters)
    group_by = str(params["group_by"])
    counts = data[group_by].value_counts(dropna=True)
    if counts.empty:
        return NO_MATCHING_RECORDS
    top_value = str(counts.index[0])
    options = params.get("options") or {}
    if options:
        for letter, option_value in options.items():
            if option_value == top_value:
                return f"{letter}. {top_value}"
    return top_value


def _field_values(df: pd.DataFrame, params: dict[str, Any]) -> list[str]:
    field = params.get("field")
    if not field:
        raise ValueError("field_values requires a field parameter.")
    field_name = str(field)
    if field_name not in df.columns:
        raise ValueError(f"Unknown field column: {field_name}")
    values = [str(value) for value in df[field_name].dropna().unique()]
    return sorted(values, key=lambda item: item.lower())


def _missing_columns_choice(df: pd.DataFrame, params: dict[str, Any]) -> str:
    fields = [field for field in (params.get("fields") or []) if field in df.columns]
    if not fields:
        return "未在上传表结构中找到候选字段"
    missing_fields = [
        field
        for field in fields
        if _null_mask(df[field]).any()
    ]
    options = params.get("options") or {}
    if options:
        normalized_missing = {field.lower() for field in missing_fields}
        for letter, text in options.items():
            lowered = str(text).lower()
            if "neither" in lowered and not missing_fields:
                return f"{letter}. {text}"
            if "both" in lowered and len(normalized_missing) == len(fields) and all(field.lower() in lowered for field in fields):
                return f"{letter}. {text}"
            option_fields = {field.lower() for field in fields if field.lower() in lowered}
            if option_fields and option_fields == normalized_missing:
                return f"{letter}. {text}"
    return ", ".join(missing_fields)


def _row_count(df: pd.DataFrame, filters: dict[str, Any]) -> int:
    return int(len(_apply_dataframe_filters(df, filters)))


def _distinct_count(df: pd.DataFrame, filters: dict[str, Any], params: dict[str, Any]) -> int:
    data = _apply_dataframe_filters(df, filters)
    field = str(params.get("field") or "")
    if field not in data.columns:
        raise ValueError("distinct_count requires a known field column.")
    return int(data[field].dropna().nunique())


def _boolean_count_ratio(df: pd.DataFrame, filters: dict[str, Any], params: dict[str, Any]) -> float | str:
    data = _apply_dataframe_filters(df, filters)
    field = str(params.get("field") or "")
    if field not in data.columns:
        raise ValueError("boolean_count_ratio requires a known boolean field.")
    values = _bool_series(data[field])
    left_value = bool(params.get("left_value", True))
    right_value = bool(params.get("right_value", False))
    left_count = int((values == left_value).sum())
    right_count = int((values == right_value).sum())
    if right_count == 0:
        return 0.0
    return left_count / right_count


def _metric_per_distinct_entity(df: pd.DataFrame, filters: dict[str, Any], params: dict[str, Any]) -> float | str:
    data = _apply_dataframe_filters(df, filters)
    metric = str(params.get("metric") or "")
    entity_field = str(params.get("entity_field") or params.get("field") or "")
    aggregation = str(params.get("aggregation") or "sum")
    is_row_count_metric = metric in {"__row_count__", "row_count", "transaction_count"} or aggregation == "count"
    if (not is_row_count_metric and metric not in data.columns) or entity_field not in data.columns:
        raise ValueError("metric_per_distinct_entity requires known metric and entity columns.")
    entity_present = data[~_null_mask(data[entity_field])]
    entity_count = int(entity_present[entity_field].nunique())
    if entity_count == 0:
        return 0.0
    if is_row_count_metric:
        numerator = float(len(entity_present))
    elif aggregation == "mean":
        grouped_means = pd.to_numeric(entity_present[metric], errors="coerce").groupby(entity_present[entity_field]).mean().dropna()
        if grouped_means.empty:
            return 0.0
        return float(grouped_means.mean())
    else:
        values = pd.to_numeric(entity_present[metric], errors="coerce").fillna(0)
        numerator = float(values.sum())
    return numerator / entity_count


def _repeat_entity_percentage(df: pd.DataFrame, filters: dict[str, Any], params: dict[str, Any]) -> float:
    data = _apply_dataframe_filters(df, filters)
    field = str(params.get("field") or params.get("entity_field") or "")
    if field not in data.columns:
        raise ValueError("repeat_entity_percentage requires a known entity field column.")
    counts = data[field].dropna().value_counts()
    if counts.empty:
        return 0.0
    repeat_entities = int((counts > 1).sum())
    return repeat_entities / int(len(counts)) * 100


def _repeat_entity_count(df: pd.DataFrame, filters: dict[str, Any], params: dict[str, Any]) -> int:
    data = _apply_dataframe_filters(df, filters)
    field = str(params.get("field") or params.get("entity_field") or "")
    if field not in data.columns:
        raise ValueError("repeat_entity_count requires a known entity field column.")
    min_count = int(params.get("min_count") or 2)
    values = data.loc[~_null_mask(data[field]), field].astype(str)
    counts = values.value_counts()
    return int((counts >= min_count).sum())


def _outlier_count(df: pd.DataFrame, filters: dict[str, Any], params: dict[str, Any]) -> int:
    data = _apply_dataframe_filters(df, filters)
    metric = str(params.get("metric") or "")
    if metric not in data.columns:
        raise ValueError("outlier_count requires a known numeric metric column.")
    mask = _outlier_mask(data, metric, params)
    if mask.empty:
        return 0
    return int(mask.sum())


def _top_outlier_group(df: pd.DataFrame, filters: dict[str, Any], params: dict[str, Any]) -> Any:
    data = _apply_dataframe_filters(df, filters)
    group_by = str(params.get("group_by") or "")
    metric = str(params.get("metric") or "")
    if group_by not in data.columns:
        raise ValueError("top_outlier_group requires a known group_by column.")
    if metric not in data.columns:
        raise ValueError("top_outlier_group requires a known numeric metric column.")
    mask = _outlier_mask(data, metric, params)
    outliers = data[mask]
    if outliers.empty:
        return NO_MATCHING_RECORDS
    counts = outliers.groupby(group_by, dropna=True).size().sort_values(ascending=False)
    if counts.empty:
        return NO_MATCHING_RECORDS
    selected = counts.index[0]
    if isinstance(selected, (int, float)):
        return selected
    try:
        numeric = float(selected)
        return int(numeric) if numeric.is_integer() else numeric
    except (TypeError, ValueError):
        return str(selected)


def _outlier_mask(data: pd.DataFrame, metric: str, params: dict[str, Any]) -> pd.Series:
    series = pd.to_numeric(data[metric], errors="coerce")
    valid = series.dropna()
    if valid.empty:
        return pd.Series(False, index=data.index)
    method = str(params.get("method") or "iqr").lower()
    if method == "zscore":
        std = float(valid.std(ddof=0))
        if std == 0.0:
            return pd.Series(False, index=data.index)
        threshold = float(params.get("z_threshold") or 3.0)
        zscores = (series - float(valid.mean())).abs() / std
        return zscores > threshold
    q1 = float(valid.quantile(0.25))
    q3 = float(valid.quantile(0.75))
    iqr = q3 - q1
    if iqr == 0.0:
        return pd.Series(False, index=data.index)
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    return (series < lower) | (series > upper)


def _top_k_share(df: pd.DataFrame, filters: dict[str, Any], params: dict[str, Any]) -> float:
    data = _apply_dataframe_filters(df, filters)
    if data.empty:
        return 0.0
    dimension = str(params.get("dimension") or params.get("group_by") or "")
    if dimension not in data.columns:
        raise ValueError("top_k_share requires a known dimension column.")
    aggregation = str(params.get("aggregation") or "sum")
    ranking_metric = params.get("ranking_metric", params.get("metric"))
    share_metric = params.get("share_metric", params.get("metric"))
    limit = int(params.get("limit") or 3)
    if aggregation == "count" or not ranking_metric or ranking_metric in {"__row_count__", "row_count", "transaction_count"}:
        ranking_grouped = data.groupby(dimension, dropna=True).size().sort_values(ascending=False)
    else:
        ranking_metric_name = str(ranking_metric)
        if ranking_metric_name not in data.columns:
            raise ValueError("top_k_share requires a known metric column.")
        ranking_grouped = (
            pd.to_numeric(data[ranking_metric_name], errors="coerce").fillna(0).groupby(data[dimension]).sum().sort_values(ascending=False)
        )
    selected_groups = set(ranking_grouped.head(limit).index)
    selected_rows = data[data[dimension].isin(selected_groups)]
    if share_metric in {None, "__row_count__", "row_count", "transaction_count"}:
        denominator = float(len(data))
        numerator = float(len(selected_rows))
    else:
        share_metric_name = str(share_metric)
        if share_metric_name not in data.columns:
            raise ValueError("top_k_share requires a known share metric column.")
        denominator = float(pd.to_numeric(data[share_metric_name], errors="coerce").fillna(0).sum())
        numerator = float(pd.to_numeric(selected_rows[share_metric_name], errors="coerce").fillna(0).sum())
    if denominator == 0.0:
        return 0.0
    return numerator / denominator * 100


def _quantile_percentage(df: pd.DataFrame, filters: dict[str, Any], params: dict[str, Any]) -> float:
    data = _apply_dataframe_filters(df, filters)
    metric = str(params.get("metric") or "")
    if metric not in data.columns:
        raise ValueError("quantile_percentage requires a known numeric metric column.")
    metric_series = pd.to_numeric(data[metric], errors="coerce")
    valid = data.loc[metric_series.notna()].copy()
    series = metric_series.loc[metric_series.notna()]
    if valid.empty:
        return 0.0
    quantile = float(params.get("quantile") or 0.9)
    threshold = float(series.quantile(quantile))
    if str(params.get("operator") or "above") == "below":
        selected = valid.loc[series < threshold]
    else:
        selected = valid.loc[series > threshold]
    target_mode = str(params.get("target_mode") or "")
    target_field = str(params.get("target_field") or "")
    if target_mode == "repeat_entity" and target_field:
        if target_field not in data.columns:
            raise ValueError("quantile_percentage repeat_entity target requires a known target field.")
        if selected.empty:
            return 0.0
        entity_values = data.loc[~_null_mask(data[target_field]), target_field].astype(str)
        entity_counts = entity_values.value_counts()
        repeat_entities = set(entity_counts[entity_counts > 1].index)
        matches = selected[target_field].astype(str).isin(repeat_entities)
        return float(matches.mean() * 100)
    return 0.0 if len(valid) == 0 else float(len(selected) / len(valid) * 100)


def _outlier_target_percentage(df: pd.DataFrame, filters: dict[str, Any], params: dict[str, Any]) -> float | str:
    data = _apply_dataframe_filters(df, filters)
    metric = str(params.get("metric") or "")
    target = str(params.get("target") or "")
    if metric not in data.columns or target not in data.columns:
        raise ValueError("outlier_target_percentage requires known metric and target columns.")
    outliers = data[_outlier_mask(data, metric, params)]
    if outliers.empty:
        return 0.0
    return float(_bool_series(outliers[target]).mean() * 100)


def _outlier_rate_comparison(df: pd.DataFrame, filters: dict[str, Any], params: dict[str, Any]) -> str:
    data = _apply_dataframe_filters(df, filters)
    metric = str(params.get("metric") or "")
    target = str(params.get("target") or "")
    if metric not in data.columns or target not in data.columns:
        raise ValueError("outlier_rate_comparison requires known metric and target columns.")
    mask = _outlier_mask(data, metric, params)
    outliers = data[mask]
    inliers = data[~mask]
    if outliers.empty or inliers.empty:
        return "no"
    outlier_rate = float(_bool_series(outliers[target]).mean())
    inlier_rate = float(_bool_series(inliers[target]).mean())
    higher = outlier_rate > inlier_rate
    expected = higher if str(params.get("operator") or "higher_than") == "higher_than" else not higher
    return "yes" if expected else "no"


def _correlation_threshold(df: pd.DataFrame, filters: dict[str, Any], params: dict[str, Any]) -> dict[str, Any] | str:
    data = _apply_dataframe_filters(df, filters)
    metric = str(params.get("metric") or "")
    target = str(params.get("target") or "")
    if metric not in data.columns or target not in data.columns:
        raise ValueError("correlation_threshold requires known metric and target columns.")
    metric_series = pd.to_numeric(data[metric], errors="coerce")
    target_series = _bool_series(data[target]).astype(float)
    valid = pd.DataFrame({"metric": metric_series, "target": target_series}).dropna()
    if len(valid) < 2 or valid["metric"].nunique() < 2 or valid["target"].nunique() < 2:
        return {"answer": "no", "correlation": 0.0, "threshold": float(params.get("threshold") or 0.5)}
    coefficient = float(valid["metric"].corr(valid["target"]))
    threshold = float(params.get("threshold") or 0.5)
    value = abs(coefficient) if params.get("absolute", True) else coefficient
    return {
        "answer": "yes" if value > threshold else "no",
        "correlation": coefficient,
        "threshold": threshold,
    }


def _worst_fraud_segment(df: pd.DataFrame, filters: dict[str, Any], params: dict[str, Any]) -> dict[str, Any] | str:
    data = _apply_dataframe_filters(df, filters)
    dimensions = [str(item) for item in (params.get("dimensions") or []) if str(item) in data.columns]
    if not dimensions:
        raise ValueError("worst_fraud_segment requires at least one known dimension.")
    if params.get("combine_dimensions"):
        rows: list[dict[str, Any]] = []
        for keys, group in data.groupby(dimensions, dropna=True):
            key_tuple = keys if isinstance(keys, tuple) else (keys,)
            total_volume = float(pd.to_numeric(group["eur_amount"], errors="coerce").fillna(0).sum()) if "eur_amount" in group.columns else float(len(group))
            if total_volume == 0:
                continue
            fraud_mask = _bool_series(group["has_fraudulent_dispute"])
            fraud_volume = float(pd.to_numeric(group.loc[fraud_mask, "eur_amount"], errors="coerce").fillna(0).sum()) if "eur_amount" in group.columns else float(fraud_mask.sum())
            row = {
                dimension: str(value)
                for dimension, value in zip(dimensions, key_tuple)
            }
            row.update(
                {
                    "fraud_rate": 0.0 if total_volume == 0 else fraud_volume / total_volume * 100,
                    "fraudulent_volume": fraud_volume,
                    "total_volume": total_volume,
                    "transaction_count": int(len(group)),
                }
            )
            rows.append(row)
        if not rows:
            return {"answer": NO_MATCHING_RECORDS, "candidate_table": []}
        rows.sort(key=lambda row: (-float(row["fraud_rate"]), tuple(str(row[dimension]) for dimension in dimensions)))
        selected = rows[0]
        values = [str(selected[dimension]) for dimension in dimensions]
        return {
            "answer": ", ".join(values),
            "values": values,
            "dimensions": dimensions,
            "fraud_rate": selected["fraud_rate"],
            "candidate_table": rows,
        }
    rows: list[dict[str, Any]] = []
    for dimension in dimensions:
        for value, group in data.groupby(dimension, dropna=True):
            total_volume = float(pd.to_numeric(group["eur_amount"], errors="coerce").fillna(0).sum()) if "eur_amount" in group.columns else float(len(group))
            if total_volume == 0:
                continue
            fraud_mask = _bool_series(group["has_fraudulent_dispute"])
            fraud_volume = float(pd.to_numeric(group.loc[fraud_mask, "eur_amount"], errors="coerce").fillna(0).sum()) if "eur_amount" in group.columns else float(fraud_mask.sum())
            rows.append(
                {
                    "segment": dimension,
                    "value": str(value),
                    "fraud_rate": 0.0 if total_volume == 0 else fraud_volume / total_volume * 100,
                    "fraudulent_volume": fraud_volume,
                    "total_volume": total_volume,
                    "transaction_count": int(len(group)),
                }
            )
    if not rows:
        return {"answer": NO_MATCHING_RECORDS, "candidate_table": []}
    rows.sort(key=lambda row: (-float(row["fraud_rate"]), row["segment"], row["value"]))
    selected = rows[0]
    return {
        "answer": f"{selected['segment']}={selected['value']}",
        "segment": selected["segment"],
        "value": selected["value"],
        "fraud_rate": selected["fraud_rate"],
        "candidate_table": rows,
    }


def _filtered_metric_ranking(df: pd.DataFrame, filters: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    data = _apply_dataframe_filters(df, filters)
    dimension = str(params.get("dimension") or "")
    if dimension not in data.columns:
        raise ValueError("filtered_metric_ranking requires a known dimension column.")
    rows = _aggregate_grouped(
        data,
        dimension,
        None if params.get("metric") is None else str(params.get("metric")),
        str(params.get("aggregation") or "sum"),
    )
    if not rows:
        return rows
    metric_column = next((key for key in rows[0] if key != dimension), "value")
    reverse = str(params.get("sort_order") or "desc") == "desc"
    rows.sort(key=lambda row: row.get(metric_column), reverse=reverse)
    return rows[: int(params.get("limit") or 1)]


def _boolean_percentage(df: pd.DataFrame, filters: dict[str, Any], params: dict[str, Any]) -> float:
    data = _apply_dataframe_filters(df, filters)
    if data.empty:
        return 0.0
    field = str(params["field"])
    if field not in data.columns:
        raise ValueError(f"Unknown boolean field column: {field}")
    expected = params.get("value")
    if expected is None:
        expected = True
    matches = _bool_series(data[field]) == bool(expected)
    return float(matches.mean() * 100)


def _duplicate_check(df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    subset = params.get("subset")
    subset_columns = None
    if isinstance(subset, list):
        subset_columns = [str(column) for column in subset if str(column) in df.columns]
    duplicate_rows = df.duplicated(subset=subset_columns, keep=False)
    duplicate_row_count = int(duplicate_rows.sum())
    return {
        "answer": "yes" if duplicate_row_count else "no",
        "duplicate_row_count": duplicate_row_count,
    }


def _null_check(df: pd.DataFrame, filters: dict[str, Any], params: dict[str, Any]) -> int | float | dict[str, Any]:
    data = _apply_dataframe_filters(df, filters)
    field = params.get("field")
    mode = str(params.get("mode") or "count")
    target_field = params.get("target_field")
    target_value = params.get("target_value", True)
    if field:
        field_name = str(field)
        if field_name not in data.columns:
            raise ValueError(f"Unknown field column: {field_name}")
        mask = _null_mask(data[field_name])
        if target_field:
            target_name = str(target_field)
            if target_name not in data.columns:
                raise ValueError(f"Unknown target field column: {target_name}")
            mask = mask & (_bool_series(data[target_name]) == bool(target_value))
        denominator = len(data)
        null_count = int(mask.sum())
    else:
        mask_frame = data.apply(_null_mask)
        denominator = int(data.shape[0] * data.shape[1])
        null_count = int(mask_frame.to_numpy().sum()) if denominator else 0
        field_name = None
    if mode == "exists":
        return {
            "answer": "yes" if null_count else "no",
            "null_count": null_count,
            "checked_field": field_name,
        }
    if mode == "max_field":
        missing_by_field = data.apply(lambda column: int(_null_mask(column).sum()))
        if missing_by_field.empty:
            return NO_MATCHING_RECORDS
        return str(missing_by_field.sort_values(ascending=False).index[0])
    if mode == "rate":
        return 0.0 if denominator == 0 else null_count / denominator * 100
    if mode == "present_rate":
        return 0.0 if denominator == 0 else (denominator - null_count) / denominator * 100
    return null_count


def _schema_field_lookup(df: pd.DataFrame, params: dict[str, Any]) -> str:
    field = str(params.get("field") or "")
    if field in df.columns:
        return field
    concept = str(params.get("concept") or "")
    concept_fields = {
        "fraud": ("has_fraudulent_dispute", "is_fraud", "fraud"),
        "email": ("email_address", "email"),
        "country": ("issuing_country", "ip_country", "acquirer_country", "country"),
    }
    for candidate in concept_fields.get(concept, ()):
        if candidate in df.columns:
            return candidate
    return "未在上传表结构中找到匹配字段"


def _rank_by_metric(df: pd.DataFrame, logic: Any) -> dict[str, Any]:
    params = logic.parameters
    group_by = str(logic.group_by or params["group_by"])
    metric = str(logic.metric or params.get("metric") or "count")
    objective = str(logic.objective or params.get("objective") or "maximum")
    options = dict(logic.options or params.get("options") or {})
    sort_desc = objective != "minimum"
    data = _apply_dataframe_filters(df, logic.filters)
    if metric == "fraud_volume_rate":
        candidate_table = _fraud_volume_rate_by_dimension(data, group_by, options)
        metric_column = "fraud_volume_rate"
        metric_scale = 100.0
    elif metric == "fraud_transaction_rate":
        candidate_table = _fraud_transaction_rate_by_dimension(data, group_by, options)
        metric_column = "fraud_transaction_rate"
        metric_scale = 100.0
    else:
        return {"answer": _top_count(df, logic.filters, {"group_by": group_by, "options": options}), "candidate_table": []}
    if not candidate_table:
        return {"answer": NO_MATCHING_RECORDS, "candidate_table": [], "metric": metric}
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
        "selected_metric": float(selected[metric_column]) * metric_scale,
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
        return "no"
    result = left_rate > right_rate if operator == "higher_than" else left_rate < right_rate
    return "yes" if result else "no"


def _fraud_rate_filtered(df: pd.DataFrame, filters: dict[str, Any]) -> float | str:
    data = _apply_dataframe_filters(df, filters)
    if data.empty:
        return 0.0
    fraud_mask = _bool_series(data["has_fraudulent_dispute"])
    if "eur_amount" in data.columns:
        total_volume = float(pd.to_numeric(data["eur_amount"], errors="coerce").fillna(0).sum())
        if total_volume == 0:
            return 0.0
        fraud_volume = float(pd.to_numeric(data.loc[fraud_mask, "eur_amount"], errors="coerce").fillna(0).sum())
        return fraud_volume / total_volume * 100
    return float(fraud_mask.mean() * 100)


def _fraud_rate_fluctuation(df: pd.DataFrame, filters: dict[str, Any], params: dict[str, Any]) -> dict[str, Any] | str:
    data = _apply_dataframe_filters(df, filters)
    group_by = str(params.get("group_by") or "")
    if data.empty:
        return {"answer": NO_MATCHING_RECORDS, "candidate_table": []}
    if group_by not in data.columns:
        raise ValueError("fraud_rate_fluctuation requires a known group_by column.")
    if "month" in data.columns:
        month_values = pd.to_numeric(data["month"], errors="coerce")
    elif {"year", "day_of_year"}.issubset(data.columns):
        year = int(filters.get("year") or 2023)
        month_values = pd.to_datetime(data["day_of_year"].astype(int) - 1, unit="D", origin=f"{year}-01-01").dt.month
    else:
        raise ValueError("fraud_rate_fluctuation requires month or day_of_year columns.")
    working = data.assign(__month=month_values)
    rows: list[dict[str, Any]] = []
    for value, group in working.groupby(group_by, dropna=True):
        rates: list[float] = []
        for _, period_group in group.groupby("__month", dropna=True):
            total_volume = float(pd.to_numeric(period_group["eur_amount"], errors="coerce").fillna(0).sum()) if "eur_amount" in period_group.columns else float(len(period_group))
            if total_volume == 0:
                continue
            fraud_mask = _bool_series(period_group["has_fraudulent_dispute"])
            fraud_volume = float(pd.to_numeric(period_group.loc[fraud_mask, "eur_amount"], errors="coerce").fillna(0).sum()) if "eur_amount" in period_group.columns else float(fraud_mask.sum())
            rates.append(fraud_volume / total_volume * 100)
        if not rates:
            continue
        std = float(pd.Series(rates).std(ddof=0))
        rows.append({group_by: str(value), "fraud_rate_std": std, "period_count": len(rates)})
    if not rows:
        return {"answer": NO_MATCHING_RECORDS, "candidate_table": []}
    reverse = str(params.get("objective") or "maximum") != "minimum"
    rows.sort(key=lambda row: (float(row["fraud_rate_std"]), str(row[group_by])), reverse=reverse)
    selected = rows[0]
    return {
        "answer": selected[group_by],
        "selected": selected[group_by],
        "selected_metric": selected["fraud_rate_std"],
        "group_by": group_by,
        "candidate_table": rows,
    }


def _fraud_rate(data: pd.DataFrame) -> float | None:
    if data.empty:
        return None
    return float(_bool_series(data["has_fraudulent_dispute"]).mean())


def _apply_dataframe_filters(df: pd.DataFrame, filters: dict[str, Any]) -> pd.DataFrame:
    data = df
    for column, expected in filters.items():
        if expected is None:
            continue
        if column == "month_range" and "month" not in data.columns and {"year", "day_of_year"}.issubset(data.columns):
            start_month, end_month = expected
            months = pd.to_datetime(
                data["day_of_year"].astype(int) - 1,
                unit="D",
                origin=f"{int(filters.get('year') or 2023)}-01-01",
            ).dt.month
            data = data[(months >= int(start_month)) & (months <= int(end_month))]
            continue
        if column == "month" and "month" not in data.columns and {"year", "day_of_year"}.issubset(data.columns):
            months = pd.to_datetime(
                data["day_of_year"].astype(int) - 1,
                unit="D",
                origin=f"{int(filters.get('year') or 2023)}-01-01",
            ).dt.month
            data = data[months == int(expected)]
            continue
        if column not in data.columns:
            continue
        if expected == "__NULL__":
            data = data[_null_mask(data[column])]
            continue
        if expected == "__NOT_NULL__":
            data = data[~_null_mask(data[column])]
            continue
        if _is_day_of_year_range_filter(column, expected):
            start, end = expected
            values = pd.to_numeric(data[column], errors="coerce")
            data = data[(values >= float(start)) & (values <= float(end))]
            continue
        if isinstance(expected, dict) and ("min" in expected or "max" in expected):
            values = pd.to_numeric(data[column], errors="coerce")
            mask = values.notna()
            if expected.get("min") is not None:
                mask &= values >= float(expected["min"])
            if expected.get("max") is not None:
                mask &= values <= float(expected["max"])
            data = data[mask]
            continue
        data = data[_series_equals(data[column], expected)]
    return data


def _is_day_of_year_range_filter(column: Any, expected: Any) -> bool:
    if str(column) != "day_of_year" or not isinstance(expected, (list, tuple)) or len(expected) != 2:
        return False
    try:
        start = float(expected[0])
        end = float(expected[1])
    except (TypeError, ValueError):
        return False
    return start <= end


def _series_equals(series: pd.Series, expected: Any) -> pd.Series:
    if isinstance(expected, bool):
        return _bool_series(series) == expected
    if isinstance(expected, (list, tuple, set)):
        expected_values = {str(value) for value in expected}
        return series.astype(str).isin(expected_values)
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce") == float(expected)
    return series.astype(str) == str(expected)


def _bool_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)
    truthy = {"true", "1", "yes", "y"}
    return series.fillna(False).astype(str).str.strip().str.lower().isin(truthy)


def _null_mask(series: pd.Series) -> pd.Series:
    return series.isna() | series.astype(str).str.strip().str.lower().isin({"", "nan", "none", "null"})


def _fee_candidate_table(dimension: str, candidates: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, value in sorted(candidates.items(), key=lambda item: str(item[0])):
        if isinstance(value, dict):
            row = {dimension: str(key), **value}
            row.setdefault("fee", value.get("fee"))
        else:
            row = {dimension: str(key), "fee": value}
        rows.append(row)
    return rows


def _fee_engine(context: dict[str, Any]) -> DabstepFeeEngine:
    if "_fee_engine" not in context:
        context["_fee_engine"] = DabstepFeeEngine(context["context_dir"])
    return context["_fee_engine"]


def _merchant_filter_or_default(engine: DabstepFeeEngine, filters: dict[str, Any]) -> str:
    merchant = filters.get("merchant")
    if merchant:
        return str(merchant)
    merchants = sorted(str(name) for name in engine.merchants.keys())
    if len(merchants) == 1:
        return merchants[0]
    raise ValueError("Merchant filter is required when multiple merchants are available.")


def _mcc_from_filter(engine: DabstepFeeEngine, filters: dict[str, Any]) -> int | None:
    if filters.get("merchant_category_code") is not None:
        return int(filters["merchant_category_code"])
    if filters.get("mcc_description"):
        return engine.mcc_for_description(str(filters["mcc_description"]))
    return None
