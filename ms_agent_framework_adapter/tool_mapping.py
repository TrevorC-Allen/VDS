"""Tool mapping draft for future Microsoft Agent Framework integration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolMapping:
    """One internal tool exposed to a future framework adapter."""

    internal_name: str
    framework_kind: str
    code_owner: str


TOOL_MAPPINGS = [
    ToolMapping("parse_uploaded_file", "function_tool", "data_agent_core.core.file_parser"),
    ToolMapping("profile_schema", "function_tool", "data_agent_core.core.schema_profiler"),
    ToolMapping("execute_pandas_plan", "function_tool", "data_agent_core.executors.pandas_executor"),
    ToolMapping("execute_sql_plan", "function_tool", "data_agent_core.executors.sql_executor"),
    ToolMapping("verify_results", "function_tool", "data_agent_core.verifier"),
]
