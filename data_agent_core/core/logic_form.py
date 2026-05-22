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
    output_format: dict[str, object] | None = None,
    output_contract: dict[str, object] | None = None,
) -> LogicForm:
    """Create a LogicForm with stable empty defaults."""

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
        parameters=parameters or {},
        output_format=output_format or {},
        output_contract=output_contract or {},
    )
