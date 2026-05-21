"""Optional Microsoft Agent Framework tool adapter.

The adapter exposes internal ToolDefinition entries as Microsoft Agent
Framework tools when the optional `agent-framework` package is installed. The
core algorithm remains in data_agent_core and executable tool wrappers remain
in agent_runtime.
"""

from __future__ import annotations

import inspect
import uuid
from typing import Any, Callable

from agent_runtime.agent_role import AgentRole
from agent_runtime.data_agent_tool_catalog import build_data_agent_tool_registry
from agent_runtime.tool_contracts import ToolCall
from agent_runtime.tool_dispatcher import ToolDispatcher
from agent_runtime.tool_registry import ToolDefinition, ToolRegistry


class MicrosoftAgentFrameworkUnavailable(RuntimeError):
    """Raised when the optional Microsoft Agent Framework package is missing."""


def is_framework_available() -> bool:
    """Return whether the optional Microsoft Agent Framework package imports."""

    try:
        _load_microsoft_tool_decorator()
        return True
    except MicrosoftAgentFrameworkUnavailable:
        return False


def build_microsoft_tool_metadata(registry: ToolRegistry | None = None) -> list[dict[str, Any]]:
    """Return adapter metadata without importing Microsoft Agent Framework."""

    registry = registry or build_data_agent_tool_registry()
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
            "allowed_roles": [role.value for role in tool.allowed_roles],
            "timeout_seconds": tool.timeout_seconds,
            "result_policy": tool.result_policy,
            "framework_kind": "function_tool",
            "approval_mode": "never_require",
        }
        for tool in registry.list_definitions()
    ]


def build_microsoft_tool_functions(
    registry: ToolRegistry | None = None,
    *,
    dispatcher: ToolDispatcher | None = None,
    requested_by_by_tool: dict[str, AgentRole] | None = None,
) -> list[Callable[..., Any]]:
    """Build Microsoft Agent Framework function tools from internal tools.

    This function imports `agent_framework.tool` only inside the adapter. Tests
    can monkeypatch the import path; production can install `agent-framework`.
    """

    registry = registry or build_data_agent_tool_registry()
    dispatcher = dispatcher or ToolDispatcher(registry)
    requested_by_by_tool = requested_by_by_tool or {}
    ms_tool = _load_microsoft_tool_decorator()
    functions: list[Callable[..., Any]] = []
    for definition in registry.list_definitions():
        runner = _make_tool_runner(definition, dispatcher, requested_by_by_tool.get(definition.name))
        functions.append(ms_tool(approval_mode="never_require")(runner))
    return functions


def _make_tool_runner(
    definition: ToolDefinition,
    dispatcher: ToolDispatcher,
    requested_by: AgentRole | None,
) -> Callable[..., dict[str, Any]]:
    default_role = requested_by or (definition.allowed_roles[0] if definition.allowed_roles else AgentRole.PLANNER)

    def runner(**arguments: Any) -> dict[str, Any]:
        cleaned_arguments = {key: value for key, value in arguments.items() if value is not None}
        result = dispatcher.dispatch(
            ToolCall(
                step_id=f"ms_tool_{definition.name}_{uuid.uuid4().hex[:8]}",
                tool_name=definition.name,
                arguments=cleaned_arguments,
                requested_by=default_role,
            )
        )
        return result.to_dict()

    runner.__name__ = definition.name
    runner.__doc__ = definition.description
    runner.__signature__ = _signature_from_schema(definition.input_schema)  # type: ignore[attr-defined]
    return runner


def _signature_from_schema(schema: dict[str, Any]) -> inspect.Signature:
    required = set(schema.get("required") or [])
    parameters = []
    for name, property_schema in (schema.get("properties") or {}).items():
        default = inspect.Parameter.empty if name in required else None
        parameters.append(
            inspect.Parameter(
                name,
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=_python_type((property_schema or {}).get("type")),
            )
        )
    return inspect.Signature(parameters=parameters, return_annotation=dict[str, Any])


def _python_type(schema_type: str | None) -> type:
    return {
        "string": str,
        "object": dict,
        "array": list,
        "number": float,
        "boolean": bool,
    }.get(schema_type or "", Any)


def _load_microsoft_tool_decorator() -> Callable[..., Any]:
    try:
        from agent_framework import tool as ms_tool
    except Exception as exc:  # noqa: BLE001 - adapter must provide a clear optional dependency error.
        raise MicrosoftAgentFrameworkUnavailable(
            "Microsoft Agent Framework is not installed. Install locally with `pip install agent-framework` "
            "when running the optional adapter."
        ) from exc
    return ms_tool
