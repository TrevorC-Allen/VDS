"""Agent contract drafts shared with the internal agent runtime.

TODO:
- Define AgentTask, AgentResult, and WorkflowState contracts.
- Keep these aligned with agent_runtime without importing framework-specific
  packages.
- Allow future adapters to map the internal contracts to Microsoft Agent
  Framework, LangGraph, CrewAI, or a self-hosted workflow runtime.

Draft structures:
- AgentTask: task_id, role, input_payload, context, constraints
- AgentResult: task_id, role, success, output_payload, issues, confidence
- WorkflowState: dataset_id, question, schema_profile, logic_form,
  analysis_plan, pandas_result, sql_result, verification, final_response
"""
