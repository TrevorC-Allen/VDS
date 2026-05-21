# ms_agent_framework_adapter

本目录只负责未来接入 Microsoft Agent Framework。

## 当前阶段

1. 当前不作为核心依赖。
2. 当前不安装 Microsoft Agent Framework。
3. 当前不实现业务逻辑。
4. 核心算法仍在 data_agent_core/。
5. 内部 Agent 抽象仍在 agent_runtime/。
6. 本目录负责把 agent_runtime 的角色、任务、工具和状态映射到 Microsoft Agent Framework。
7. 如果未来更换框架，只需要新增新的 adapter，不需要重写核心算法。

## 未来映射关系

agent_runtime.AgentRole.PLANNER
→ Microsoft Agent Framework Planner Agent，LLM 为主

agent_runtime.AgentRole.PANDAS_EXECUTOR
→ Microsoft Agent Framework Tool / Function Step，代码为主

agent_runtime.AgentRole.SQL_EXECUTOR
→ Microsoft Agent Framework Tool / Function Step，代码为主

agent_runtime.AgentRole.VERIFIER
→ Microsoft Agent Framework Verifier Agent / Workflow Step，规则为主，LLM 辅助

agent_runtime.AgentRole.DATA_ENGINEER
→ Microsoft Agent Framework Tool / Agent Step，代码为主，LLM 辅助字段语义

agent_runtime.AgentRole.CORRECTION
→ Microsoft Agent Framework Agent / Workflow Step，LLM 生成修正方向，代码执行

agent_runtime.AgentRole.INSIGHT
→ Microsoft Agent Framework Insight Agent，LLM 为主

agent_runtime.AgentRole.VISUALIZATION
→ Microsoft Agent Framework Visualization Agent / Tool Step，规则 + LLM

agent_runtime.AgentRole.BENCHMARK
→ Microsoft Agent Framework Evaluation Step，代码为主，LLM 辅助错误归因

agent_runtime.WorkflowState
→ Microsoft Agent Framework Workflow State / Session State

agent_runtime.ToolDefinition / ToolCall / ToolResult
→ Microsoft Agent Framework Function Tool / Tool Call / Tool Result

当前适配层只导出 declarative tool mapping：

1. profile_schema
2. build_analysis_plan
3. execute_pandas_plan
4. execute_sql_plan
5. verify_results
6. build_chart_spec
7. generate_insight

这些 mapping 只说明未来 Microsoft Agent Framework 应如何暴露内部工具，不实现工具逻辑。

## 禁止事项

1. 禁止在 adapter 中写文件解析逻辑。
2. 禁止在 adapter 中写 Pandas 执行逻辑。
3. 禁止在 adapter 中写 SQL 执行逻辑。
4. 禁止在 adapter 中写 Benchmark 特判。
5. 禁止让 data_agent_core import ms_agent_framework_adapter。
6. 本轮禁止安装 Microsoft Agent Framework 依赖。

## TODO

- Phase 4/5 验证 adapter 不污染核心算法依赖边界。
- Phase 5 以后再接 Microsoft Agent Framework 真实 tool/function step。
- Phase 6+ 再做多 Agent workflow 编排。
