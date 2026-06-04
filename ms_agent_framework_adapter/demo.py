"""Serializable Microsoft Agent Framework adapter demo plan."""

from __future__ import annotations

from typing import Any

from ms_agent_framework_adapter.adapter import build_adapter_plan


def build_microsoft_adapter_demo_plan() -> dict[str, Any]:
    """Return an adapter-only demo plan without executing core algorithms."""

    adapter_plan = build_adapter_plan()
    workflow_steps = list(adapter_plan.get("workflow_steps") or [])
    tool_mappings = list(adapter_plan.get("tool_mappings") or [])
    return {
        "demo_name": "phase7_9_microsoft_agent_framework_adapter_demo",
        "framework": adapter_plan["framework"],
        "framework_available": adapter_plan["framework_available"],
        "optional_dependency": adapter_plan["optional_dependency"],
        "core_algorithm_location": adapter_plan["core_algorithm_location"],
        "runtime_contract_location": adapter_plan["runtime_contract_location"],
        "tool_count": len(tool_mappings),
        "workflow_role_order": [step["internal_role"] for step in workflow_steps],
        "smoke_steps": [
            "build_adapter_plan_without_core_imports",
            "build_tool_metadata_without_framework_package",
            "optionally_wrap_tools_when_agent_framework_is_installed",
            "optionally_build_sequential_workflow_when_agent_framework_is_installed",
        ],
        "boundary_assertions": [
            "data_agent_core_does_not_import_adapter",
            "adapter_does_not_parse_files",
            "adapter_does_not_execute_pandas",
            "adapter_does_not_execute_sql",
            "adapter_does_not_score_benchmarks",
            "provider_or_framework_adapters_do_not_own_core_algorithms",
        ],
    }
