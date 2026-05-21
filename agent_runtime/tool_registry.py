"""Framework-neutral tool registry for controlled tool calling."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from agent_runtime.agent_role import AgentRole


ToolCallable = Callable[[dict[str, Any]], Any]


@dataclass
class ToolDefinition:
    """Internal tool metadata before exposing it through any framework/provider."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    allowed_roles: list[AgentRole] = field(default_factory=list)
    timeout_seconds: int = 30
    result_policy: str = "summary_only"
    constraints: dict[str, Any] = field(default_factory=dict)
    callable_ref: ToolCallable | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-ready metadata for docs, tests, and adapters."""

        data = asdict(self)
        data["allowed_roles"] = [role.value if isinstance(role, AgentRole) else str(role) for role in self.allowed_roles]
        data["callable_ref"] = self.callable_ref is not None
        return data


class ToolRegistry:
    """Small registry for framework-neutral tool definitions."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Register one tool by stable name."""

        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition:
        """Return one registered tool."""

        return self._tools[name]

    def list_names(self) -> list[str]:
        """Return registered tool names sorted for deterministic tests."""

        return sorted(self._tools)

    def list_definitions(self) -> list[ToolDefinition]:
        """Return registered definitions sorted by stable tool name."""

        return [self._tools[name] for name in self.list_names()]

    def to_provider_schemas(self) -> list[dict[str, Any]]:
        """Return provider-neutral tool schemas without callables."""

        schemas: list[dict[str, Any]] = []
        for tool in self.list_definitions():
            schemas.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                    "allowed_roles": [role.value if isinstance(role, AgentRole) else str(role) for role in tool.allowed_roles],
                    "timeout_seconds": tool.timeout_seconds,
                    "result_policy": tool.result_policy,
                    "constraints": tool.constraints,
                }
            )
        return schemas
