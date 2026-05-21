# ARCHITECTURE

## 当前阶段

当前只定义 Data Agent 的工程边界和扩展方向，不实现复杂业务逻辑。

2026-05-21 更新：当前已新增核心算法 MVP，可在本地直接运行 DABstep 风格数据分析任务。该 MVP 仍保持框架无关，不依赖 Microsoft Agent Framework。

2026-05-21 更新：当前已新增 LLM 单 Agent 链路。Intent Parser、Column Mapping、Analysis Planner、Verifier / Critic、Correction Planner、Insight Generator、Chart Planner 都显式经过 LLM 阶段；代码路径负责 Pandas / SQL 执行、Result Normalizer、规则校验和 Benchmark 评分。

2026-05-21 更新：Phase 1 最小后端调用壳已落地。backend/services 负责临时存储、dataset_id 查询和调用 UploadedDatasetAgent；backend/routers 只做 API 转发；data_agent_core 仍不依赖 backend。

2026-05-21 更新：Phase 5 受控 Tool Calling 契约骨架已落地。agent_runtime 定义 ToolDefinition、ToolCall、ToolResult、ToolTraceEvent、ToolDispatcher 和 Data Agent tool catalog；ms_agent_framework_adapter 只做工具映射，不实现工具逻辑。

2026-05-21 更新：Phase 4/5 的 Microsoft adapter 和内部工具 callable 已开始落地。agent_runtime/data_agent_tool_impl.py 调用既有 data_agent_core 模块；ms_agent_framework_adapter/framework_tools.py、framework_agents.py、framework_workflow.py 只把内部工具、角色和顺序映射到 Microsoft Agent Framework 可选对象。

2026-05-21 更新：Phase 6 最小可运行多 Agent workflow 已落地。backend analyze 默认使用 multi_agent；multi_agent_workflows/end_to_end_data_analysis_workflow.py 负责编排；agent_runtime/data_analysis_roles.py 负责角色执行；data_agent_core 仍不依赖 multi_agent_workflows。

## 层次边界

1. data_agent_core 是核心算法层。
2. backend 是调用壳，只负责接收请求、临时文件管理、调用核心层和返回结构化 JSON。
3. agent_runtime 是项目内部 Agent 抽象层。
4. ms_agent_framework_adapter 是可选 Microsoft Agent Framework 适配层。
5. multi_agent_workflows 已承载默认 Phase 6 最小顺序多 Agent workflow。
6. docs 是工程契约和扩展需求管理目录。

## 依赖规则

1. data_agent_core 不依赖 backend。
2. data_agent_core 不依赖 ms_agent_framework_adapter。
3. data_agent_core 不依赖 multi_agent_workflows。
4. data_agent_core 不依赖 Microsoft Agent Framework。
5. 核心算法保持框架无关。
6. Microsoft Agent Framework 适配层可以调用 agent_runtime 的工具和角色映射，但不能承载核心算法。
7. multi_agent_workflows 可以组合 agent_runtime 角色，但不能把核心算法写进 workflow。
8. LLM client 位于 data_agent_core/llm，不依赖 Microsoft Agent Framework。
9. prompt 位于 data_agent_core/prompts/data_agent_system_prompt.md。
10. API key 只从环境变量读取，不进入 Git、trace、文档或 CHANGELOG。

## 核心链路

用户问题
↓
LLM：Intent Parser
↓
LLM + 规则：Column Mapping
↓
LLM：Analysis Planner
↓
代码：Pandas Executor
↓
代码：SQL / DuckDB Executor
↓
代码：Result Normalizer
↓
规则 + LLM：Verifier / Critic
↓
规则 + LLM：Correction Planner
↓
LLM：Insight Generator
↓
LLM + 规则：Chart Planner
↓
后端返回 JSON

## 单 Agent 职责分工

1. LLM Intent Parser：根据用户问题和 guidelines 输出结构化意图摘要。
2. LLM + 规则 Column Mapping：结合字段语义和代码规则，把指标、维度、过滤条件映射到上传表字段或规则知识库字段。
3. LLM Analysis Planner：生成可序列化 LogicForm 草案。
4. 代码 Pandas Executor：只执行 AnalysisPlan，不重新理解用户问题。
5. 代码 SQL / DuckDB Executor：提供第二条执行路径，当前本地缺少 DuckDB 时使用 sqlite fallback。
6. 代码 Result Normalizer：标准化 Pandas 和 SQL 结果，供比较和 trace 使用。
7. 规则 + LLM Verifier / Critic：规则先判定执行成功、一致性和空结果，LLM 只做辅助审查。
8. 规则 + LLM Correction Planner：最多预留两次修正方向，不能绕过 Verifier 输出结论。
9. LLM Insight Generator：只在结果可信后生成解释和建议。
10. LLM + 规则 Chart Planner：规则先约束图表类型，LLM 辅助选择展示语义。

## 当前多 Agent 映射

