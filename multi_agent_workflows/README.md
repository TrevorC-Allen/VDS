# multi_agent_workflows

本目录用于未来多 Agent 编排。

## 当前阶段

1. 当前只是多 Agent workflow 预留目录。
2. 当前不启用复杂多 Agent。
3. 未来会组合 Planner、Data Engineer、Pandas Executor、SQL Executor、Verifier、Insight、Visualization 等角色。
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

## TODO

- Phase 5 从单 Agent MVP 演进到多 Agent workflow。
- 确保多 Agent 只改变编排方式，不改变核心算法位置。
