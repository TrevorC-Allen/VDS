"""Tests for provider-neutral controlled tool-calling contracts."""

from __future__ import annotations

import unittest
import json
import time
from unittest.mock import patch

from agent_runtime.agent_role import AgentRole
from agent_runtime.data_agent_tool_catalog import TOOL_NAMES, build_data_agent_tool_registry
from agent_runtime.provider_native_tool_adapter import (
    NativeToolChatConfig,
    OpenAICompatibleNativeToolChatClient,
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

    def test_openai_compatible_native_tool_client_builds_real_smoke_payload(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["authorization"] = request.get_header("Authorization")
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return _FakeHTTPResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "{\"ok\": true}",
                                "reasoning_content": "must not persist",
                            }
                        }
                    ]
                }
            )

        client = OpenAICompatibleNativeToolChatClient(
            NativeToolChatConfig(
                provider="openai",
                api_key="local-provider-key",
                model="test-model",
                base_url="https://provider.example/v1",
                timeout_seconds=7,
            )
        )
        with patch("agent_runtime.provider_native_tool_adapter.urllib.request.urlopen", fake_urlopen):
            message = client.complete([{"role": "user", "content": "use a tool"}], [{"type": "function", "function": {"name": "x"}}])

        self.assertEqual("https://provider.example/v1/chat/completions", captured["url"])
        self.assertEqual(7, captured["timeout"])
        self.assertEqual("Bearer local-provider-key", captured["authorization"])
        self.assertEqual("test-model", captured["payload"]["model"])
        self.assertEqual("auto", captured["payload"]["tool_choice"])
        self.assertNotIn("reasoning_content", message)

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

    def test_dispatcher_redacts_sensitive_trace_error_and_output_payload(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="secret_echo",
                description="Test-only tool with sensitive fields.",
                input_schema={
                    "type": "object",
                    "required": ["dataset_id", "api_key", "analysis_plan"],
                    "properties": {
                        "dataset_id": {"type": "string"},
                        "api_key": {"type": "string"},
                        "analysis_plan": {
                            "type": "object",
                            "required": ["operation"],
                            "properties": {
                                "operation": {"type": "string", "enum": ["profile"]},
                                "expected_answer": {"type": "string"},
                            },
                            "additionalProperties": False,
                        },
                    },
                    "additionalProperties": False,
                },
                allowed_roles=[AgentRole.PLANNER],
                timeout_seconds=1,
                callable_ref=lambda _arguments: {
                    "visible": "ok",
                    "authorization": "Bearer local-token",
                    "nested": {"proxy_answer": "42"},
                },
            )
        )
        result = ToolDispatcher(registry).dispatch(
            ToolCall(
                step_id="tool_secret",
                tool_name="secret_echo",
                arguments={
                    "dataset_id": "ds_1",
                    "api_key": "local-token",
                    "analysis_plan": {"operation": "profile", "expected_answer": "42"},
                },
                requested_by=AgentRole.PLANNER,
            )
        )

        self.assertTrue(result.success)
        self.assertEqual("[REDACTED]", result.output_payload["authorization"])
        self.assertEqual("[REDACTED]", result.output_payload["nested"]["proxy_answer"])
        trace_text = json.dumps(result.trace_event.to_dict(), ensure_ascii=False)
        self.assertNotIn("local-token", trace_text)
        self.assertNotIn("expected_answer", trace_text)
        self.assertNotIn("proxy_answer", trace_text)

        registry.register(
            ToolDefinition(
                name="secret_failure",
                description="Test-only failing tool.",
                input_schema={"type": "object", "required": [], "properties": {}, "additionalProperties": False},
                allowed_roles=[AgentRole.PLANNER],
                timeout_seconds=1,
                callable_ref=lambda _arguments: (_ for _ in ()).throw(RuntimeError("api key local-token leaked")),
            )
        )
        failure = ToolDispatcher(registry).dispatch(
            ToolCall(step_id="tool_secret_failure", tool_name="secret_failure", arguments={}, requested_by=AgentRole.PLANNER)
        )
        self.assertFalse(failure.success)
        self.assertEqual("[REDACTED]", failure.errors[0]["error_message"])
        self.assertEqual("[REDACTED]", failure.trace_event.error)

    def test_dispatcher_rejects_nested_unsafe_arguments_and_schema_enum(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="safe_plan",
                description="Test-only nested schema validation.",
                input_schema={
                    "type": "object",
                    "required": ["analysis_plan"],
                    "properties": {
                        "analysis_plan": {
                            "type": "object",
                            "required": ["operation"],
                            "properties": {"operation": {"type": "string", "enum": ["profile", "aggregate"]}},
                            "additionalProperties": True,
                        }
                    },
                    "additionalProperties": False,
                },
                allowed_roles=[AgentRole.PLANNER],
                timeout_seconds=1,
                callable_ref=lambda arguments: {"operation": arguments["analysis_plan"]["operation"]},
            )
        )
        dispatcher = ToolDispatcher(registry)

        unsafe = dispatcher.dispatch(
            ToolCall(
                step_id="tool_unsafe",
                tool_name="safe_plan",
                arguments={"analysis_plan": {"operation": "profile", "raw_sql": "select * from table"}},
                requested_by=AgentRole.PLANNER,
            )
        )
        self.assertFalse(unsafe.success)
        self.assertIn("forbidden unsafe argument keys", unsafe.errors[0]["error_message"])

        invalid_enum = dispatcher.dispatch(
            ToolCall(
                step_id="tool_invalid_enum",
                tool_name="safe_plan",
                arguments={"analysis_plan": {"operation": "drop"}},
                requested_by=AgentRole.PLANNER,
            )
        )
        self.assertFalse(invalid_enum.success)
        self.assertIn("must be one of", invalid_enum.errors[0]["error_message"])


class _FakeProviderClient:
    def __init__(self, messages: list[dict[str, object]]) -> None:
        self._messages = list(messages)

    def complete(self, messages: list[dict[str, object]], tools: list[dict[str, object]]) -> dict[str, object]:
        self.assertion_payload = {"message_count": len(messages), "tool_count": len(tools)}
        return self._messages.pop(0)


class _FakeHTTPResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
