"""Microsoft Agent Framework adapter boundary.

The adapter may optionally import Microsoft Agent Framework inside dedicated
adapter modules. data_agent_core remains framework-neutral.
"""

from __future__ import annotations

from typing import Any

from ms_agent_framework_adapter.framework_tools import build_microsoft_tool_metadata, is_framework_available
from ms_agent_framework_adapter.tool_mapping import TOOL_MAPPINGS
from ms_agent_framework_adapter.workflow_mapping import build_workflow_mapping


def build_adapter_plan() -> dict[str, Any]:
    """Return a serializable Microsoft adapter plan."""

    return {
        "framework": "microsoft_agent_framework",
        "imports_framework": is_framework_available(),
        "framework_available": is_framework_available(),
        "optional_dependency": "agent-framework",
        "core_algorithm_location": "data_agent_core",
        "runtime_contract_location": "agent_runtime",
        "tool_adapter": "ms_agent_framework_adapter.framework_tools.build_microsoft_tool_functions",
        "agent_factory": "ms_agent_framework_adapter.framework_agents.build_data_analysis_agents",
        "workflow_factory": "ms_agent_framework_adapter.framework_workflow.build_microsoft_sequential_workflow",
        "workflow_steps": [
            {
                "step_index": step.step_index,
                "internal_role": step.role_mapping.internal_role.value,
                "microsoft_step_kind": step.role_mapping.microsoft_step_kind,
                "responsibility": step.role_mapping.responsibility,
            }
            for step in build_workflow_mapping()
        ],
        "tool_mappings": [
            {
                "internal_name": tool.internal_name,
                "framework_kind": tool.framework_kind,
                "code_owner": tool.code_owner,
                "result_policy": tool.result_policy,
                "timeout_seconds": tool.timeout_seconds,
            }
            for tool in TOOL_MAPPINGS
        ],
        "microsoft_tool_metadata": build_microsoft_tool_metadata(),
        "boundary_rules": [
            "adapter_does_not_parse_files",
            "adapter_does_not_execute_pandas",
            "adapter_does_not_execute_sql",
            "adapter_does_not_score_benchmarks",
            "data_agent_core_does_not_import_adapter",
        ],
    }