1. Planner Agent：LLM 为主。
2. Data Engineer Agent：代码为主，LLM 辅助字段语义。
3. Pandas Executor Agent：代码为主。
4. SQL Executor Agent：代码为主。
5. Verifier Agent：规则为主，LLM 辅助。
6. Correction Agent：LLM 生成修正方向，代码执行。
7. Insight Agent：LLM 为主。
8. Visualization Agent：规则 + LLM。
9. Response Builder：代码为主，生成最终稳定 JSON。
10. Benchmark Agent：代码为主，LLM 辅助错误归因。

这些角色由 agent_runtime 表达，multi_agent_workflows 只负责编排，Microsoft Agent Framework adapter 只负责把角色映射到 framework workflow，不承载核心算法。

当前默认 analyze 顺序：

Planner Agent
↓
Data Engineer Agent
↓
Pandas Executor Agent
↓
SQL Executor Agent
↓
Verifier Agent
↓
Correction Agent
↓
Insight Agent
↓
Visualization Agent
↓
Response Builder

## Phase 5 受控工具层

Phase 5 的工具层只暴露内部白名单工具，不开放任意代码、任意 SQL、shell、网络请求或外部文件访问。

当前 provider-neutral 工具契约和可执行工具层位于 agent_runtime：

1. ToolDefinition：稳定工具名、说明、input_schema、allowed_roles、timeout_seconds、result_policy、constraints。
2. ToolCall：step_id、tool_name、arguments、requested_by。
3. ToolResult：success、output_payload、warnings、errors、trace_event。
4. ToolTraceEvent：只记录工具名、角色、参数摘要、结果摘要、错误和耗时。
5. ToolDispatcher：本地校验工具名、角色和 JSON 参数，再调用受控 callable。
6. DataAgentToolRuntime：保存当前运行会话中的 dataset context / profile，并把工具绑定到 data_agent_core 的既有函数。

当前 Data Agent 白名单工具：

1. profile_schema
2. build_analysis_plan
3. execute_pandas_plan
4. execute_sql_plan
5. verify_results
6. build_chart_spec
7. generate_insight

OpenAI、DeepSeek、Microsoft Agent Framework 只能适配这些内部工具契约，不能把 provider 原生工具格式写成核心算法契约。

## Microsoft Agent Framework Adapter

当前 adapter 只负责可选映射：

1. framework_tools：把内部 ToolDefinition 包装为 Microsoft Agent Framework function tool。
2. framework_agents：把 AgentRole 映射为 Microsoft Agent Framework Agent，并按角色分配白名单工具。
3. framework_workflow：按 Planner → Data Engineer → Pandas Executor → SQL Executor → Verifier → Correction → Insight → Visualization 的顺序构建 sequential workflow。
4. adapter 未安装或未找到 `agent-framework` 时返回清晰错误；测试使用 fake framework 验证映射，不要求本地强制安装。
5. adapter 不写文件解析、Pandas、SQL、Verifier、Benchmark 或评分逻辑。

## DABstep 本地测试链路

当前 DABstep 测试按以下边界处理：

1. payments.csv 是业务数据库表。
2. manual.md 是业务规则文档。
3. fees.json 是结构化费用规则知识库。
4. merchant_data.json 是商户元数据知识库。
5. all.jsonl / dev.jsonl 中的问题只提供 question 和 guidelines 给核心分析链路。
6. answer 字段只允许在 benchmark evaluator 中用于评分，不允许进入 intent parser、executor、verifier 或 response builder。
7. 运行 trace 记录 structured analysis plan、execution trace 和 verification notes，不记录完整 Chain of Thought。

## 上传文件最小链路

当前上传文件链路按以下边界处理：

1. backend 接收文件路径或上传文件，并调用 DataAgentService。
2. DataAgentService 调用 data_agent_core.core.file_parser.parse_dataset_file。
3. File Parser 返回 ParsedDataset，其中包含 tables 和 DatasetProfile。
4. TempFileStore 保存 source_file、profile.json，并在当前进程内保存 DataFrame tables。
5. analyze 时 DataAgentService 根据 dataset_id 取回 tables，默认创建 DataAnalysisMultiAgentWorkflow。
6. DataAnalysisMultiAgentWorkflow 通过 agent_runtime 角色和受控工具执行 Pandas / SQL 双路径、Result Normalizer、Verifier、Insight 和 Chart。
7. trace 写入 storage/runs/{run_id}/trace.json，debug.trace_path 只用于调试，前端不能依赖它作为稳定契约。
8. UploadedDatasetAgent 保留为 single_agent fallback。

## TODO

- 扩展 CSV / Excel 表头识别和多 sheet 策略。
- 将 sqlite fallback 替换或扩展为 DuckDB runtime，但保持核心框架无关。
- 后续再启用 provider 原生 OpenAI / DeepSeek 工具循环；当前先保证内部 dispatcher 和 Microsoft adapter 可测。
- Phase 6 后续再扩展真实 Microsoft Agent Framework demo、并行 executor 和更完整 Correction Loop，不把核心算法写进 workflow。
