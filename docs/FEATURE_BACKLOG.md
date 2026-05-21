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
6. 泛化验证方式
7. 是否影响 contracts
8. 是否影响 API_CONTRACT
9. 是否影响 tracing
10. 是否影响 errors

## Backlog

### DABstep 核心算法 MVP

目标：支持把 payments.csv 作为业务数据库表，把 manual.md / fees.json / merchant_data.json 作为文档和规则知识库，运行 DABstep 前 10 题核心算法测试。

影响模块：data_agent_core/core、data_agent_core/executors、data_agent_core/verifier、data_agent_core/output、data_agent_core/benchmark、tests/core。

优先级：P0。

验收标准：DABstep dev 前 10 题本地评测准确率不低于 80%，且分析链路不接收 task_id、标准答案、固定题面或只适配当前样本的条件分支。

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

风险：禁止标准答案泄漏、单题硬编码和伪泛化补丁；Benchmark 失败只能转成能力族缺口，不能转成当前样本专用逻辑。

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

状态：2026-05-22 已完成 provider-neutral 契约、本地 dispatcher、timeout_seconds 执行边界、真实内部工具 callable 测试和 OpenAI / DeepSeek 兼容 provider-native mock loop，包括 profile_schema、build_analysis_plan、execute_pandas_plan、execute_sql_plan、verify_results、build_chart_spec、generate_insight；仍未把真实 OpenAI / DeepSeek 网络 tool loop 作为生产默认链路。

### Microsoft Agent Framework Adapter

目标：把内部 AgentRole、ToolDefinition、ToolDispatcher 和 WorkflowState 映射到 Microsoft Agent Framework function tool、Agent 和 sequential workflow。

影响模块：ms_agent_framework_adapter、agent_runtime、tests/ms_agent_framework_adapter、docs。

优先级：P2，阶段：Phase 4/5 到 Phase 6 过渡。

验收标准：adapter 可选导入 `agent_framework`；本地没有安装时有清晰错误；fake framework 测试能验证 function tool 包装和 workflow builder；data_agent_core 不 import Microsoft Agent Framework；adapter 不实现核心算法。

风险：如果让 adapter 承载核心算法，会导致未来无法切换 LangGraph / CrewAI / 自研 runtime。

状态：2026-05-21 已新增 framework_tools、framework_agents、framework_workflow 的可选适配实现和测试，并新增 requirements-ms-agent.txt 作为独立可选依赖入口。

### Phase Gate And Multi-Agent Migration

目标：按 Phase 1 到 Phase 6+ 的门槛推进，先补核心泛化能力、防硬编码测试和防伪泛化验收，再接 Microsoft Agent Framework adapter、Phase 5 受控 Tool Calling 和 Phase 6+ 多 Agent workflow。

影响模块：docs、agent_runtime、ms_agent_framework_adapter、multi_agent_workflows、tests/architecture。

优先级：P0。

验收标准：docs/PHASE_GATES.md 明确每个阶段的进入/退出条件；agent_runtime 提供框架无关 AgentTask / AgentResult / WorkflowState；adapter 映射不 import Microsoft Agent Framework；防 Benchmark 硬编码测试通过；新能力必须用合成/非 Benchmark 用例证明不是只修当前样本。

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

风险：如果把 Benchmark dev 题面、答案、固定字段值、固定候选项或当前错误形态写入判断，会破坏泛化能力；如果只比较 Pandas / SQL 一致性，可能出现两条路径一致但业务口径错误。

泛化验证方式：每个新业务语义能力必须至少包含一个合成/非 Benchmark 用例、一个同类变体用例和一个旧代表回归用例；DABstep 只能作为后验回归观察。

状态：2026-05-22 已完成 fraud volume rate ranking、Verifier semantic correction action、受控重跑 wiring、trace 证据、合成能力测试、Not Applicable 第一/二批能力族、DABstep hour-of-day 和 Microsoft 21-40 中文零售能力闭环。DABstep dev 前 10 回归为 9/10。ACI associated cost / best_fraud_aci_choice 仍需继续按通用 fee what-if candidate table 和 associated cost 语义增强，不能只修当前失败样本。

### Chinese-First Multilingual Data Analysis

目标：把中文问题理解、中文字段映射、中文业务术语、中文日期/金额/百分比格式和中文最终回答作为核心主路径，同时保持英文问题、英文字段和英文 Benchmark 的兼容能力。

影响模块：data_agent_core/core、data_agent_core/llm、data_agent_core/prompts、data_agent_core/executors、data_agent_core/verifier、agent_runtime、multi_agent_workflows、tests/core、tests/benchmark、docs。

优先级：P0。

验收标准：能力类改动必须优先说明中文场景验收方式；Intent Parser / Column Mapping / Planner 必须支持中文业务术语和中文字段名；Response Builder 必须保留中文输出格式；英文 DABstep 回归不能退化；任何只覆盖英文的能力必须明确标记为阶段性限制。

风险：如果只围绕英文 Benchmark、英文 prompt 或英文字段设计，会导致实际中文使用场景不可用；如果为中文写固定字段值、固定问法或当前脱敏数据专用规则，会变成伪泛化补丁。

