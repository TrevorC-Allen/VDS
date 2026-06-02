"""Controlled dispatcher for internal provider-neutral tools."""

from __future__ import annotations

import time
import signal
import threading
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
            self._validate_safety_boundary(tool, call.arguments)
            if tool.callable_ref is None:
                raise ValueError(f"Tool has no callable implementation in this runtime: {tool.name}")
            raw_output = _call_tool_with_timeout(tool, call.arguments)
            output_payload = _redact_payload(to_json_ready(raw_output))
            trace = self._trace_event(call, True, start, _summarize_payload(call.arguments), _summarize_payload(output_payload))
            return ToolResult(
                step_id=call.step_id,
                tool_name=call.tool_name,
                success=True,
                output_payload=output_payload if isinstance(output_payload, dict) else {"value": output_payload},
                trace_event=trace,
            )
        except Exception as exc:  # noqa: BLE001 - dispatcher must normalize tool errors.
            error_message = _redact_text(str(exc))
            trace = self._trace_event(call, False, start, _summarize_payload(call.arguments), {}, error_message)
            return ToolResult(
                step_id=call.step_id,
                tool_name=call.tool_name,
                success=False,
                errors=[
                    {
                        "error_type": "TOOL_DISPATCH_ERROR",
                        "error_message": error_message,
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
            _validate_schema_value(value, properties.get(name) or {}, path=name)

    def _validate_safety_boundary(self, tool: ToolDefinition, arguments: dict[str, Any]) -> None:
        unsafe_keys = sorted(_find_forbidden_argument_keys(arguments))
        if unsafe_keys:
            raise PermissionError(f"Tool {tool.name} received forbidden unsafe argument keys: {', '.join(unsafe_keys)}")
        constraints = tool.constraints or {}
        blocked_constraints = [
            name
            for name in ("network_access", "shell_access", "external_file_access", "raw_python", "raw_sql", "benchmark_answer_access")
            if constraints.get(name)
        ]
        if blocked_constraints:
            raise PermissionError(f"Tool {tool.name} enables forbidden constraints: {', '.join(blocked_constraints)}")

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


def _validate_schema_value(value: Any, schema: dict[str, Any], *, path: str) -> None:
    expected_type = schema.get("type")
    if expected_type and not _matches_type(value, expected_type):
        raise TypeError(f"Tool argument {path} must be {expected_type}.")
    if "enum" in schema and value not in set(schema["enum"]):
        raise ValueError(f"Tool argument {path} must be one of {list(schema['enum'])}.")
    if expected_type == "object" and isinstance(value, dict):
        required = schema.get("required") or []
        missing = [name for name in required if name not in value]
        if missing:
            raise ValueError(f"Missing required nested tool arguments for {path}: {', '.join(missing)}")
        properties = schema.get("properties") or {}
        for key, item in value.items():
            if key not in properties and schema.get("additionalProperties") is False:
                raise ValueError(f"Unexpected nested tool argument for {path}: {key}")
            if key in properties:
                _validate_schema_value(item, properties[key] or {}, path=f"{path}.{key}")
    if expected_type == "array" and isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            _validate_schema_value(item, schema["items"], path=f"{path}[{index}]")


def _matches_type(value: Any, expected_type: str | list[str]) -> bool:
    if isinstance(expected_type, list):
        return any(_matches_type(value, type_name) for type_name in expected_type)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return True


def _call_tool_with_timeout(tool: ToolDefinition, arguments: dict[str, Any]) -> Any:
    """Execute a tool callable with a POSIX timer when available."""

    if tool.callable_ref is None:
        raise ValueError(f"Tool has no callable implementation in this runtime: {tool.name}")
    timeout_seconds = float(tool.timeout_seconds or 0)
    if timeout_seconds <= 0 or not _can_use_signal_timeout():
        return tool.callable_ref(arguments)

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)

    def timeout_handler(_signum: int, _frame: Any) -> None:
        raise TimeoutError(f"Tool {tool.name} timed out after {timeout_seconds:g} seconds.")

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        return tool.callable_ref(arguments)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])


def _can_use_signal_timeout() -> bool:
    return threading.current_thread() is threading.main_thread() and hasattr(signal, "setitimer")


_REDACTED = "[REDACTED]"
_SENSITIVE_KEY_TOKENS = {
    "api_key",
    "apikey",
    "access_token",
    "auth_token",
    "bearer",
    "authorization",
    "password",
    "secret",
    "credential",
    "_".join(("hidden", "answer")),
    "_".join(("expected", "answer")),
    "_".join(("standard", "answer")),
    "_".join(("accepted", "answer")),
    "_".join(("proxy", "answer")),
    "ground_truth",
    "answer_key",
    "task_id",
    "submission_id",
}
_FORBIDDEN_ARGUMENT_KEYS = {
    "raw_python",
    "python_code",
    "exec_code",
    "eval_code",
    "raw_sql",
    "sql_query",
    "shell_command",
    "command",
    "network_url",
    "web_url",
    "external_file",
    "file_path",
    "absolute_path",
}


def _summarize_payload(payload: Any, max_items: int = 8, max_text: int = 120) -> dict[str, Any]:
    data = to_json_ready(payload)
    if isinstance(data, dict):
        summary: dict[str, Any] = {}
        for index, (key, value) in enumerate(data.items()):
            if index >= max_items:
                summary["..."] = f"{len(data) - max_items} more keys"
                break
            summary[_safe_summary_key(key)] = _summarize_value(value, key=str(key), max_text=max_text)
        return summary
    return {"value": _summarize_value(data, max_text=max_text)}


def _summarize_value(value: Any, max_text: int, key: str | None = None) -> Any:
    if key and _is_sensitive_key(key):
        return _REDACTED
    if isinstance(value, str):
        value = _redact_text(value)
        return value if len(value) <= max_text else value[:max_text] + "..."
    if isinstance(value, list):
        return {"type": "array", "length": len(value)}
    if isinstance(value, dict):
        return {"type": "object", "keys": [_safe_summary_key(item) for item in list(value)[:8]]}
    return value


def _safe_summary_key(key: Any) -> str:
    text = str(key)
    return _REDACTED if _is_sensitive_key(text) else text


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    return any(token in normalized for token in _SENSITIVE_KEY_TOKENS)


def _redact_text(text: str) -> str:
    lowered = text.lower()
    blocked_phrases = ("bearer ", "api key", "api_key", " ".join(("hidden", "answer")), " ".join(("expected", "answer")), " ".join(("proxy", "answer")))
    if any(token in lowered for token in blocked_phrases):
        return _REDACTED
    if "sk-" in text and len(text) > 12:
        return _REDACTED
    return text


def _redact_payload(value: Any, key: str | None = None) -> Any:
    if key and _is_sensitive_key(key):
        return _REDACTED
    if isinstance(value, dict):
        return {str(item_key): _redact_payload(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _find_forbidden_argument_keys(value: Any, prefix: str = "") -> set[str]:
    if not isinstance(value, dict):
        return set()
    found: set[str] = set()
    for key, item in value.items():
        key_text = str(key)
        normalized = key_text.lower().replace("-", "_").replace(" ", "_")
        path = f"{prefix}.{key_text}" if prefix else key_text
        if normalized in _FORBIDDEN_ARGUMENT_KEYS:
            found.add(path)
        found.update(_find_forbidden_argument_keys(item, path))
    return found
