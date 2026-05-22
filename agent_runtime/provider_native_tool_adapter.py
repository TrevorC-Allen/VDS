"""Provider-native tool calling adapter for OpenAI-compatible providers.

This module only maps provider tool schemas and tool call messages to the
internal ToolDefinition / ToolCall / ToolResult contracts. Real execution still
goes through ToolDispatcher.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from agent_runtime.agent_role import AgentRole
from agent_runtime.tool_contracts import ToolCall, ToolResult
from agent_runtime.tool_dispatcher import ToolDispatcher
from agent_runtime.tool_registry import ToolDefinition, ToolRegistry


TOOL_ROLE_BY_NAME = {
    "profile_schema": AgentRole.DATA_ENGINEER,
    "build_analysis_plan": AgentRole.PLANNER,
    "execute_pandas_plan": AgentRole.PANDAS_EXECUTOR,
    "execute_sql_plan": AgentRole.SQL_EXECUTOR,
    "verify_results": AgentRole.VERIFIER,
    "build_chart_spec": AgentRole.VISUALIZATION,
    "generate_insight": AgentRole.INSIGHT,
}


class NativeToolChatClient(Protocol):
    """Minimal protocol for OpenAI-compatible chat clients with tools."""

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        """Return one assistant message dict, potentially with tool_calls."""


@dataclass
class ProviderToolCall:
    """Provider tool call normalized before dispatch."""

    provider_call_id: str
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderToolLoopResult:
    """Provider-native tool loop output safe for traces."""

    final_message: dict[str, Any]
    tool_results: list[ToolResult] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)

    @property
    def trace_events(self) -> list[dict[str, Any]]:
        """Return trace-safe tool events."""

        events: list[dict[str, Any]] = []
        for result in self.tool_results:
            if result.trace_event is not None:
                events.append(result.trace_event.to_dict())
        return events


def build_openai_tool_schemas(registry: ToolRegistry) -> list[dict[str, Any]]:
    """Map internal tool definitions to OpenAI / DeepSeek compatible schemas."""

    return [_openai_tool_schema(tool) for tool in registry.list_definitions()]


def parse_openai_tool_calls(message: dict[str, Any]) -> list[ProviderToolCall]:
    """Parse OpenAI-compatible assistant message tool_calls."""

    calls: list[ProviderToolCall] = []
    for raw_call in message.get("tool_calls") or []:
        function = raw_call.get("function") or {}
        arguments = function.get("arguments") or "{}"
        if isinstance(arguments, str):
            parsed_arguments = json.loads(arguments or "{}")
        elif isinstance(arguments, dict):
            parsed_arguments = arguments
        else:
            raise ValueError("Provider tool call arguments must be JSON object text or a dict.")
        if not isinstance(parsed_arguments, dict):
            raise ValueError("Provider tool call arguments must decode to a JSON object.")
        calls.append(
            ProviderToolCall(
                provider_call_id=str(raw_call.get("id") or function.get("name") or "tool_call"),
                tool_name=str(function["name"]),
                arguments=parsed_arguments,
            )
        )
    return calls


def dispatch_provider_tool_call(
    *,
    provider_call: ProviderToolCall,
    dispatcher: ToolDispatcher,
    step_prefix: str = "provider_tool",
) -> ToolResult:
    """Dispatch one provider-native tool call through the internal dispatcher."""

    requested_by = TOOL_ROLE_BY_NAME.get(provider_call.tool_name, AgentRole.PLANNER)
    return dispatcher.dispatch(
        ToolCall(
            step_id=f"{step_prefix}_{provider_call.provider_call_id}",
            tool_name=provider_call.tool_name,
            arguments=provider_call.arguments,
            requested_by=requested_by,
        )
    )


def build_openai_tool_result_message(provider_call: ProviderToolCall, result: ToolResult) -> dict[str, Any]:
    """Build a provider-compatible tool result message."""

    payload = {
        "success": result.success,
        "tool_name": result.tool_name,
        "output_payload": result.output_payload,
        "warnings": result.warnings,
        "errors": result.errors,
    }
    return {
        "role": "tool",
        "tool_call_id": provider_call.provider_call_id,
        "content": json.dumps(payload, ensure_ascii=False),
    }


class ProviderNativeToolLoopAdapter:
    """Small OpenAI-compatible tool loop that delegates execution locally."""

    def __init__(
        self,
        *,
        client: NativeToolChatClient,
        registry: ToolRegistry,
        dispatcher: ToolDispatcher,
        max_tool_rounds: int = 4,
    ) -> None:
        self.client = client
        self.registry = registry
        self.dispatcher = dispatcher
        self.max_tool_rounds = max_tool_rounds

    def run(self, messages: list[dict[str, Any]]) -> ProviderToolLoopResult:
        """Run bounded provider-native tool loop and return trace-safe result."""

        active_messages = [dict(message) for message in messages]
        tools = build_openai_tool_schemas(self.registry)
        tool_results: list[ToolResult] = []
        final_message: dict[str, Any] = {}
        for _ in range(self.max_tool_rounds):
            assistant_message = self.client.complete(active_messages, tools)
            final_message = _strip_reasoning_fields(assistant_message)
            active_messages.append(final_message)
            provider_calls = parse_openai_tool_calls(assistant_message)
            if not provider_calls:
                return ProviderToolLoopResult(final_message=final_message, tool_results=tool_results, messages=active_messages)
            for provider_call in provider_calls:
                result = dispatch_provider_tool_call(provider_call=provider_call, dispatcher=self.dispatcher)
                tool_results.append(result)
                active_messages.append(build_openai_tool_result_message(provider_call, result))
        return ProviderToolLoopResult(final_message=final_message, tool_results=tool_results, messages=active_messages)


def _openai_tool_schema(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        },
    }


def _strip_reasoning_fields(message: dict[str, Any]) -> dict[str, Any]:
    blocked = {"reasoning", "reasoning_content", "chain_of_thought", "hidden_reasoning"}
    return {key: value for key, value in message.items() if key not in blocked}
