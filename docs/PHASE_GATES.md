# PHASE GATES

## 目标

本文件定义从 Phase 1 到 Phase 4+ 的推进门槛，避免为了 Benchmark 单题得分牺牲泛化能力。

## 总红线

1. 禁止根据 Benchmark task_id、题号、标准答案或隐藏答案优化。
2. 禁止把标准答案传入 Intent Parser、Column Mapping、Planner、Executor、Verifier、Correction、Insight 或 Chart Planner。
3. 禁止让 Microsoft Agent Framework 成为 data_agent_core 的依赖。
4. 禁止把核心算法写进 backend、ms_agent_framework_adapter 或 multi_agent_workflows。
5. 所有能力提升必须归入通用模块，例如字段画像、意图识别、执行器、结果标准化、校验、自纠和解释。

## Phase 1：核心算法 + 最小 API

目标：

1. CSV / Excel 文件解析。
2. DatasetProfile / TableProfile / ColumnProfile 稳定返回。
3. 最小 backend API 调用 data_agent_core。
4. analyze 返回 response_version、run_id、errors、warnings、trace 摘要。

进入下一阶段前必须满足：

1. 单文件 CSV / Excel 解析测试通过。
2. schema profiler 能识别数值、日期、分类、ID、金额候选字段。
3. backend router 不包含 Pandas / SQL 核心分析逻辑。
4. 架构边界测试通过。

## Phase 2：单 Agent MVP

目标：

1. 单 Agent 按固定链路运行：LLM Intent Parser → LLM + 规则 Column Mapping → LLM Analysis Planner → 代码执行 → 代码标准化 → 规则 + LLM 校验 → 修正计划 → Insight → Chart。
2. Planner 生成可序列化 LogicForm / AnalysisPlan。
3. Pandas / SQL 执行器不重新理解用户问题。
4. Verifier 不能被绕过。

进入下一阶段前必须满足：

1. 单 Agent trace 中包含每个阶段的结构化摘要。
2. mock LLM 和真实 LLM 都能运行同一条 analyze 链路。
3. DABstep 或其他 Benchmark 只用于评估，不改变核心输入。
4. 防硬编码测试通过。

## Phase 3：Benchmark 评测与错误归因

目标：

1. Benchmark runner 支持分段运行、报告、trace、错误类型统计。
2. evaluator 对齐官方 scorer。
3. 错误归因输出通用模块缺口，而不是单题补丁。

进入下一阶段前必须满足：

1. runner 不把 task_id、question_id、answer、expected_answer 传入 agent.analyze。
2. 报告按 operation、error_type、backend、verification issue 聚合。
3. 修复项必须指向通用能力，例如字段映射、日期解析、聚合口径、TopN 排序、费用规则执行。

## Phase 4：Microsoft Agent Framework Adapter 实验

目标：

1. ms_agent_framework_adapter 只映射 agent_runtime 的 AgentRole、AgentTask、AgentResult 和 WorkflowState。
2. adapter 只负责编排，不实现文件解析、Pandas、SQL、Verifier、Benchmark。
3. data_agent_core 不 import Microsoft Agent Framework。
4. backend 仍调用统一服务入口，不依赖具体 Agent 框架。

进入 Phase 5 前必须满足：

1. adapter 的映射测试通过。
2. Microsoft 依赖只允许出现在 adapter 或独立 demo 中。
3. 不引入任何 data_agent_core → adapter 的反向依赖。
4. 同一 AgentTask 能由自研 runtime 或 Microsoft adapter 映射。

## Phase 5+：多 Agent Workflow

目标：

1. Planner Agent：LLM 为主。
2. Data Engineer Agent：代码为主，LLM 辅助字段语义。
3. Pandas Executor Agent：代码为主。
4. SQL Executor Agent：代码为主。
5. Verifier Agent：规则为主，LLM 辅助。
6. Correction Agent：LLM 生成修正方向，代码执行。
7. Insight Agent：LLM 为主。
8. Visualization Agent：规则 + LLM。
9. Benchmark Agent：代码为主，LLM 辅助错误归因。

验收标准：

1. 多 Agent 只改变编排方式，不改变核心算法位置。
2. 每个 Agent 可独立测试。
3. WorkflowState 可序列化、可追踪、可回归。
4. 可替换为 LangGraph、CrewAI 或自研 runtime，而不重写 data_agent_core。
