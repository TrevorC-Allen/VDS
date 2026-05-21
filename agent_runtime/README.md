# agent_runtime

agent_runtime 是项目内部 Agent 抽象层。

## 边界

1. 不依赖 Microsoft Agent Framework。
2. 定义 Agent 角色、任务、结果、状态和工具注册协议。
3. Microsoft Agent Framework、LangGraph、CrewAI 或自研 workflow 都应该通过 adapter 调用这个抽象层。
4. data_agent_core 保持纯算法，不感知 Agent runtime。

## 概念草案

AgentRole:
- PLANNER
- DATA_ENGINEER
- PANDAS_EXECUTOR
- SQL_EXECUTOR
- VERIFIER
- CORRECTION
- INSIGHT
- VISUALIZATION
- BENCHMARK

## 当前角色职责

默认 analyze 的 Phase 6 workflow 通过这些 handler 执行。

1. PLANNER：Planner Agent，LLM 为主。
2. DATA_ENGINEER：Data Engineer Agent，代码为主，LLM 辅助字段语义。
3. PANDAS_EXECUTOR：Pandas Executor Agent，代码为主。
4. SQL_EXECUTOR：SQL Executor Agent，代码为主。
5. VERIFIER：Verifier Agent，规则为主，LLM 辅助。
6. CORRECTION：Correction Agent，LLM 生成修正方向，代码执行。
7. INSIGHT：Insight Agent，LLM 为主。
8. VISUALIZATION：Visualization Agent，规则 + LLM。
9. BENCHMARK：Benchmark Agent，代码为主，LLM 辅助错误归因。

AgentTask:
- task_id
- role
- input_payload
- context
- constraints

AgentResult:
- task_id
- role
- success
- output_payload
- issues
- confidence

WorkflowState:
- dataset_id
- question
- schema_profile
- logic_form
- analysis_plan
- pandas_result
- sql_result
- verification
- final_response
- tool_call_trace

## Phase 5 受控工具契约

ToolDefinition:
- name
- description
- input_schema
- allowed_roles
- timeout_seconds
- result_policy
- constraints

ToolCall:
- step_id
- tool_name
- arguments
- requested_by

ToolResult:
- step_id
- tool_name
- success
- output_payload
- warnings
- errors
- trace_event

当前白名单工具：

1. profile_schema
2. build_analysis_plan
3. execute_pandas_plan
4. execute_sql_plan
5. verify_results
6. build_chart_spec
7. generate_insight

工具层是 provider-neutral 的内部契约。OpenAI、DeepSeek、Microsoft Agent Framework、LangGraph 或 CrewAI 都只能通过 adapter 映射这些契约，不能直接改变 data_agent_core 的核心算法。

## 当前工具实现

agent_runtime/data_agent_tool_impl.py 提供受控 callable：

1. profile_schema 调用 schema profiler / DatasetProfile。
2. build_analysis_plan 调用 data_agent_core.core.analysis_planner。
3. execute_pandas_plan 调用 data_agent_core.executors.pandas_executor。
4. execute_sql_plan 调用 data_agent_core.executors.sql_executor。
5. verify_results 调用 result_comparator 和 rule_checker。
6. build_chart_spec 只基于已验证结果生成基础 ChartSpec。
7. generate_insight 只基于已验证结果生成基础 InsightResult。

这些工具不开放 raw Python、raw SQL、shell、网络或任意外部文件访问。

## Phase Status

- Phase 5：ToolDefinition、ToolCall、ToolResult、ToolTraceEvent、ToolDispatcher、tool catalog、timeout_seconds 执行边界和 provider-native mock loop 已建立。
- Phase 6：data_analysis_roles.py 已承载默认多 Agent 角色执行，backend analyze 默认经 multi_agent workflow 进入这些角色。
- 当前 verified 状态：DABstep public all 1-450 mock 执行覆盖 450/450，Microsoft 脱敏数据 1-300 mock 离线 scorer 300/300，桌面 VDS `问题汇总.xlsx` 95 题 smoke 95/95。
- 当前仍保留 single_agent fallback；真实 OpenAI / DeepSeek 网络 tool loop 尚未作为生产默认链路启用。

## 当前多 Agent 角色执行

agent_runtime/data_analysis_roles.py 提供 Phase 6 角色 handler：

1. Data Engineer Agent：调用 profile_schema。
2. Planner Agent：执行 LLM intent、LLM + 规则 column mapping、LLM plan，并通过 build_analysis_plan 工具生成 AnalysisPlan。
3. Pandas Executor Agent：调用 execute_pandas_plan。
4. SQL Executor Agent：对 SQL-compatible plan 调用 execute_sql_plan。
5. Verifier Agent：规则优先校验，并调用 LLM verifier critic。
6. Correction Agent：生成 bounded correction plan，不执行任意代码。
7. Insight Agent：在 verification 之后生成 insight。
8. Visualization Agent：在 verification 之后生成 chart spec。
9. Response Builder：生成稳定 FinalResponse。

## TODO

- Phase 5 已新增 provider-native OpenAI / DeepSeek 兼容 tool call adapter 骨架，保持内部 ToolDefinition 不变；后续再接真实 provider 网络调用和更完整工具循环验证。
- Phase 6 后续接真实 Microsoft Agent Framework cloud workflow、并行 executor 和更完整 Correction Loop。
- 继续增强 ACI associated cost 通用语义、真实 LLM 大规模回归和更多中文业务表能力，不允许把 Benchmark 标准答案传入角色执行。
