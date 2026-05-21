# multi_agent_workflows

本目录当前承载 Phase 6 最小多 Agent 编排，后续扩展复杂并行、循环和 Microsoft Agent Framework 承载 workflow。

## 当前阶段

1. 当前已提供 Phase 6 最小可运行多 Agent workflow。
2. 当前不启用复杂并行/循环多 Agent，只启用顺序 role workflow。
3. 当前组合 Planner、Data Engineer、Pandas Executor、SQL Executor、Verifier、Correction、Insight、Visualization、Response Builder。
4. workflow 调用 agent_runtime，不直接写核心算法。
5. workflow 可以由 Microsoft Agent Framework adapter 承载，也可以由自研 runtime 承载。

## 未来结构

DataAnalysisSupervisor
├─ Planner Agent：LLM 为主
├─ Data Engineer Agent：代码为主，LLM 辅助字段语义
├─ Pandas Executor Agent：代码为主
├─ SQL Executor Agent：代码为主
├─ Verifier Agent：规则为主，LLM 辅助
├─ Correction Agent：LLM 生成修正方向，代码执行
├─ Insight Agent：LLM 为主
├─ Visualization Agent：规则 + LLM
└─ Benchmark Agent：代码为主，LLM 辅助错误归因

## Phase 关系

1. Phase 5 已建立受控 Tool Calling 层。
2. Phase 6 已启用内部多 Agent workflow。
3. 多 Agent 调用 agent_runtime 的 provider-neutral 工具契约，但不能直接写核心算法。

## TODO

- 扩展 Microsoft Agent Framework 真实运行 demo。
- 为每个 Agent 增加更细的独立测试。
