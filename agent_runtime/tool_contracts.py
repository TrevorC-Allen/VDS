"""Provider-neutral contracts for controlled tool calling."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any

from agent_runtime.agent_role import AgentRole


@dataclass
class ToolCall:
    """One requested internal tool call before provider-specific adaptation."""

    step_id: str
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    requested_by: AgentRole | str = AgentRole.PLANNER

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready tool call dict."""

        data = asdict(self)
        data["requested_by"] = self.requested_by.value if isinstance(self.requested_by, AgentRole) else self.requested_by
        return data


@dataclass
class ToolTraceEvent:
    """Auditable tool call summary safe for trace/debug output."""

    step_id: str
    tool_name: str
    requested_by: str
    success: bool
    arguments_summary: dict[str, Any] = field(default_factory=dict)
    result_summary: dict[str, Any] = field(default_factory=dict)
    latency_ms: float | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready trace event."""

        return asdict(self)


@dataclass
class ToolResult:
    """Standard output from the internal tool dispatcher."""

    step_id: str
    tool_name: str
    success: bool
    output_payload: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    trace_event: ToolTraceEvent | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready result dict."""

        data = asdict(self)
        if self.trace_event is not None:
            data["trace_event"] = self.trace_event.to_dict()
        return data


def to_json_ready(value: Any) -> Any:
    """Recursively convert runtime objects to JSON-safe values."""

    if isinstance(value, AgentRole):
        return value.value
    if is_dataclass(value):
        return to_json_ready(asdict(value))
    if isinstance(value, dict):
        return {str(key): to_json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [to_json_ready(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    return value
