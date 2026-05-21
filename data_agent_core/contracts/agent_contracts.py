"""Agent contract notes shared with the internal agent runtime.

The concrete runtime contracts live in agent_runtime so data_agent_core remains
pure algorithm code and does not need to know about workflow orchestration.

Stable shapes:
- AgentTask: task_id, role, input_payload, context, constraints
- AgentResult: task_id, role, success, output_payload, issues, confidence
- WorkflowState: dataset_id, question, schema_profile, logic_form,
  analysis_plan, pandas_result, sql_result, verification, final_response,
  tool_call_trace
- ToolDefinition: name, description, input_schema, allowed_roles,
  timeout_seconds, result_policy, constraints
- ToolCall: step_id, tool_name, arguments, requested_by
- ToolResult: step_id, tool_name, success, output_payload, warnings, errors,
  trace_event

Adapters for Microsoft Agent Framework, LangGraph, CrewAI, or a self-hosted
runtime must map these shapes instead of changing core algorithms.
"""
