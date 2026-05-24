# ARCHITECTURE

## 当前阶段

当前已实现 Data Agent 最小核心算法、最小 API 壳、内部多 Agent 顺序 workflow、受控工具层和可选 Microsoft adapter 边界；复杂后端业务、前端、部署、权限和生产级 provider tool loop 仍不在当前默认范围。

2026-05-21 更新：当前已新增核心算法 MVP，可在本地直接运行 DABstep 风格数据分析任务。该 MVP 仍保持框架无关，不依赖 Microsoft Agent Framework。

2026-05-21 更新：当前已新增 LLM 单 Agent 链路。Intent Parser、Column Mapping、Analysis Planner、Verifier / Critic、Correction Planner、Insight Generator、Chart Planner 都显式经过 LLM 阶段；代码路径负责 Pandas / SQL 执行、Result Normalizer、规则校验和 Benchmark 评分。

2026-05-21 更新：Phase 1 最小后端调用壳已落地。backend/services 负责临时存储、dataset_id 查询和调用 UploadedDatasetAgent；backend/routers 只做 API 转发；data_agent_core 仍不依赖 backend。

2026-05-21 更新：Phase 5 受控 Tool Calling 契约骨架已落地。agent_runtime 定义 ToolDefinition、ToolCall、ToolResult、ToolTraceEvent、ToolDispatcher 和 Data Agent tool catalog；ms_agent_framework_adapter 只做工具映射，不实现工具逻辑。

2026-05-21 更新：Phase 4/5 的 Microsoft adapter 和内部工具 callable 已开始落地。agent_runtime/data_agent_tool_impl.py 调用既有 data_agent_core 模块；ms_agent_framework_adapter/framework_tools.py、framework_agents.py、framework_workflow.py 只把内部工具、角色和顺序映射到 Microsoft Agent Framework 可选对象。

2026-05-21 更新：Phase 6 最小可运行多 Agent workflow 已落地。backend analyze 默认使用 multi_agent；multi_agent_workflows/end_to_end_data_analysis_workflow.py 负责编排；agent_runtime/data_analysis_roles.py 负责角色执行；data_agent_core 仍不依赖 multi_agent_workflows。

2026-05-21 更新：业务口径驱动校验已开始落地。LogicForm 预留 metric、metric_definition、numerator、denominator、group_by、objective 和 options；Verifier 不只检查 Pandas / SQL 一致性，也检查问题语义和指标定义是否一致；Correction 可输出结构化 corrected LogicForm 并触发受控重跑。

2026-05-21 更新：Phase 7 的 `Not Applicable` 能力缺口闭环已继续推进。Response Builder、trace 和 Benchmark report 会区分 `true_unsupported` 与 `capability_gap`；基础通用能力族已新增 row_count、distinct_count、repeat_entity_percentage、outlier_count、top_k_share、filtered_metric_ranking、null_check、季度过滤、fraud likelihood 多维排名和 fee what-if candidate table，并优先用合成中英文用例验证泛化。

2026-05-21 更新：Phase 7 的 Provider-native tool calling adapter 已建立在 `agent_runtime/provider_native_tool_adapter.py`。该层只把 OpenAI / DeepSeek 兼容 tool schema 和 tool_calls 映射到内部 ToolDefinition / ToolCall / ToolResult，再交给 ToolDispatcher；不实现 DatasetProfile、Pandas、SQL、Verifier、Chart、Insight 或 Benchmark 逻辑。

2026-05-22 更新：ToolDispatcher 已对 timeout_seconds 增加本地 POSIX timeout 执行边界；架构测试新增 tracked-file secret scan，并把 Benchmark 硬编码扫描扩大到 agent_runtime、backend、ms_agent_framework_adapter 和 multi_agent_workflows 的核心源码范围。

2026-05-23 更新：Phase 11 会话隔离、历史续聊和 GPT-like 安静过程展示已进入 planned architecture。后续应在 Workbench 与 DataAgentService 之间增加 Conversation Store / Conversation Service，用 `conversation_id` 管理会话上下文、历史消息、active dataset 和 runs；当前尚未实现，文档只记录后续架构边界。

## 层次边界

1. data_agent_core 是核心算法层。
2. backend 是调用壳，只负责接收请求、临时文件管理、调用核心层和返回结构化 JSON。
3. agent_runtime 是项目内部 Agent 抽象层。
4. ms_agent_framework_adapter 是可选 Microsoft Agent Framework 适配层。
5. multi_agent_workflows 已承载默认 Phase 6 最小顺序多 Agent workflow。
6. docs 是工程契约和扩展需求管理目录。
7. Phase 11 planned Conversation Service 位于 backend 内，负责 `conversation_id`、历史消息、active dataset、runs 和 owner_context 过滤边界；它只能编排已有 upload / analyze 调用，不能承载核心数据分析逻辑。

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
11. 中文问题理解、中文字段名、中文业务术语和中文输出格式是核心主路径；英文问题、英文字段和英文 Benchmark 必须兼容，但不能替代中文验收。

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
5. ToolDispatcher：本地校验工具名、角色、JSON 参数和 timeout_seconds，再调用受控 callable。
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

