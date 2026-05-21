"""Tests for provider-neutral controlled tool-calling contracts."""

from __future__ import annotations

import unittest

from agent_runtime.agent_role import AgentRole
from agent_runtime.data_agent_tool_catalog import TOOL_NAMES, build_data_agent_tool_registry
from agent_runtime.tool_contracts import ToolCall
from agent_runtime.tool_dispatcher import ToolDispatcher
from ms_agent_framework_adapter.tool_mapping import build_tool_mappings


class ToolCallingContractTest(unittest.TestCase):
    def test_data_agent_tool_catalog_has_required_metadata(self) -> None:
        registry = build_data_agent_tool_registry()
        self.assertEqual(sorted(TOOL_NAMES), registry.list_names())
        for tool in registry.list_definitions():
            self.assertTrue(tool.input_schema["required"])
            self.assertTrue(tool.allowed_roles)
            self.assertGreater(tool.timeout_seconds, 0)
            self.assertIn("network_access", tool.constraints)
            self.assertFalse(tool.constraints["network_access"])
            self.assertFalse(tool.constraints["shell_access"])

    def test_dispatcher_validates_role_and_arguments(self) -> None:
        registry = build_data_agent_tool_registry(
            {
                "profile_schema": lambda arguments: {
                    "dataset_id": arguments["dataset_id"],
                    "tables": [{"table_name": "sales"}],
                }
            }
        )
        dispatcher = ToolDispatcher(registry)

        result = dispatcher.dispatch(
            ToolCall(
                step_id="tool_001",
                tool_name="profile_schema",
                arguments={"dataset_id": "ds_1"},
                requested_by=AgentRole.DATA_ENGINEER,
            )
        )
        self.assertTrue(result.success)
        self.assertEqual("ds_1", result.output_payload["dataset_id"])
        self.assertEqual("profile_schema", result.trace_event.tool_name)
        self.assertEqual({"dataset_id": "ds_1"}, result.trace_event.arguments_summary)

        forbidden = dispatcher.dispatch(
            ToolCall(
                step_id="tool_002",
                tool_name="profile_schema",
                arguments={"dataset_id": "ds_1"},
                requested_by=AgentRole.SQL_EXECUTOR,
            )
        )
        self.assertFalse(forbidden.success)
        self.assertEqual("TOOL_DISPATCH_ERROR", forbidden.errors[0]["error_type"])

        missing = dispatcher.dispatch(
            ToolCall(
                step_id="tool_003",
                tool_name="profile_schema",
                arguments={},
                requested_by=AgentRole.DATA_ENGINEER,
            )
        )
        self.assertFalse(missing.success)
        self.assertIn("Missing required", missing.errors[0]["error_message"])

    def test_adapter_tool_mapping_is_declarative(self) -> None:
        mappings = build_tool_mappings()
        self.assertEqual(sorted(TOOL_NAMES), sorted(mapping.internal_name for mapping in mappings))
        self.assertTrue(all(mapping.framework_kind == "function_tool" for mapping in mappings))
        self.assertTrue(all(mapping.timeout_seconds > 0 for mapping in mappings))


if __name__ == "__main__":
    unittest.main()
