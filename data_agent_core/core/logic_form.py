"""Logic form helpers shared by executors and verifier."""

from __future__ import annotations

from data_agent_core.contracts.analysis_contracts import LogicForm


def make_logic_form(
    *,
    task_type: str,
    operation: str,
    metric: str | None = None,
    metric_definition: dict[str, object] | None = None,
    numerator: dict[str, object] | None = None,
    denominator: dict[str, object] | None = None,
    entity_grain: dict[str, object] | None = None,
    time_window: dict[str, object] | None = None,
    candidate_set: dict[str, object] | None = None,
    group_by: str | None = None,
    objective: str | None = None,
    options: dict[str, object] | None = None,
    filters: dict[str, object] | None = None,
    parameters: dict[str, object] | None = None,
    source_tables: list[str] | None = None,
    table_selection_reason: str = "",
    join_plan: dict[str, object] | None = None,
    answer_target: str | None = None,
    output_format: dict[str, object] | None = None,
    output_contract: dict[str, object] | None = None,
) -> LogicForm:
    """Create a LogicForm with stable empty defaults."""

    parameters_payload = dict(parameters or {})
    output_format_payload = dict(output_format or {})
    if answer_target:
        output_format_payload.setdefault("answer_target", answer_target)
    elif output_format_payload.get("answer_target"):
        answer_target = str(output_format_payload["answer_target"])
    source_tables_payload = list(source_tables or parameters_payload.get("source_tables") or [])
    table_selection_reason_payload = table_selection_reason or str(parameters_payload.get("table_selection_reason") or "")
    join_plan_payload = dict(join_plan or parameters_payload.get("join_plan") or {})

    return LogicForm(
        task_type=task_type,
        operation=operation,
        metric=metric,
        metric_definition=metric_definition or {},
        numerator=numerator or {},
        denominator=denominator or {},
        entity_grain=entity_grain or {},
        time_window=time_window or {},
        candidate_set=candidate_set or {},
        group_by=group_by,
        objective=objective,
        options=options or {},
        filters=filters or {},
        parameters=parameters_payload,
        source_tables=source_tables_payload,
        table_selection_reason=table_selection_reason_payload,
        join_plan=join_plan_payload,
        answer_target=answer_target,
        output_format=output_format_payload,
        output_contract=output_contract or {},
    )
