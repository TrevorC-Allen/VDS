"""Canonical provider-neutral Data Agent tool catalog."""

from __future__ import annotations

from typing import Any

from agent_runtime.agent_role import AgentRole
from agent_runtime.tool_registry import ToolCallable, ToolDefinition, ToolRegistry


TOOL_NAMES = [
    "profile_schema",
    "build_analysis_plan",
    "execute_pandas_plan",
    "execute_sql_plan",
    "verify_results",
    "build_chart_spec",
    "generate_insight",
]


def build_data_agent_tool_registry(overrides: dict[str, ToolCallable] | None = None) -> ToolRegistry:
    """Build the internal Phase 5 tool registry without provider dependencies."""

    overrides = overrides or {}
    registry = ToolRegistry()
    for tool in _tool_definitions(overrides):
        registry.register(tool)
    return registry


def build_runtime_data_agent_tool_registry(runtime: Any) -> ToolRegistry:
    """Build the canonical registry bound to executable core tool callables."""

    from agent_runtime.data_agent_tool_impl import build_data_agent_tool_overrides

    return build_data_agent_tool_registry(build_data_agent_tool_overrides(runtime))


def _tool_definitions(overrides: dict[str, ToolCallable]) -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="profile_schema",
            description="Return DatasetProfile/TableProfile/ColumnProfile summaries for a dataset.",
            input_schema=_object_schema(required=["dataset_id"], properties={"dataset_id": "string"}),
            allowed_roles=[AgentRole.DATA_ENGINEER, AgentRole.PLANNER],
            timeout_seconds=10,
            result_policy="summary_only",
            constraints=_safe_tool_constraints(),
            callable_ref=overrides.get("profile_schema"),
        ),
        ToolDefinition(
            name="build_analysis_plan",
            description="Build a LogicForm and AnalysisPlan from validated intent and column mapping.",
            input_schema=_object_schema(
                required=["dataset_id", "intent", "column_mapping"],
                properties={"dataset_id": "string", "intent": "object", "column_mapping": "object"},
            ),
            allowed_roles=[AgentRole.PLANNER],
            timeout_seconds=10,
            result_policy="structured_plan_only",
            constraints=_safe_tool_constraints(),
            callable_ref=overrides.get("build_analysis_plan"),
        ),
        ToolDefinition(
            name="execute_pandas_plan",
            description="Execute a validated AnalysisPlan with the Pandas/NumPy path.",
            input_schema=_object_schema(
                required=["dataset_id", "analysis_plan"],
                properties={"dataset_id": "string", "analysis_plan": "object"},
            ),
            allowed_roles=[AgentRole.PANDAS_EXECUTOR],
            timeout_seconds=30,
            result_policy="execution_summary_only",
            constraints=_safe_tool_constraints(),
            callable_ref=overrides.get("execute_pandas_plan"),
        ),
        ToolDefinition(
            name="execute_sql_plan",
            description="Execute a validated AnalysisPlan with the SQL/DuckDB path.",
            input_schema=_object_schema(
                required=["dataset_id", "analysis_plan"],
                properties={"dataset_id": "string", "analysis_plan": "object"},
            ),
            allowed_roles=[AgentRole.SQL_EXECUTOR],
            timeout_seconds=30,
            result_policy="execution_summary_only",
            constraints=_safe_tool_constraints(),
            callable_ref=overrides.get("execute_sql_plan"),
        ),
        ToolDefinition(
            name="verify_results",
            description="Compare execution results and return verification notes, confidence, and issues.",
            input_schema=_object_schema(
                required=["pandas_result", "sql_result"],
                properties={"pandas_result": "object", "sql_result": "object"},
            ),
            allowed_roles=[AgentRole.VERIFIER],
            timeout_seconds=15,
            result_policy="verification_summary_only",
            constraints=_safe_tool_constraints(),
            callable_ref=overrides.get("verify_results"),
        ),
        ToolDefinition(
            name="build_chart_spec",
            description="Build a frontend-neutral chart spec from verified results.",
            input_schema=_object_schema(
                required=["analysis_plan", "verified_result"],
                properties={"analysis_plan": "object", "verified_result": "object"},
            ),
            allowed_roles=[AgentRole.VISUALIZATION],
            timeout_seconds=10,
            result_policy="chart_spec_only",
            constraints=_safe_tool_constraints(),
            callable_ref=overrides.get("build_chart_spec"),
        ),
        ToolDefinition(
            name="generate_insight",
            description="Generate concise insight from verified results only.",
            input_schema=_object_schema(
                required=["question", "verified_result"],
                properties={"question": "string", "verified_result": "object"},
            ),
            allowed_roles=[AgentRole.INSIGHT],
            timeout_seconds=20,
            result_policy="insight_summary_only",
            constraints=_safe_tool_constraints(),
            callable_ref=overrides.get("generate_insight"),
        ),
    ]


def _object_schema(required: list[str], properties: dict[str, str]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": required,
        "properties": {name: {"type": type_name} for name, type_name in properties.items()},
        "additionalProperties": False,
    }


def _safe_tool_constraints() -> dict[str, Any]:
    return {
        "network_access": False,
        "shell_access": False,
        "external_file_access": False,
        "raw_python": False,
        "raw_sql": False,
        "benchmark_answer_access": False,
    }
