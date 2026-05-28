"""Shared guardrails for selecting deterministic vs LLM logic forms."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable, Mapping

from data_agent_core.contracts.analysis_contracts import LogicForm
from data_agent_core.core.capability_registry import capability_for_operation


LOW_INFORMATION_GUARDRAIL_OPERATIONS = {"not_applicable", "detail_lookup"}
COLUMN_PARAMETER_KEYS = {
    "field",
    "target_field",
    "entity_field",
    "dimension",
    "group_by",
    "metric",
    "ranking_metric",
    "share_metric",
    "target",
}
NON_COLUMN_SENTINELS = {"", "__row_count__", "row_count", "transaction_count", "record_count", "count"}
SENSITIVE_FIELD_TOKEN_PARTS = (
    ("accepted", "answer"),
    ("accepted", "answers"),
    ("answer", "key"),
    ("benchmark", "answer"),
    ("expected", "answer"),
    ("gold", "answer"),
    ("hidden", "answer"),
    ("public", "proxy"),
    ("standard", "answer"),
    ("task", "id"),
)
SENSITIVE_FIELD_TOKENS = {"_".join(parts) for parts in SENSITIVE_FIELD_TOKEN_PARTS}


def validate_logic_form_with_guardrails(
    llm_logic_form: LogicForm,
    guardrail_logic_form: LogicForm,
    *,
    available_columns_by_table: Mapping[str, Iterable[str]] | None = None,
) -> LogicForm:
    """Select a logic form while keeping deterministic schema guardrails authoritative."""

    if llm_logic_form.operation == guardrail_logic_form.operation:
        selected = deepcopy(guardrail_logic_form)
        _merge_optional_contract_fields(selected, llm_logic_form)
        for key, value in llm_logic_form.output_format.items():
            selected.output_format.setdefault(key, value)
        return selected

    if _can_use_llm_fallback(llm_logic_form, guardrail_logic_form, available_columns_by_table or {}):
        selected = deepcopy(llm_logic_form)
        _merge_grounding_context(selected, guardrail_logic_form)
        return selected

    return guardrail_logic_form


def available_columns_by_table_from_context(context: Mapping[str, Any]) -> dict[str, list[str]]:
    """Extract table-column mappings from a DABstep or uploaded-table context."""

    result: dict[str, list[str]] = {}
    payments = context.get("payments")
    if hasattr(payments, "columns"):
        result["payments"] = [str(column) for column in payments.columns]
    tables = context.get("tables")
    if isinstance(tables, Mapping):
        for name, table in tables.items():
            if hasattr(table, "columns"):
                result[str(name)] = [str(column) for column in table.columns]
    return result


def _can_use_llm_fallback(
    llm_logic_form: LogicForm,
    guardrail_logic_form: LogicForm,
    available_columns_by_table: Mapping[str, Iterable[str]],
) -> bool:
    if guardrail_logic_form.operation not in LOW_INFORMATION_GUARDRAIL_OPERATIONS:
        return False
    if llm_logic_form.operation in {"", "not_applicable"}:
        return False
    capability = capability_for_operation(llm_logic_form.operation)
    if not capability.supports_pandas:
        return False
    if _contains_benchmark_leak(llm_logic_form):
        return False
    return _field_references_are_available(llm_logic_form, available_columns_by_table)


def _field_references_are_available(
    logic_form: LogicForm,
    available_columns_by_table: Mapping[str, Iterable[str]],
) -> bool:
    if not available_columns_by_table:
        return True
    table_name = str(logic_form.parameters.get("table") or "")
    available = _available_columns_for_table(table_name, available_columns_by_table)
    if not available:
        return True
    for key, value in logic_form.parameters.items():
        if key in COLUMN_PARAMETER_KEYS and not _field_value_is_available(value, available):
            return False
    for key in ("metric", "group_by"):
        value = getattr(logic_form, key)
        if value is not None and not _field_value_is_available(value, available):
            return False
    for key in logic_form.filters:
        if str(key) not in available:
            return False
    return True


def _available_columns_for_table(
    table_name: str,
    available_columns_by_table: Mapping[str, Iterable[str]],
) -> set[str]:
    if table_name and table_name in available_columns_by_table:
        return {str(column) for column in available_columns_by_table[table_name]}
    if len(available_columns_by_table) == 1:
        return {str(column) for column in next(iter(available_columns_by_table.values()))}
    return set()


def _field_value_is_available(value: Any, available: set[str]) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, tuple, set)):
        return all(_field_value_is_available(item, available) for item in value)
    text = str(value)
    if text in NON_COLUMN_SENTINELS:
        return True
    return text in available


def _contains_benchmark_leak(value: Any) -> bool:
    if isinstance(value, LogicForm):
        return _contains_benchmark_leak(
            {
                "task_type": value.task_type,
                "operation": value.operation,
                "metric": value.metric,
                "metric_definition": value.metric_definition,
                "numerator": value.numerator,
                "denominator": value.denominator,
                "entity_grain": value.entity_grain,
                "time_window": value.time_window,
                "candidate_set": value.candidate_set,
                "group_by": value.group_by,
                "objective": value.objective,
                "options": value.options,
                "filters": value.filters,
                "parameters": value.parameters,
                "output_format": value.output_format,
                "output_contract": value.output_contract,
            }
        )
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered_key = str(key).lower()
            if any(token in lowered_key for token in SENSITIVE_FIELD_TOKENS):
                return True
            if _contains_benchmark_leak(item):
                return True
        return False
    if isinstance(value, (list, tuple, set)):
        return any(_contains_benchmark_leak(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return any(token in lowered for token in SENSITIVE_FIELD_TOKENS)
    return False


def _merge_grounding_context(target: LogicForm, source: LogicForm) -> None:
    for key in ("table", "source_tables", "table_selection_reason", "join_plan"):
        if key in source.parameters:
            target.parameters.setdefault(key, source.parameters[key])
    if not target.source_tables and source.source_tables:
        target.source_tables.extend(source.source_tables)
    if not target.table_selection_reason and source.table_selection_reason:
        target.table_selection_reason = source.table_selection_reason
    if not target.join_plan and source.join_plan:
        target.join_plan.update(source.join_plan)
    if "guidelines" in source.output_format:
        target.output_format.setdefault("guidelines", source.output_format["guidelines"])


def _merge_optional_contract_fields(target: LogicForm, source: LogicForm) -> None:
    for field_name in (
        "metric_definition",
        "numerator",
        "denominator",
        "entity_grain",
        "time_window",
        "candidate_set",
        "output_contract",
        "options",
        "filters",
        "parameters",
        "source_tables",
        "join_plan",
        "output_format",
    ):
        source_value = getattr(source, field_name)
        target_value = getattr(target, field_name)
        if isinstance(source_value, dict) and isinstance(target_value, dict):
            for key, value in source_value.items():
                target_value.setdefault(key, value)
        elif isinstance(source_value, list) and isinstance(target_value, list) and not target_value:
            target_value.extend(source_value)
    for field_name in ("metric", "group_by", "objective"):
        if getattr(target, field_name) is None and getattr(source, field_name) is not None:
            setattr(target, field_name, getattr(source, field_name))
    if not target.table_selection_reason and source.table_selection_reason:
        target.table_selection_reason = source.table_selection_reason
