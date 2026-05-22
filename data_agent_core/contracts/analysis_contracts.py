"""Analysis contracts for user questions, logic forms, and plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class UserQuestion:
    """Input question contract before intent parsing."""

    dataset_id: str
    question: str
    execution_mode: str = "dual"
    guidelines: str | None = None
    requested_at: str | None = None


@dataclass
class LogicForm:
    """Serializable intermediate form shared by executors and verifier."""

    task_type: str
    operation: str
    metric: str | None = None
    metric_definition: dict[str, Any] = field(default_factory=dict)
    numerator: dict[str, Any] = field(default_factory=dict)
    denominator: dict[str, Any] = field(default_factory=dict)
    entity_grain: dict[str, Any] = field(default_factory=dict)
    time_window: dict[str, Any] = field(default_factory=dict)
    candidate_set: dict[str, Any] = field(default_factory=dict)
    group_by: str | None = None
    objective: str | None = None
    options: dict[str, Any] = field(default_factory=dict)
    filters: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    output_format: dict[str, Any] = field(default_factory=dict)
    output_contract: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisPlan:
    """Backend-neutral plan produced from a LogicForm."""

    plan_id: str
    logic_form: LogicForm
    steps: list[str] = field(default_factory=list)
    expected_result_shape: str = "scalar"
    constraints: dict[str, Any] = field(default_factory=dict)
