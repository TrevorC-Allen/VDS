# ms_agent_framework_adapter

本目录只负责接入 Microsoft Agent Framework。

## 当前阶段

1. 当前仍不作为核心依赖。
2. 当前不强制安装 Microsoft Agent Framework；本地运行可选 adapter 时再安装 `agent-framework`。
3. 当前不实现核心业务逻辑。
4. 核心算法仍在 data_agent_core/。
5. 内部 Agent 抽象仍在 agent_runtime/。
6. 本目录负责把 agent_runtime 的角色、任务、工具和状态映射到 Microsoft Agent Framework。
7. 如果未来更换框架，只需要新增新的 adapter，不需要重写核心算法。
8. framework_tools.py 负责把内部 ToolDefinition 包装为 Microsoft function tool。
9. framework_agents.py 负责把 AgentRole 映射为 Microsoft Agent Framework Agent。
10. framework_workflow.py 负责构建 sequential workflow。

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

当前适配层导出 declarative tool mapping，并提供可选 Microsoft function tool 包装：

1. profile_schema
2. build_analysis_plan
3. execute_pandas_plan
4. execute_sql_plan
5. verify_results
6. build_chart_spec
7. generate_insight

这些工具的真实执行逻辑位于 agent_runtime/data_agent_tool_impl.py，并继续调用 data_agent_core；adapter 只做 Microsoft 框架包装。

## 可选运行方式

本地需要实际运行 Microsoft Agent Framework adapter 时：

```bash
pip install -r requirements-ms-agent.txt
```

如果需要 Azure Foundry、OpenAI、Anthropic、Redis 等完整 provider extras，再按官方文档安装完整 `agent-framework` 包。

adapter 不会自动读取 `.env`。模型、Azure Foundry 或其他 provider 配置应由运行脚本从环境变量显式传入，禁止提交 key。

## 禁止事项

1. 禁止在 adapter 中写文件解析逻辑。
2. 禁止在 adapter 中写 Pandas 执行逻辑。
3. 禁止在 adapter 中写 SQL 执行逻辑。
4. 禁止在 adapter 中写 Benchmark 特判。
5. 禁止让 data_agent_core import ms_agent_framework_adapter。
6. 禁止把 Microsoft Agent Framework 作为 data_agent_core 或 backend 的强依赖。

## TODO

- 后续接真实 Azure Foundry / OpenAI-compatible client 时，保持 key 只来自环境变量。
- Phase 6+ 再扩展复杂多 Agent workflow 编排。
