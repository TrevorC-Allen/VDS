"""Declarative role mapping for future Microsoft Agent Framework integration."""

from __future__ import annotations

from dataclasses import dataclass

from agent_runtime.agent_role import AgentRole


@dataclass(frozen=True)
class FrameworkRoleMapping:
    """Framework-neutral description of a future Microsoft role mapping."""

    internal_role: AgentRole
    microsoft_step_kind: str
    responsibility: str


ROLE_MAPPINGS: dict[AgentRole, FrameworkRoleMapping] = {
    AgentRole.PLANNER: FrameworkRoleMapping(
        AgentRole.PLANNER,
        "planner_agent",
        "LLM-first intent and analysis planning.",
    ),
    AgentRole.DATA_ENGINEER: FrameworkRoleMapping(
        AgentRole.DATA_ENGINEER,
        "tool_or_agent_step",
        "Code-first schema checks with LLM-assisted field semantics.",
    ),
    AgentRole.PANDAS_EXECUTOR: FrameworkRoleMapping(
        AgentRole.PANDAS_EXECUTOR,
        "function_tool_step",
        "Code-only Pandas execution.",
    ),
    AgentRole.SQL_EXECUTOR: FrameworkRoleMapping(
        AgentRole.SQL_EXECUTOR,
        "function_tool_step",
        "Code-only SQL or DuckDB execution.",
    ),
    AgentRole.VERIFIER: FrameworkRoleMapping(
        AgentRole.VERIFIER,
        "verifier_agent_or_workflow_step",
        "Rule-first verification with LLM-assisted critique.",
    ),
    AgentRole.CORRECTION: FrameworkRoleMapping(
        AgentRole.CORRECTION,
        "workflow_step",
        "LLM proposes correction direction; code executes bounded retry.",
    ),
    AgentRole.INSIGHT: FrameworkRoleMapping(
        AgentRole.INSIGHT,
        "insight_agent",
        "LLM-first explanation after verification passes.",
    ),
    AgentRole.VISUALIZATION: FrameworkRoleMapping(
        AgentRole.VISUALIZATION,
        "visualization_agent_or_tool_step",
        "Rule-constrained chart planning with LLM assistance.",
    ),
    AgentRole.BENCHMARK: FrameworkRoleMapping(
        AgentRole.BENCHMARK,
        "evaluation_step",
        "Code-first evaluation with LLM-assisted error attribution.",
    ),
}


def get_role_mapping(role: AgentRole) -> FrameworkRoleMapping:
    """Return the future Microsoft mapping for one internal role."""

    return ROLE_MAPPINGS[role]