## 业务口径校验

后续质量提升必须围绕通用业务口径能力，不围绕 Benchmark 单题，也不围绕当前错误样本做伪泛化补丁：

1. Planner 输出的 LogicForm 必须携带指标定义、分子、分母、维度、候选项和目标方向。
2. Data Engineer 负责把 manual / schema profile / guidelines 中的业务定义落入结构化字段。
3. Executor 只执行 LogicForm，不根据题号、标准答案、固定题面、固定字段值、固定候选项或当前错误样本分支。
4. Verifier 必须检查业务口径，例如 fraud ranking 应区分 raw count、transaction rate、volume rate 和 monthly fraud level。
5. Correction 只能输出结构化修正动作，修正后仍要经过 Executor、Comparator 和 Verifier。
6. Trace 记录 metric_definition、candidate_table_summary、selected_candidate 和 semantic_verification_notes，不记录完整 Chain of Thought。
7. 新能力必须能解释迁移边界：适用于哪些数据形态、字段类型、候选项结构、问题表达方式和业务定义来源。
8. 新能力必须用合成/非 Benchmark 用例和同类变体验证，不能只用当前失败 benchmark 题证明。
9. 如果当前修复导致旧代表用例、上传文件场景或同类问题族退化，默认判定为架构方向错误，而不是局部测试波动。
10. 新能力必须优先检查中文表达、中文字段、中文日期/金额/百分比格式和中文业务口径；英文能力必须保持回归，但不能作为唯一通过标准。

## Not Applicable 归因

1. `true_unsupported`：上传规则、manual、schema 或业务知识确实没有定义的问题，例如未定义 danger / fine 阈值，不允许模型臆造答案。
2. `capability_gap`：问题原则上可以由数据或规则回答，但当前 Planner、Parser、Executor 或 Tool 能力族尚未覆盖。
3. Response Builder 对 `capability_gap` 返回 `CAPABILITY_GAP` 错误，避免 benchmark report 把 unexpected Not Applicable 当成正常成功。
4. trace / debug 只记录归因摘要，不记录完整 Chain of Thought、raw reasoning tokens、API key 或敏感原始数据。
5. 新增能力族必须先通过合成或非 Benchmark 用例，再用 DABstep / proxy 作为后验回归观察。

## 中文零售真实数据回归边界

Microsoft 脱敏数据回归只用于暴露中文真实业务表能力缺口，不能把 task_id、标准答案、固定姓名、固定品类或固定输出写入核心链路。

当前中文零售能力必须保持以下边界：

1. Intent Parser 只把中文问题映射为 schema-backed `retail_*` LogicForm。
2. Executor 只根据上传表字段、日期、人员、商品、客户和状态执行通用聚合、排名、计数、比例和字段枚举。
3. 服务客户、目标达成率、拜访成功率、陈列记录、订单状态、今日分销和路线客户关联都必须作为能力族实现。
4. Microsoft 标准答案只允许在离线 scorer 使用，不进入 prompt、Planner、Executor、Verifier、Correction、测试 fixture 或 trace。
5. DABstep 100-130 的 public proxy observation 只能用于后验趋势观察，official 本地准确率仍因 public all answer 为空而不可计算。
6. DABstep hour-of-day 能力作为通用分组能力实现：普通交易量用 `top_count`，离群交易先按 Z-Score / IQR 识别 outlier，再用 `top_outlier_group` 按小时或其他维度统计。

2026-05-22 更新：Microsoft 脱敏数据 41-60 已通过离线 runner 回归到 20/20。该 runner 只在 response 生成后使用标准答案评分，不向 Agent workflow 传入 task_id 或 answer。

## VDS 中文 BI 周期比较边界

VDS 桌面测试数据用于暴露中文 BI 周环比、阈值、异常和多行业指标能力缺口，不能把题号、标准答案、固定文件名或固定实体值写入核心链路。

当前 VDS BI 能力边界：

1. `vds_bi_intent` 只根据上传表 schema、中文实体词和指标 `_row` 字段生成 `vds_*` LogicForm。
2. `vds_bi_executor` 只执行周期比较、排名变化、TopN delta、当前周期过滤指标 TopN、增长数量占比、阈值计数、同圈层异常、分组环比、状态影响、各组 Top 实体、三周期 TopN 和维度环比增长率。
3. 同一套能力必须能迁移到门店、校区、院区、站点和客户，不允许只服务某一个 Excel 文件。
4. LLM stage payload 必须 JSON-safe，pandas Timestamp 等对象必须转为可序列化摘要，不能因复杂表格值中断 Verifier / Insight。
5. VDS 标准答案或人工答案只能用于后验评分或人工检查，不进入 prompt、Planner、Executor、Verifier、Correction、测试 fixture 或 trace。

