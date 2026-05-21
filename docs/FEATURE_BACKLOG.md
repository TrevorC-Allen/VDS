# FEATURE BACKLOG

## 当前阶段

后续新增功能点统一记录在这里。新功能不能只散落在聊天记录里。

## 功能记录格式

每个功能点需要记录：

1. 目标
2. 影响模块
3. 优先级
4. 验收标准
5. 风险
6. 是否影响 contracts
7. 是否影响 API_CONTRACT
8. 是否影响 tracing
9. 是否影响 errors

## Backlog

### DABstep 核心算法 MVP

目标：支持把 payments.csv 作为业务数据库表，把 manual.md / fees.json / merchant_data.json 作为文档和规则知识库，运行 DABstep 前 10 题核心算法测试。

影响模块：data_agent_core/core、data_agent_core/executors、data_agent_core/verifier、data_agent_core/output、data_agent_core/benchmark、tests/core。

优先级：P0。

验收标准：DABstep dev 前 10 题本地评测准确率不低于 80%，且分析链路不接收 task_id 或标准答案。

风险：当前为规则引擎和通用意图解析 MVP，覆盖的是 DABstep 风格的主要费用规则、聚合、分组和 what-if 问题；尚未覆盖完整 450 题。

状态：2026-05-21 已完成 MVP，dev 前 10 题验证结果为 8/10。

### LLM Single Agent Chain

目标：Agent 必须按固定链路调用 LLM 和代码模块：LLM Intent Parser、LLM + 规则 Column Mapping、LLM Analysis Planner、代码 Pandas Executor、代码 SQL / DuckDB Executor、代码 Result Normalizer、规则 + LLM Verifier / Critic、规则 + LLM Correction Planner、LLM Insight Generator、LLM + 规则 Chart Planner，最后由后端返回 JSON。

影响模块：data_agent_core/llm、data_agent_core/prompts、data_agent_core/agent/single_agent.py、tracing、docs。

优先级：P0。

验收标准：没有环境变量 key 时真实 LLM 模式应失败；mock LLM 模式可用于单元测试；真实 key 只能通过环境变量提供，不进入 Git；trace/debug 中能看到各 LLM 阶段摘要；执行、标准化和评分仍由代码完成。

风险：LLM 输出不稳定，必须通过本地 schema guardrail 限制到受支持 operation，不允许把标准答案或 task_id 传给 LLM。

状态：2026-05-21 已完成 LLM client、stage helper、prompt 文件、单 Agent 阶段 trace 和 mock 测试 wiring。

### CSV / Excel 文件解析

目标：支持上传文件解析并生成 DatasetProfile。

影响模块：data_agent_core/core/file_parser.py、schema_profiler.py、backend。

优先级：P1。

验收标准：能对 csv / xlsx 返回稳定字段画像。

风险：表头识别、编码识别、多 sheet 处理。

### 双执行路径

目标：支持 Pandas / NumPy 和 SQL / DuckDB 两条执行路径。

影响模块：executors、verifier、contracts。

优先级：P1。

验收标准：两条路径能返回可比较的标准 ExecutionResult。

风险：数值精度、排序、空值和日期标准化。

### Benchmark Runner

目标：接入 450 题 Benchmark 评测和错误归因。

影响模块：benchmark、errors、tracing。

优先级：P3。

验收标准：输出按错误类型统计的评测报告。

风险：禁止标准答案泄漏和单题硬编码。

### Phase Gate And Multi-Agent Migration

目标：按 Phase 1 到 Phase 4+ 的门槛推进，先补核心泛化能力和防硬编码测试，再接 Microsoft Agent Framework adapter 和多 Agent workflow。

影响模块：docs、agent_runtime、ms_agent_framework_adapter、multi_agent_workflows、tests/architecture。

优先级：P0。

验收标准：docs/PHASE_GATES.md 明确每个阶段的进入/退出条件；agent_runtime 提供框架无关 AgentTask / AgentResult / WorkflowState；adapter 映射不 import Microsoft Agent Framework；防 Benchmark 硬编码测试通过。

风险：如果跳过 Phase gate 直接做 Microsoft workflow，容易把核心算法绑死在具体框架里。

状态：2026-05-21 开始落地 Phase gate、内部 runtime 契约和 adapter 映射骨架。

## TODO

- 新功能进入开发前，先确认是否影响 contracts / API_CONTRACT / tracing / errors。
