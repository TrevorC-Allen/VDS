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

状态：2026-05-21 已完成 MVP 并开始业务口径增强，dev 前 10 题当前验证结果为 9/10。

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

状态：2026-05-21 已完成 Phase 1 最小 CSV / Excel 解析入口、DatasetProfile 生成、上传表核心测试；后续仍需增强编码识别、表头不确定处理和多 sheet 策略。

### 双执行路径

目标：支持 Pandas / NumPy 和 SQL / DuckDB 两条执行路径。

影响模块：executors、verifier、contracts。

优先级：P1。

验收标准：两条路径能返回可比较的标准 ExecutionResult。

风险：数值精度、排序、空值和日期标准化。

状态：2026-05-21 已为上传单表的 aggregation / ranking 增加 Pandas 和 SQL fallback 双路径测试；后续需要补 DuckDB runtime、更多过滤/趋势/对比能力和更严格的标准化。

### Benchmark Runner

目标：接入 450 题 Benchmark 评测和错误归因。

影响模块：benchmark、errors、tracing。

优先级：P3。

验收标准：输出按错误类型统计的评测报告。

风险：禁止标准答案泄漏和单题硬编码。

状态：2026-05-21 已支持分段运行、dev 前 10 题评分、all offset 预测、metrics 和 error_analysis 聚合；public all.jsonl answer 为空，不能本地计算完整 450 题官方准确率。

### Minimal Backend API Shell

目标：提供 upload / analyze / profile 的最小后端调用壳，供前端未来接入。

影响模块：backend/services、backend/storage、backend/schemas、backend/routers、tests/backend。

优先级：P1。

验收标准：backend 只调用 data_agent_core，不实现 Pandas / SQL / Verifier 核心逻辑；响应包含 response_version、errors、warnings；analyze 包含 run_id。

风险：当前 TempFileStore 只适合本地和 Phase 1 测试，进程重启后不会恢复 DataFrame tables，后续服务化需要明确 retention 和重新加载策略。

状态：2026-05-21 已完成最小服务壳和测试。

### Controlled Tool Calling Layer

目标：在 Phase 5 引入受控 Tool Calling，把 profile_schema、build_analysis_plan、execute_pandas_plan、execute_sql_plan、verify_results、build_chart_spec、generate_insight 等内部能力包装成模型可选择但代码受控执行的白名单工具。

影响模块：agent_runtime/tool_registry.py、data_agent_core/configs/tool_whitelist.yaml、data_agent_core/llm、data_agent_core/agent、data_agent_core/tracing、ms_agent_framework_adapter/tool_mapping.py、tests/agent_runtime。

优先级：P2，阶段：Phase 5。

验收标准：每个工具必须有稳定名称、JSON schema、参数校验、allowed_roles、timeout、result_policy 和测试覆盖；mock tool-calling 可离线运行；OpenAI / DeepSeek 差异只出现在 provider adapter；trace 只记录工具调用摘要，不记录完整 Chain of Thought 或 raw reasoning tokens。

风险：如果过早启用自由工具调用，模型可能绕过确定性执行器和 Verifier；如果工具 schema 不严格，容易出现参数漂移、隐式任意 SQL、敏感数据泄露或不可复现结果。

状态：2026-05-21 已完成 provider-neutral 契约、本地 dispatcher 和真实内部工具 callable 测试，包括 profile_schema、build_analysis_plan、execute_pandas_plan、execute_sql_plan、verify_results、build_chart_spec、generate_insight；仍未启用 OpenAI / DeepSeek provider 原生工具循环。

### Microsoft Agent Framework Adapter

目标：把内部 AgentRole、ToolDefinition、ToolDispatcher 和 WorkflowState 映射到 Microsoft Agent Framework function tool、Agent 和 sequential workflow。

影响模块：ms_agent_framework_adapter、agent_runtime、tests/ms_agent_framework_adapter、docs。

优先级：P2，阶段：Phase 4/5 到 Phase 6 过渡。

