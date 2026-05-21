"""Tests for optional Microsoft Agent Framework adapter behavior."""

from __future__ import annotations

import sys
import types
import unittest

import pandas as pd

from agent_runtime.agent_role import AgentRole
from agent_runtime.data_agent_tool_catalog import build_runtime_data_agent_tool_registry
from agent_runtime.data_agent_tool_impl import DataAgentToolRuntime
from ms_agent_framework_adapter.framework_tools import (
    MicrosoftAgentFrameworkUnavailable,
    build_microsoft_tool_functions,
    build_microsoft_tool_metadata,
)
from ms_agent_framework_adapter.framework_workflow import build_microsoft_sequential_workflow


class MicrosoftFrameworkAdapterTest(unittest.TestCase):
    def tearDown(self) -> None:
        sys.modules.pop("agent_framework", None)

    def test_metadata_builds_without_optional_package(self) -> None:
        metadata = build_microsoft_tool_metadata()
        self.assertGreaterEqual(len(metadata), 7)
        self.assertTrue(all(item["framework_kind"] == "function_tool" for item in metadata))

    def test_tool_function_build_raises_clear_error_without_package(self) -> None:
        sys.modules.pop("agent_framework", None)
        try:
            __import__("agent_framework")
        except Exception:
            pass
        else:
            self.skipTest("agent_framework is installed in this environment")
        with self.assertRaises(MicrosoftAgentFrameworkUnavailable):
            build_microsoft_tool_functions()

    def test_tool_functions_wrap_dispatcher_when_framework_is_present(self) -> None:
        def fake_tool(**decorator_kwargs):
            def decorate(func):
                func._ms_tool = decorator_kwargs
                return func

            return decorate

        sys.modules["agent_framework"] = types.SimpleNamespace(tool=fake_tool)

        runtime = DataAgentToolRuntime(
            dataset_contexts={
                "ds_1": {
                    "tables": {
                        "sales": pd.DataFrame(
                            [
                                {"city": "Shanghai", "sales": 120},
                                {"city": "Shanghai", "sales": 30},
                            ]
                        )
                    }
                }
            }
        )
        registry = build_runtime_data_agent_tool_registry(runtime)
        functions = build_microsoft_tool_functions(registry, requested_by_by_tool={"profile_schema": AgentRole.DATA_ENGINEER})
        by_name = {func.__name__: func for func in functions}
        result = by_name["profile_schema"](dataset_id="ds_1")
        self.assertTrue(result["success"])
        self.assertEqual("never_require", by_name["profile_schema"]._ms_tool["approval_mode"])
        self.assertIn("dataset_id", str(by_name["profile_schema"].__signature__))

    def test_workflow_builder_uses_role_order_when_framework_is_present(self) -> None:
        class FakeWorkflowBuilder:
            def __init__(self, start_executor):
                self.start_executor = start_executor
                self.edges = []

            def add_edge(self, left, right):
                self.edges.append((left, right))
                return self

            def build(self):
                return {"start": self.start_executor, "edges": self.edges}

        sys.modules["agent_framework"] = types.SimpleNamespace(WorkflowBuilder=FakeWorkflowBuilder)
        workflow = build_microsoft_sequential_workflow(
            {
                AgentRole.PLANNER: "planner_agent",
                AgentRole.DATA_ENGINEER: "data_engineer_agent",
                AgentRole.VERIFIER: "verifier_agent",
            }
        )
        self.assertEqual("planner_agent", workflow["start"])
        self.assertEqual([("planner_agent", "data_engineer_agent"), ("data_engineer_agent", "verifier_agent")], workflow["edges"])


if __name__ == "__main__":
    unittest.main()
