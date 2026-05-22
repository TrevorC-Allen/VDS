"""Analysis planner for structured analysis plans."""

from __future__ import annotations

import hashlib
from typing import Any

from data_agent_core.contracts.analysis_contracts import AnalysisPlan, LogicForm
from data_agent_core.core.capability_registry import capability_for_operation


COUNT_LIKE_BUSINESS_OPERATIONS = frozenset(
    {
        "retail_audit_sku_category_record_top",
        "retail_audit_sku_store_sku_count_top",
        "retail_display_execution_image_pass_top",
        "retail_display_execution_item_count_top",
        "retail_display_item_top",
        "retail_today_category_top",
        "retail_active_sku_top",
    }
)


def build_analysis_plan(logic_form: LogicForm) -> AnalysisPlan:
    """Build a backend-neutral AnalysisPlan from a LogicForm."""

    logic_form = complete_generalization_contract(logic_form)
    plan_seed = f"{logic_form.task_type}:{logic_form.operation}:{logic_form.filters}:{logic_form.parameters}"
    plan_id = "plan_" + hashlib.sha1(plan_seed.encode("utf-8")).hexdigest()[:12]
    return AnalysisPlan(
        plan_id=plan_id,
        logic_form=logic_form,
        steps=[
            "llm_intent_parser",
            "llm_rules_column_mapping",
            "llm_analysis_planner",
            "code_pandas_executor",
            "code_sql_duckdb_executor",
            "code_result_normalizer",
            "rules_llm_verifier_critic",
            "rules_llm_correction_planner",
            "llm_insight_generator",
            "llm_rules_chart_planner",
            "backend_json_response",
        ],
        expected_result_shape=str(logic_form.output_format.get("answer_type", "scalar")),
        constraints={
            "framework_neutral": True,
            "no_benchmark_answer_access": True,
            "generalization_contract": {
                "capability_family": capability_for_operation(logic_form.operation).capability_family,
                "metric_definition": bool(logic_form.metric_definition),
                "numerator": bool(logic_form.numerator),
                "denominator": bool(logic_form.denominator),
                "entity_grain": bool(logic_form.entity_grain),
                "time_window": bool(logic_form.time_window),
                "candidate_set": bool(logic_form.candidate_set),
                "filters": isinstance(logic_form.filters, dict),
                "filter_count": len(logic_form.filters),
                "output_contract": bool(logic_form.output_contract),
            },
        },
    )


def complete_generalization_contract(logic_form: LogicForm) -> LogicForm:
    """Fill stable planner contract fields from existing structured intent."""

    params = logic_form.parameters
    capability = capability_for_operation(logic_form.operation)
    metric = logic_form.metric or params.get("metric")
    aggregation = _aggregation_for(logic_form, metric)
    group_field = logic_form.group_by or params.get("group_by") or params.get("dimension")
    entity_field = params.get("entity_field") or params.get("entity") or params.get("field")
    if not logic_form.metric_definition:
        logic_form.metric_definition = {
            "name": _metric_name(logic_form, metric),
            "capability_family": capability.capability_family,
            "aggregation": aggregation,
            "business_definition": _metric_business_definition(logic_form, metric, aggregation),
        }
    if not logic_form.numerator:
        logic_form.numerator = _numerator(logic_form, metric, aggregation)
    if not logic_form.denominator:
        logic_form.denominator = _denominator(logic_form, metric, aggregation, entity_field)
    if not logic_form.entity_grain:
        logic_form.entity_grain = _entity_grain(group_field=group_field, entity_field=entity_field)
    if not logic_form.time_window:
        logic_form.time_window = _time_window(logic_form.filters, params)
    if not logic_form.candidate_set:
        logic_form.candidate_set = _candidate_set(logic_form.options, params, group_field)
    if not logic_form.output_contract:
        logic_form.output_contract = {
            "answer_type": str(logic_form.output_format.get("answer_type") or "scalar"),
            "expected_result_shape": str(logic_form.output_format.get("answer_type") or "scalar"),
            "capability_family": capability.capability_family,
            "format_guidelines": str(logic_form.output_format.get("guidelines") or ""),
        }
    return logic_form


def _aggregation_for(logic_form: LogicForm, metric: Any) -> str:
    aggregation = logic_form.parameters.get("aggregation")
    if aggregation:
        return str(aggregation)
    if logic_form.operation in COUNT_LIKE_BUSINESS_OPERATIONS:
        return "count"
    if logic_form.operation in {"row_count", "distinct_count", "top_count"}:
        return "count"
    if metric in {"__row_count__", "row_count", "transaction_count", "record_count"}:
        return "count"
    return "sum" if metric else "none"


