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
→ Microsoft Agent Framework Planner Agent

agent_runtime.AgentRole.PANDAS_EXECUTOR
→ Microsoft Agent Framework Tool / Function Step

agent_runtime.AgentRole.SQL_EXECUTOR
→ Microsoft Agent Framework Tool / Function Step

agent_runtime.AgentRole.VERIFIER
→ Microsoft Agent Framework Verifier Agent / Workflow Step

agent_runtime.WorkflowState
→ Microsoft Agent Framework Workflow State / Session State

## 禁止事项

1. 禁止在 adapter 中写文件解析逻辑。
2. 禁止在 adapter 中写 Pandas 执行逻辑。
3. 禁止在 adapter 中写 SQL 执行逻辑。
4. 禁止在 adapter 中写 Benchmark 特判。
5. 禁止让 data_agent_core import ms_agent_framework_adapter。
6. 本轮禁止安装 Microsoft Agent Framework 依赖。

## TODO

- Phase 4 增加最小 demo workflow。
- Phase 4 验证 adapter 不污染核心算法依赖边界。
