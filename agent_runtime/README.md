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

## 未来角色职责

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

## TODO

- Phase 2 将 agent_contracts.py 的草案对齐到 agent_runtime。
- Phase 4 由 ms_agent_framework_adapter 映射到具体框架。