def _metric_name(logic_form: LogicForm, metric: Any) -> str:
    if metric:
        return str(metric)
    return {
        "row_count": "row_count",
        "distinct_count": "distinct_count",
        "top_count": "record_count",
        "duplicate_check": "duplicate_rows",
        "null_check": "missing_values",
        "field_values": "field_values",
    }.get(logic_form.operation, logic_form.operation)


def _metric_business_definition(logic_form: LogicForm, metric: Any, aggregation: str) -> str:
    if logic_form.operation == "top_k_share":
        if aggregation == "count" or not metric:
            return "Share of rows represented by the top candidate groups after filters."
        return "Share of the selected metric represented by the top candidate groups after filters."
    if logic_form.operation == "metric_per_distinct_entity":
        return "Selected numerator divided by the number of distinct entities after filters."
    if aggregation == "count":
        return "Count rows or entities after applying the plan filters."
    if metric:
        return f"Aggregate {metric} with {aggregation} after applying the plan filters."
    return "No metric aggregation is required for this operation."


def _numerator(logic_form: LogicForm, metric: Any, aggregation: str) -> dict[str, Any]:
    params = logic_form.parameters
    if logic_form.operation == "top_k_share":
        return {
            "aggregation": aggregation,
            "field": None if aggregation == "count" else metric,
            "scope": "top_k_groups",
            "limit": params.get("limit"),
        }
    if logic_form.operation == "metric_per_distinct_entity":
        return {"aggregation": aggregation, "field": metric or "__row_count__", "scope": "filtered_rows"}
    if logic_form.operation in {"row_count", "top_count"}:
        return {"aggregation": "count", "field": "__row_count__", "scope": "filtered_rows"}
    if logic_form.operation == "distinct_count":
        return {"aggregation": "distinct_count", "field": params.get("field"), "scope": "filtered_rows"}
    if logic_form.operation == "boolean_percentage":
        return {"aggregation": "count", "field": params.get("field"), "value": params.get("value", True), "scope": "matching_rows"}
    if logic_form.operation == "fraud_rate_filtered":
        return {"aggregation": "sum", "field": "eur_amount", "filter": {"has_fraudulent_dispute": True}, "scope": "fraudulent_rows"}
    if metric:
        return {"aggregation": aggregation, "field": metric, "scope": "filtered_rows"}
    return {"scope": "not_required"}


def _denominator(logic_form: LogicForm, metric: Any, aggregation: str, entity_field: Any) -> dict[str, Any]:
    params = logic_form.parameters
    if logic_form.operation == "metric_per_distinct_entity":
        denominator_field = params.get("entity_field") or params.get("field") or entity_field
        return {"aggregation": "nunique", "field": denominator_field, "role": "unique_entity"}
    if logic_form.operation == "repeat_entity_percentage":
        denominator_field = params.get("field") or params.get("entity_field") or entity_field
        return {"aggregation": "nunique", "field": denominator_field, "role": "unique_entity"}
    if logic_form.operation == "top_k_share":
        return {
            "aggregation": aggregation,
            "scope": "filtered_total",
            "field": None if aggregation == "count" else metric,
        }
    if logic_form.operation in {"boolean_percentage", "fraud_rate_filtered"}:
        return {"aggregation": "count_or_sum", "scope": "filtered_population"}
    return {"scope": "not_required"}


def _entity_grain(*, group_field: Any, entity_field: Any) -> dict[str, Any]:
    if group_field:
        return {"field": str(group_field), "role": "group_by"}
    if entity_field:
        return {"field": str(entity_field), "role": "entity"}
    return {"field": "__table__", "role": "table"}


def _time_window(filters: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    time_keys = {
        "year",
        "month",
        "month_range",
        "day_of_year",
        "date",
        "ym",
        "current_period",
        "previous_period",
        "fiscal_year",
    }
    values = {key: value for key, value in (filters | params).items() if key in time_keys and value is not None}
    return {"type": "filtered", "values": values} if values else {"type": "all_time", "values": {}}


def _candidate_set(options: dict[str, Any], params: dict[str, Any], group_field: Any) -> dict[str, Any]:
    if options:
        return {"source": "options", "values": dict(options)}
    if params.get("options"):
        return {"source": "options", "values": dict(params["options"])}
    if group_field:
        return {"source": "data", "field": str(group_field)}
    return {"source": "not_required", "values": []}