泛化验证方式：每个中文能力族至少包含一个合成/非 Benchmark 中文用例，并保留一个英文或中英混合回归用例；涉及字段映射的能力应覆盖中文字段名、英文字段名和别名表达。

状态：2026-05-21 已将中文优先、英文兼容写入 MAIN_GOAL、BRANCH_RULES、ARCHITECTURE、API_CONTRACT 和 PHASE_GATES；后续能力开发必须按该规则验收。

### Not Applicable Capability Gap Closure

目标：把 `Not Applicable` 拆成可审计的 `true_unsupported` 与 `capability_gap`，并把可回答问题优先路由到可复用能力族，而不是普通兜底。

影响模块：data_agent_core/core/intent_parser.py、data_agent_core/executors、data_agent_core/output/response_builder.py、data_agent_core/tracing、data_agent_core/benchmark、agent_runtime/data_analysis_roles.py、multi_agent_workflows、tests/core、docs/API_CONTRACT.md。

优先级：P0，阶段：Phase 6+。

验收标准：FinalResponse debug / trace / benchmark report 能记录 not_applicable_attribution；`capability_gap` 必须进入 errors 字段并使用 `CAPABILITY_GAP`；新增基础能力族 row_count、distinct_count、repeat_entity_percentage、outlier_count、top_k_share、filtered_metric_ranking 能在合成中英文用例上运行；DABstep / proxy 只作为后验观察。

风险：如果只是把当前 benchmark 失败题的 Not Applicable 改成固定答案或固定字段值，就是伪泛化；如果把所有 Not Applicable 都判为失败，会破坏真正未定义业务概念的安全兜底。

泛化验证方式：每个能力族至少有合成/非 Benchmark 用例，并覆盖中文问题或中文字段名；同时保留英文上传表或 DABstep 回归。

状态：2026-05-22 已完成第一批能力族、Not Applicable 归因、CAPABILITY_GAP 错误类型、trace/debug/report 摘要和合成中英文测试。已继续补齐 null_check、更多英文/中文季度表达、fraud likelihood 多维排名、fee what-if candidate table 和 provider-native tool calling adapter 骨架。DABstep official 本地准确率仍不可计算，public proxy 仅用于后验观察；DABstep 100-130 暴露的 hour-of-day top group / outlier group 已按通用能力族补齐。Microsoft 21-40 中文零售 target / aggregation / ranking / row_count 等能力缺口已用中文零售能力族和合成中文用例闭环。

### Chinese Retail 21-40 Capability Closure

目标：修复 Microsoft 脱敏数据 21-40 暴露的中文零售能力缺口，并把能力沉淀为可复用 operation，而不是围绕题号、标准答案或固定字段值优化。

影响模块：data_agent_core/core/chinese_retail_intent.py、data_agent_core/executors/chinese_retail_executor.py、tests/core/test_chinese_retail_capabilities.py、benchmark report、docs。

优先级：P0，阶段：Phase 6+。

验收标准：支持服务客户数、合约店占比、目标人数、目标达成率、今日分销排名、历史 SKU / 品类排名、拜访成功率、陈列/拜访记录数、冰柜客户数和历史字段枚举；每项能力至少有合成中文用例；标准答案只用于离线 scorer。

风险：如果将脱敏数据中的固定姓名、固定品类、固定答案或 task_id 写入 parser/executor/test fixture，会形成伪泛化补丁。

泛化验证方式：使用合成中文零售表验证同类操作，并保留英文 DABstep / 通用能力回归；Microsoft 21-40 只作为后验回归观察。

状态：2026-05-21 已新增 executor 能力和合成测试；Microsoft 21-40 mock 与真实 LLM 回归均为 20/20。标准答案只用于离线 scorer，未进入 Agent workflow。

### DABstep Hour-Of-Day Group Capability

目标：补齐 DABstep 100-130 暴露的小时分组能力缺口，支持“哪个小时交易最多”和“哪个小时离群交易最多”这类通用问题。

影响模块：data_agent_core/core/intent_parser.py、data_agent_core/executors/pandas_executor.py、tests/core/test_generic_capability_operations.py、benchmark report。

优先级：P0，阶段：Phase 6+。

验收标准：支持按 `hour_of_day` 分组统计交易数；支持按 Z-Score 或 IQR 识别 outlier 后再按小时分组排名；不依赖 DABstep task_id、题面或答案。

风险：如果把能力写成只处理当前两个 task_id，就会形成伪泛化补丁。

泛化验证方式：使用合成 payments 表验证 hour-of-day top count 和 top outlier group；DABstep 100-130 只作为后验执行覆盖观察。

状态：2026-05-21 已完成。DABstep all 100-130 mock 多 Agent 回归 total=31、success_count=31、unexpected_not_applicable=0；official accuracy 仍因 public all answer 为空而不可本地计算。

## TODO

- 新功能进入开发前，先确认是否影响 contracts / API_CONTRACT / tracing / errors。
- 真实 OpenAI / DeepSeek provider-native tool loop、DuckDB runtime、ACI associated cost 通用口径、复杂并行/多轮自纠、DABstep 131+、Microsoft 41+ 和更多中文真实数据仍需按能力族推进。
