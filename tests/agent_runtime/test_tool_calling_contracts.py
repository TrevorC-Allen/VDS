"""Tests for provider-neutral controlled tool-calling contracts."""

from __future__ import annotations

import unittest
import json
import time

from agent_runtime.agent_role import AgentRole
from agent_runtime.data_agent_tool_catalog import TOOL_NAMES, build_data_agent_tool_registry
from agent_runtime.provider_native_tool_adapter import (
    ProviderNativeToolLoopAdapter,
    build_openai_tool_schemas,
    parse_openai_tool_calls,
)
from agent_runtime.tool_contracts import ToolCall
from agent_runtime.tool_dispatcher import ToolDispatcher
from agent_runtime.tool_registry import ToolDefinition, ToolRegistry
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

    def test_provider_native_schema_and_tool_call_parsing_are_openai_compatible(self) -> None:
        registry = build_data_agent_tool_registry()
        schemas = build_openai_tool_schemas(registry)
        self.assertEqual("function", schemas[0]["type"])
        self.assertIn("parameters", schemas[0]["function"])

        calls = parse_openai_tool_calls(
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "profile_schema", "arguments": json.dumps({"dataset_id": "ds_1"})},
                    }
                ],
            }
        )
        self.assertEqual("profile_schema", calls[0].tool_name)
        self.assertEqual({"dataset_id": "ds_1"}, calls[0].arguments)

    def test_provider_native_tool_loop_dispatches_through_tool_dispatcher(self) -> None:
        registry = build_data_agent_tool_registry(
            {
                "profile_schema": lambda arguments: {
                    "dataset_id": arguments["dataset_id"],
                    "tables": [{"table_name": "sales"}],
                }
            }
        )
        dispatcher = ToolDispatcher(registry)
        client = _FakeProviderClient(
            [
                {
                    "role": "assistant",
                    "reasoning_content": "must not be persisted",
                    "tool_calls": [
                        {
                            "id": "call_profile",
                            "type": "function",
                            "function": {"name": "profile_schema", "arguments": "{\"dataset_id\":\"ds_1\"}"},
                        }
                    ],
                },
                {"role": "assistant", "content": "{\"done\": true}"},
            ]
        )
        result = ProviderNativeToolLoopAdapter(client=client, registry=registry, dispatcher=dispatcher).run(
            [{"role": "user", "content": "profile ds_1"}]
        )

        self.assertEqual(1, len(result.tool_results))
        self.assertTrue(result.tool_results[0].success)
        self.assertEqual("profile_schema", result.trace_events[0]["tool_name"])
        self.assertNotIn("reasoning_content", result.messages[1])

    def test_dispatcher_enforces_tool_timeout(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="slow_tool",
                description="Test-only slow tool.",
                input_schema={"type": "object", "required": [], "properties": {}, "additionalProperties": False},
                allowed_roles=[AgentRole.PLANNER],
                timeout_seconds=0.01,
                callable_ref=lambda _arguments: time.sleep(1),
            )
        )

        result = ToolDispatcher(registry).dispatch(
            ToolCall(step_id="tool_timeout", tool_name="slow_tool", arguments={}, requested_by=AgentRole.PLANNER)
        )

        self.assertFalse(result.success)
        self.assertEqual("TOOL_DISPATCH_ERROR", result.errors[0]["error_type"])
        self.assertIn("timed out", result.errors[0]["error_message"])


class _FakeProviderClient:
    def __init__(self, messages: list[dict[str, object]]) -> None:
        self._messages = list(messages)

    def complete(self, messages: list[dict[str, object]], tools: list[dict[str, object]]) -> dict[str, object]:
        self.assertion_payload = {"message_count": len(messages), "tool_count": len(tools)}
        return self._messages.pop(0)


if __name__ == "__main__":
    unittest.main()
