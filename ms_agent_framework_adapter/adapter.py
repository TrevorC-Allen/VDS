"""Microsoft Agent Framework adapter boundary.

This module intentionally does not import Microsoft Agent Framework yet. It
only exposes a declarative adapter plan so Phase 4 can wire framework-specific
objects without changing data_agent_core.
"""

from __future__ import annotations

from typing import Any

from ms_agent_framework_adapter.workflow_mapping import build_workflow_mapping


def build_adapter_plan() -> dict[str, Any]:
    """Return a serializable adapter plan without importing Microsoft packages."""

    return {
        "framework": "microsoft_agent_framework",
        "imports_framework": False,
        "core_algorithm_location": "data_agent_core",
        "runtime_contract_location": "agent_runtime",
        "workflow_steps": [
            {
                "step_index": step.step_index,
                "internal_role": step.role_mapping.internal_role.value,
                "microsoft_step_kind": step.role_mapping.microsoft_step_kind,
                "responsibility": step.role_mapping.responsibility,
            }
            for step in build_workflow_mapping()
        ],
        "boundary_rules": [
            "adapter_does_not_parse_files",
            "adapter_does_not_execute_pandas",
            "adapter_does_not_execute_sql",
            "adapter_does_not_score_benchmarks",
            "data_agent_core_does_not_import_adapter",
        ],
    }
