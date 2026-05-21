# data_agent_core

本目录是 Data Agent 的核心算法层。

## 边界

1. 不依赖 backend。
2. 不依赖 Microsoft Agent Framework。
3. 不依赖 ms_agent_framework_adapter。
4. 不依赖 multi_agent_workflows。
5. 后续文件解析、字段画像、逻辑计划、执行器、校验器、解释器、图表规划器都放在这里。
6. 所有模块未来必须基于 contracts 交互。
7. 所有失败未来必须基于 errors 返回。
8. 所有 analyze 链路未来必须生成 trace。

## 当前阶段

当前已从目录骨架推进到核心算法测试 MVP，并加入 LLM 单 Agent 链路。

当前单 Agent 链路：

1. LLM：Intent Parser
2. LLM + 规则：Column Mapping
3. LLM：Analysis Planner
4. 代码：Pandas Executor
5. 代码：SQL / DuckDB Executor
6. 代码：Result Normalizer
7. 规则 + LLM：Verifier / Critic
8. 规则 + LLM：Correction Planner
9. LLM：Insight Generator
10. LLM + 规则：Chart Planner
11. 后端返回 JSON

LLM API key 只能从环境变量读取，不能写入仓库、trace、文档或 CHANGELOG。LLM 阶段只记录 reasoning summary，不记录完整 Chain of Thought。

## TODO

- Phase 1 实现 File Parser 和 Schema Profiler。
- Phase 1 对齐 response_contracts.py。
- Phase 2 实现 Logic Form、Analysis Plan、Pandas Executor、SQL Executor 和 Verifier。
- Phase 3 接入 Benchmark Runner。
