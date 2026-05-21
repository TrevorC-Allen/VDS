"""Controlled dispatcher for internal provider-neutral tools."""

from __future__ import annotations

import time
from typing import Any

from agent_runtime.agent_role import AgentRole
from agent_runtime.tool_contracts import ToolCall, ToolResult, ToolTraceEvent, to_json_ready
from agent_runtime.tool_registry import ToolDefinition, ToolRegistry


class ToolDispatcher:
    """Validate and dispatch internal tools through a registry."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def dispatch(self, call: ToolCall) -> ToolResult:
        """Dispatch one controlled tool call and return trace-safe output."""

        start = time.perf_counter()
        try:
            tool = self.registry.get(call.tool_name)
            self._validate_role(tool, call)
            self._validate_arguments(tool, call.arguments)
            if tool.callable_ref is None:
                raise ValueError(f"Tool has no callable implementation in this runtime: {tool.name}")
            raw_output = tool.callable_ref(call.arguments)
            output_payload = to_json_ready(raw_output)
            trace = self._trace_event(call, True, start, _summarize_payload(call.arguments), _summarize_payload(output_payload))
            return ToolResult(
                step_id=call.step_id,
                tool_name=call.tool_name,
                success=True,
                output_payload=output_payload if isinstance(output_payload, dict) else {"value": output_payload},
                trace_event=trace,
            )
        except Exception as exc:  # noqa: BLE001 - dispatcher must normalize tool errors.
            trace = self._trace_event(call, False, start, _summarize_payload(call.arguments), {}, str(exc))
            return ToolResult(
                step_id=call.step_id,
                tool_name=call.tool_name,
                success=False,
                errors=[
                    {
                        "error_type": "TOOL_DISPATCH_ERROR",
                        "error_message": str(exc),
                        "failed_step": call.step_id,
                        "recoverable": True,
                        "suggested_fix": "Validate the tool name, role, and JSON arguments before retrying.",
                    }
                ],
                trace_event=trace,
            )

    def _validate_role(self, tool: ToolDefinition, call: ToolCall) -> None:
        role = call.requested_by if isinstance(call.requested_by, AgentRole) else AgentRole(str(call.requested_by))
        if tool.allowed_roles and role not in tool.allowed_roles:
            allowed = ", ".join(sorted(role.value for role in tool.allowed_roles))
            raise PermissionError(f"Role {role.value} is not allowed to call {tool.name}. allowed_roles={allowed}")

    def _validate_arguments(self, tool: ToolDefinition, arguments: dict[str, Any]) -> None:
        schema = tool.input_schema or {}
        required = schema.get("required") or []
        missing = [name for name in required if name not in arguments]
        if missing:
            raise ValueError(f"Missing required tool arguments for {tool.name}: {', '.join(missing)}")
        properties = schema.get("properties") or {}
        for name, value in arguments.items():
            if name not in properties and schema.get("additionalProperties") is False:
                raise ValueError(f"Unexpected tool argument for {tool.name}: {name}")
            expected_type = (properties.get(name) or {}).get("type")
            if expected_type and not _matches_type(value, expected_type):
                raise TypeError(f"Tool argument {name} must be {expected_type}.")

    def _trace_event(
        self,
        call: ToolCall,
        success: bool,
        start: float,
        arguments_summary: dict[str, Any],
        result_summary: dict[str, Any],
        error: str | None = None,
    ) -> ToolTraceEvent:
        return ToolTraceEvent(
            step_id=call.step_id,
            tool_name=call.tool_name,
            requested_by=call.requested_by.value if isinstance(call.requested_by, AgentRole) else str(call.requested_by),
            success=success,
            arguments_summary=arguments_summary,
            result_summary=result_summary,
            latency_ms=(time.perf_counter() - start) * 1000,
            error=error,
        )


def _matches_type(value: Any, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    return True


def _summarize_payload(payload: Any, max_items: int = 8, max_text: int = 120) -> dict[str, Any]:
    data = to_json_ready(payload)
    if isinstance(data, dict):
        summary: dict[str, Any] = {}
        for index, (key, value) in enumerate(data.items()):
            if index >= max_items:
                summary["..."] = f"{len(data) - max_items} more keys"
                break
            summary[key] = _summarize_value(value, max_text=max_text)
        return summary
    return {"value": _summarize_value(data, max_text=max_text)}


def _summarize_value(value: Any, max_text: int) -> Any:
    if isinstance(value, str):
        return value if len(value) <= max_text else value[:max_text] + "..."
    if isinstance(value, list):
        return {"type": "array", "length": len(value)}
    if isinstance(value, dict):
        return {"type": "object", "keys": list(value)[:8]}
    return value
