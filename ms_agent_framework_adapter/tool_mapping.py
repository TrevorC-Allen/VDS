"""Tool mapping for Microsoft Agent Framework integration."""

from __future__ import annotations

from dataclasses import dataclass

from agent_runtime.data_agent_tool_catalog import build_data_agent_tool_registry


@dataclass(frozen=True)
class ToolMapping:
    """One internal tool exposed to a future framework adapter."""

    internal_name: str
    framework_kind: str
    code_owner: str
    result_policy: str
    timeout_seconds: int


_CODE_OWNER_BY_TOOL = {
    "profile_schema": "data_agent_core.core.schema_profiler",
    "build_analysis_plan": "data_agent_core.core.analysis_planner",
    "execute_pandas_plan": "data_agent_core.executors.pandas_executor",
    "execute_sql_plan": "data_agent_core.executors.sql_executor",
    "verify_results": "data_agent_core.verifier",
    "build_chart_spec": "data_agent_core.output.chart_planner",
    "generate_insight": "data_agent_core.output.insight_generator",
}


def build_tool_mappings() -> list[ToolMapping]:
    """Return declarative tool mappings without importing Microsoft packages."""

    registry = build_data_agent_tool_registry()
    return [
        ToolMapping(
            internal_name=tool.name,
            framework_kind="function_tool",
            code_owner=_CODE_OWNER_BY_TOOL[tool.name],
            result_policy=tool.result_policy,
            timeout_seconds=tool.timeout_seconds,
        )
        for tool in registry.list_definitions()
    ]


TOOL_MAPPINGS = build_tool_mappings()
