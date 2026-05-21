"""Optional Microsoft Agent Framework agent factory for Data Agent roles."""

from __future__ import annotations

from typing import Any

from agent_runtime.agent_role import AgentRole
from agent_runtime.tool_registry import ToolRegistry
from ms_agent_framework_adapter.framework_tools import (
    MicrosoftAgentFrameworkUnavailable,
    build_microsoft_tool_functions,
)


ROLE_INSTRUCTIONS = {
    AgentRole.PLANNER: "Generate structured analysis plans for uploaded datasets. Do not execute calculations.",
    AgentRole.DATA_ENGINEER: "Inspect schema, field semantics, and data readiness through approved tools.",
    AgentRole.PANDAS_EXECUTOR: "Execute approved Pandas analysis plans through tools only.",
    AgentRole.SQL_EXECUTOR: "Execute approved SQL or DuckDB analysis plans through tools only.",
    AgentRole.VERIFIER: "Verify execution consistency and flag issues without fabricating conclusions.",
    AgentRole.CORRECTION: "Propose bounded correction directions; execution remains tool-controlled.",
    AgentRole.INSIGHT: "Generate concise insight only from verified results.",
    AgentRole.VISUALIZATION: "Build frontend-neutral chart specs only from verified results.",
}


def build_data_analysis_agents(client: Any, registry: ToolRegistry) -> dict[AgentRole, Any]:
    """Create Microsoft Agent Framework agents for the internal role set."""

    Agent = _load_agent_class()
    agents: dict[AgentRole, Any] = {}
    for role, instructions in ROLE_INSTRUCTIONS.items():
        role_registry = _registry_for_role(registry, role)
        role_tools = build_microsoft_tool_functions(role_registry, requested_by_by_tool={name: role for name in role_registry.list_names()})
        agents[role] = Agent(
            client=client,
            name=f"DataAgent_{role.value}",
            instructions=instructions,
            tools=role_tools,
        )
    return agents


def _registry_for_role(registry: ToolRegistry, role: AgentRole) -> ToolRegistry:
    selected = ToolRegistry()
    for tool in registry.list_definitions():
        if role in tool.allowed_roles:
            selected.register(tool)
    return selected


def _load_agent_class() -> Any:
    try:
        from agent_framework import Agent
    except Exception as exc:  # noqa: BLE001 - adapter must provide a clear optional dependency error.
        raise MicrosoftAgentFrameworkUnavailable(
            "Microsoft Agent Framework is not installed. Install locally with `pip install agent-framework` "
            "when running the optional agent factory."
        ) from exc
    return Agent