验收标准：adapter 可选导入 `agent_framework`；本地没有安装时有清晰错误；fake framework 测试能验证 function tool 包装和 workflow builder；data_agent_core 不 import Microsoft Agent Framework；adapter 不实现核心算法。

风险：如果让 adapter 承载核心算法，会导致未来无法切换 LangGraph / CrewAI / 自研 runtime。

状态：2026-05-21 已新增 framework_tools、framework_agents、framework_workflow 的可选适配实现和测试，并新增 requirements-ms-agent.txt 作为独立可选依赖入口。

### Phase Gate And Multi-Agent Migration

目标：按 Phase 1 到 Phase 6+ 的门槛推进，先补核心泛化能力和防硬编码测试，再接 Microsoft Agent Framework adapter、Phase 5 受控 Tool Calling 和 Phase 6+ 多 Agent workflow。

影响模块：docs、agent_runtime、ms_agent_framework_adapter、multi_agent_workflows、tests/architecture。

优先级：P0。

验收标准：docs/PHASE_GATES.md 明确每个阶段的进入/退出条件；agent_runtime 提供框架无关 AgentTask / AgentResult / WorkflowState；adapter 映射不 import Microsoft Agent Framework；防 Benchmark 硬编码测试通过。

风险：如果跳过 Phase gate 直接做 Microsoft workflow，容易把核心算法绑死在具体框架里。

状态：2026-05-21 已落地 Phase 6 最小可运行多 Agent workflow。backend 默认 multi_agent；DABstep 多 Agent runner 可跑 dev 前 10，当前回归为 9/10；复杂并行、多轮纠错、ACI associated cost 通用口径和真实 Microsoft cloud workflow 仍属后续增强。

### Phase 6 Multi-Agent Runtime

目标：把主 analyze 链路从单 Agent 编排切换为多 Agent 顺序 workflow。

影响模块：agent_runtime/data_analysis_roles.py、multi_agent_workflows/end_to_end_data_analysis_workflow.py、multi_agent_workflows/dabstep_benchmark_runner.py、backend/services、benchmark wrapper、tests。

优先级：P0。

验收标准：Planner、Data Engineer、Pandas Executor、SQL Executor、Verifier、Correction、Insight、Visualization、Response Builder 都进入 debug.multi_agent_roles；trace 包含 tool_call_summary，debug 包含 tool_call_summaries；DABstep dev 前 10 题仍不低于 80%；data_agent_core 不依赖 multi_agent_workflows。

风险：当前为顺序多 Agent，尚未实现复杂并行、真实 Microsoft cloud execution 和多轮自纠执行。

状态：2026-05-21 已完成最小可运行版本。

### Business Semantic Verification Loop

目标：让 Planner、Data Engineer、Verifier 和 Correction 围绕业务指标定义、候选表和中间计算证据工作，而不是只判断执行是否成功。

影响模块：data_agent_core/contracts、data_agent_core/core/intent_parser.py、data_agent_core/executors、data_agent_core/verifier、data_agent_core/tracing、agent_runtime/data_analysis_roles.py、multi_agent_workflows、tests/core。

优先级：P0，阶段：Phase 6+。

验收标准：LogicForm 能表达 metric_definition、numerator、denominator、group_by、objective 和 options；Verifier 能识别业务口径错误并输出 correction_action；Correction 能生成 corrected LogicForm 并触发受控重跑；trace 能记录 semantic_verification_notes、candidate_table_summary 和 selected_candidate。

风险：如果把 Benchmark dev 题面或答案写入判断，会破坏泛化能力；如果只比较 Pandas / SQL 一致性，可能出现两条路径一致但业务口径错误。

状态：2026-05-21 已完成 fraud volume rate ranking、Verifier semantic correction action、受控重跑 wiring 和合成能力测试；DABstep dev 前 10 回归为 9/10。ACI associated cost 仍需继续按通用 fee what-if candidate table 能力增强。

## TODO

- 新功能进入开发前，先确认是否影响 contracts / API_CONTRACT / tracing / errors。
