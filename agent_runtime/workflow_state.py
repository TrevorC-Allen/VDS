"""Internal workflow state contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class WorkflowState:
    """Serializable state shared across single-agent and multi-agent workflows."""

    dataset_id: str
    question: str
    schema_profile: Any = None
    logic_form: Any = None
    analysis_plan: Any = None
    pandas_result: Any = None
    sql_result: Any = None
    verification: Any = None
    correction_attempts: list[Any] = field(default_factory=list)
    insight: Any = None
    chart: Any = None
    final_response: Any = None
    trace: Any = None
    tool_call_trace: list[Any] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[Any] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready workflow state dict."""

        return asdict(self)
