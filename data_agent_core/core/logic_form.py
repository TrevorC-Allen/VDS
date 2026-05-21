"""Logic form helpers shared by executors and verifier."""

from __future__ import annotations

from data_agent_core.contracts.analysis_contracts import LogicForm


def make_logic_form(
    *,
    task_type: str,
    operation: str,
    filters: dict[str, object] | None = None,
    parameters: dict[str, object] | None = None,
    output_format: dict[str, object] | None = None,
) -> LogicForm:
    """Create a LogicForm with stable empty defaults."""

    return LogicForm(
        task_type=task_type,
        operation=operation,
        filters=filters or {},
        parameters=parameters or {},
        output_format=output_format or {},
    )
