"""Framework-neutral tool registry for future agent runtimes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


ToolCallable = Callable[..., Any]


@dataclass
class ToolDefinition:
    """Internal tool metadata before exposing it through any framework."""

    name: str
    callable_ref: ToolCallable | None = None
    description: str = ""
    constraints: dict[str, Any] = field(default_factory=dict)


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