2026-05-25 更新：当前分支恢复 VDS 标准答案所需的完整中文 BI 能力族，并保留 `vds_current_filtered_metric_top` 对当前周期枚举过滤 TopN 的实体/指标锁定能力。`本周 Pro 套餐 CHR 最高 Top10 客户` 会返回客户 TopN 列表，`本周流失和暂停对 ARR 影响最大的 Top10 客户` 会走状态影响能力族，不会再被通用默认排名误解析为区域维度或订阅收入指标。

当前验证：桌面 VDS `问题汇总.xlsx` 五域全部 95 题标准答案 scorer 为 `95/95`，报告在 `outputs/vds_standard_answer_recheck_20260525_core_fix_v2/report.json`。标准答案仍只在离线 runner 评分阶段使用，不进入核心分析链路。

## 语言优先级

1. 产品使用场景以中文为主，中文理解和中文数据表分析能力优先级高于英文。
2. 英文能力不能放松，DABstep 等英文 Benchmark 仍是回归和泛化观察的一部分。
3. Intent Parser、Column Mapping、Planner、Verifier、Correction 和 Tool schema 必须能表达中英文别名、字段语义和输出格式差异。
4. Executor 不能依赖散落的临时中英文关键词补丁；需要通过 schema/profile/alias/LogicForm 表达可复用语义。
5. 任何能力类 PR 都必须说明中文场景如何验收；如果只覆盖英文，必须明确记录为阶段限制。

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

## Planned Phase 11 会话层

Phase 11 计划新增会话层，但当前尚未实现。该层的目标是让 Workbench 支持多窗口隔离、历史 Chat 续聊和未来用户隔离升级。

计划链路：

用户打开 `/workbench?conversation_id=...`
↓
Workbench 读取或创建 conversation
↓
Conversation Service 恢复 messages、active_dataset_id、runs
↓
上传文件时绑定 conversation_id 和 dataset_id
↓
分析时把 question、run_id、answer summary、safe process summary 追加到 conversation
↓
Workbench 左侧历史 Chat 从 Conversation Service 加载

边界：

1. `conversation_id` 是 UI 续聊和多窗口隔离主键，不替代 `dataset_id` 的数据集身份。
2. dataset / run / conversation 三者分层：dataset 保存上传数据，run 保存一次分析，conversation 保存对话上下文和这些对象的引用。
3. v1 可使用本地匿名 owner scope，但 schema 必须预留 `owner_type`、`owner_id`、`tenant_id`、`created_by` 或统一 `owner_context`。
4. 未来真实用户隔离必须由后端 owner filter 强制执行，不能只靠前端隐藏历史 Chat。
5. 安静过程展示只消费 trace-safe `reasoning_trace_view` 摘要；默认展示一条小号浅灰的最新过程摘要，点击后展开结构化步骤，不展示完整 Chain of Thought、raw prompt、raw reasoning tokens、quality_report、warnings、verification 或 join trace。
6. Conversation Service 不能实现 join、排序、聚合、评分、图表选择或核心分析逻辑；这些仍属于 backend 调用 data_agent_core / multi_agent_workflows 后返回的结果。

## TODO

- 扩展 CSV / Excel 表头识别和多 sheet 策略。
- Phase 7.5：硬化 ToolDispatcher、工具 schema、allowed_roles、timeout、trace-safe summary、Pandas / NumPy 白名单、SQL / DuckDB read-only 限制和文件访问根目录；不开放自由 Python、自由 SQL、shell、网络或任意文件访问。
- Phase 7.6：接入真实 OpenAI / DeepSeek provider-native tool loop smoke；provider adapter 只能把 tool call 转成内部 ToolCall 并交给 ToolDispatcher，不承载 DatasetProfile、Pandas、SQL、Verifier、Chart、Insight 或 Benchmark 逻辑，也不作为生产默认链路。
- Phase 7.7：将 sqlite fallback 替换或扩展为 DuckDB read-only runtime，但保持核心框架无关；DuckDB 路径必须继续经过 Result Normalizer、Verifier 和 trace 摘要。
- Phase 7.8：先为每个 Agent 增加独立测试，再做 Pandas / SQL / DuckDB executor 有限并行和 bounded Correction Loop；Planner、Verifier、Correction 的核心决策不并行。
- Phase 7.9：扩展真实 Microsoft Agent Framework demo；MAF adapter 只承载 AgentRole、ToolDefinition、WorkflowState 映射，不能把核心算法写进 adapter 或 workflow。
- Phase 7.10：继续增强 ACI associated cost、fee what-if candidate table、VDS 趋势/状态/毛利/支付方式等复杂中文 BI 能力，所有修复必须归入能力族并通过合成/非 Benchmark 用例。
- Phase 8 Guardrail / Phase 9.1：Phase 8 只做多文件 / 多表 / join non-regression 守护；Phase 9.1 只做字段确认、join key 确认、澄清交互和评测回看面板，前端不实现指标公式、join 或数据计算。
- Phase 11：先实现 Conversation Store / Service、owner_context 过滤边界和旧 dataset_id 调用兼容，再接前端历史 Chat 与 GPT-like 安静过程 UX；不得把本地匿名会话误写成已实现登录权限。
