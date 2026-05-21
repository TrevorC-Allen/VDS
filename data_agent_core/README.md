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

当前只建立目录和模块边界，不实现复杂业务逻辑。

## TODO

- Phase 1 实现 File Parser 和 Schema Profiler。
- Phase 1 对齐 response_contracts.py。
- Phase 2 实现 Logic Form、Analysis Plan、Pandas Executor、SQL Executor 和 Verifier。
- Phase 3 接入 Benchmark Runner。
