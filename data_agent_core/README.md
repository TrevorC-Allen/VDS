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

当前已从目录骨架推进到 Phase 6 最小可运行多 Agent 默认链路，`data_agent_core` 仍保持框架无关。LLM 单 Agent 链路保留为 fallback；核心解析、计划、Pandas / SQL 执行、校验、解释和图表规划仍在本目录内通过稳定 contracts / errors / tracing 交互。

当前核心链路：

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

## Phase Status

- Phase 1：CSV / Excel 最小解析入口、DatasetProfile 和 backend service 调用壳已可测。
- Phase 2：LLM 单 Agent MVP 已可测，保留 fallback。
- Phase 3：Benchmark runner、metrics、error_analysis、trace 和错误归因已可测。
- Phase 5：内部白名单工具能力已由 agent_runtime 包装，真实执行仍回到 data_agent_core。
- Phase 6：多 Agent workflow 默认调用本目录核心能力；DABstep public all 1-450 mock 执行覆盖 450/450，Microsoft 脱敏数据 1-300 mock 离线 scorer 300/300，桌面 VDS `问题汇总.xlsx` 95 题 smoke 95/95。

## TODO

- 继续增强 `best_fraud_aci_choice` / ACI associated cost 的通用 fee what-if 语义，禁止按 DABstep dev 单题或答案特调。
- 将 sqlite fallback 扩展或替换为更完整 DuckDB runtime。
- 扩展更多中文真实业务表、多表场景、字段别名、趋势/状态/毛利/支付方式等复杂中文 BI 能力。
- 接真实 provider-native tool loop 时仍只允许通过 agent_runtime ToolDispatcher 调用本目录受控能力。
