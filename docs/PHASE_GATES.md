# PHASE GATES

## 目标

本文件定义从 Phase 1 到 Phase 4+ 的推进门槛，避免为了 Benchmark 单题得分牺牲泛化能力。

## 总红线

1. 禁止根据 Benchmark task_id、题号、标准答案或隐藏答案优化。
2. 禁止把标准答案传入 Intent Parser、Column Mapping、Planner、Executor、Verifier、Correction、Insight 或 Chart Planner。
3. 禁止让 Microsoft Agent Framework 成为 data_agent_core 的依赖。
4. 禁止把核心算法写进 backend、ms_agent_framework_adapter 或 multi_agent_workflows。
5. 所有能力提升必须归入通用模块，例如字段画像、意图识别、执行器、结果标准化、校验、自纠和解释。
6. 禁止把 Tool Calling 变成任意代码、任意 SQL、shell、网络请求或外部文件访问入口；工具只能来自内部白名单和受控执行器。

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

当前状态（2026-05-21）：已达到最小可测状态。CSV 解析、DatasetProfile、backend service upload/profile/analyze、run_id、trace_path、errors/warnings 均已有测试覆盖；Excel 和多 sheet 仍属于增强项。

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

当前状态（2026-05-21）：已达到最小可测状态。单 Agent 链路包含 LLM stages、代码执行、结果标准化、校验、解释和图表规划；mock LLM 可运行单测，真实 LLM 可通过本地环境变量运行。

## Phase 3：Benchmark 评测与错误归因

目标：

1. Benchmark runner 支持分段运行、报告、trace、错误类型统计。
2. evaluator 对齐官方 scorer。
3. 错误归因输出通用模块缺口，而不是单题补丁。

进入下一阶段前必须满足：

1. runner 不把 task_id、question_id、answer、expected_answer 传入 agent.analyze。
2. 报告按 operation、error_type、backend、verification issue 聚合。
3. 修复项必须指向通用能力，例如字段映射、日期解析、聚合口径、TopN 排序、费用规则执行。

当前状态（2026-05-21）：已达到最小可测状态。runner 支持 limit/offset、predictions、trace、metrics、error_analysis；dev 前 10 题可本地评分，public all split 因 answer 为空不能本地计算官方准确率。

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

## Phase 5：受控 Tool Calling 层

目标：

1. 将字段画像、计划构建、Pandas 执行、SQL / DuckDB 执行、结果校验、图表规划和解释生成包装为内部白名单工具。
2. ToolRegistry 支持稳定工具名、JSON schema、参数校验、allowed_roles、timeout、result_policy 和审计摘要。
3. LLM client 增加 provider-neutral 的工具调用循环，可适配 OpenAI Responses API、OpenAI-compatible chat completions 和 DeepSeek tool calls。
4. 工具调用只能发生在受控 stage 内，不能绕过 LogicForm、AnalysisPlan、Executor、Result Normalizer、Verifier 或 Response Builder。
5. thinking / reasoning 相关 provider 字段只在 provider adapter 内部用于续传，不写入稳定 trace、debug 或 API 响应。

进入 Phase 6 前必须满足：

1. mock tool-calling 流程可在无真实 key 环境下完成单元测试。
2. 每个工具都有 JSON schema、白名单声明、参数校验和失败响应。
3. 工具调用 trace 只记录工具名、参数摘要、结果摘要、错误、耗时和 step id，不记录完整 Chain of Thought 或 raw reasoning tokens。
4. OpenAI / DeepSeek provider 差异被限制在 data_agent_core/llm 或 provider adapter 内，data_agent_core 核心契约保持 provider-neutral。
5. 工具调用失败必须进入 errors / warnings，并可由 Verifier 或 Correction Planner 处理。

当前状态（2026-05-21）：未实现。当前只存在 agent_runtime.ToolRegistry 和 ms_agent_framework_adapter.tool_mapping 的骨架；Phase 5 前不得启用模型原生工具调用。

## Phase 6+：多 Agent Workflow

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
